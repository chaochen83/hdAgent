import os
import json
import re
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Literal, Optional

import httpx

from .product_knowledge import get_product_knowledge
from .schemas import ChatMessage, ChatState


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")


def _resolve_model_name(provider: str, model: Optional[str]) -> str:
    if model:
        return model
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
    if provider == "claude":
        return os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
    if provider == "qwen":
        return os.getenv("QWEN_MODEL", "qwen-plus")
    return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def _format_messages_for_markdown_log(messages: list[dict]) -> str:
    # 生成写入日志文件的 Markdown 文本，方便在 logs/*.md 里按消息逐段查看。
    blocks: list[str] = []
    for idx, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            continue
        role = message.get("role", "unknown")
        content = message.get("content", "")
        blocks.append(f"### Message {idx}\n- role: {role}\n\n```text\n{content}\n```")
    return "\n\n".join(blocks) if blocks else "(empty)"


def _format_messages_for_terminal_log(messages: list[dict]) -> str:
    # 生成终端日志文本。这里不用 Markdown code fence，
    # 改成更直观的起止分隔符，减少 prompt 在 terminal 里“糊成一团”的感觉。
    blocks: list[str] = []
    for idx, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            continue
        role = message.get("role", "unknown")
        content = message.get("content", "")
        blocks.append(
            "\n".join(
                [
                    f"----- MESSAGE {idx} BEGIN -----",
                    f"role: {role}",
                    "content:",
                    content or "(empty)",
                    f"----- MESSAGE {idx} END -----",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else "(empty)"


def _append_llm_log(*, provider: str, model: str, prompt: str, response: str) -> None:
    # 追加到按天分文件的 Markdown 日志中，便于后续回看完整请求与响应。
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        now = datetime.now()
        log_path = os.path.join(LOGS_DIR, f"{now.strftime('%Y-%m-%d')}.md")
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"## {timestamp}\n"
            f"- llm: {provider}\n"
            f"- model: {model}\n\n"
            f"### Prompt\n\n```text\n{prompt}\n```\n\n"
            f"### Response\n\n```text\n{response or '(empty)'}\n```\n\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass


def _summarize_code_block(match: re.Match[str]) -> str:
    # 将 fenced code block 压缩成短摘要，保留语言、规模、首个有效语句，
    # 避免把整段代码原样塞进 intent prompt 里浪费 token。
    raw = match.group(1) or ""
    stripped = raw.strip("\n")
    if not stripped:
        return "[code block omitted]"

    lines = [line.rstrip() for line in stripped.splitlines()]
    language = ""
    body_lines = lines
    first_line = lines[0].strip() if lines else ""

    # Markdown 代码块的第一行如果只是语言标记，则把它和真正代码正文拆开处理。
    if lines and re.fullmatch(r"[A-Za-z0-9_+-]+", first_line):
        language = first_line
        body_lines = lines[1:]

    # 用首个非空代码行做 preview，帮助模型快速理解这段代码大概在做什么。
    non_empty = [line.strip() for line in body_lines if line.strip()]
    preview = non_empty[0][:80] if non_empty else ""
    line_count = len(body_lines)
    parts = ["[code block omitted"]
    if language:
        parts.append(f"lang={language}")
    parts.append(f"lines={line_count}")
    if preview:
        parts.append(f"preview={preview}")
    return ", ".join(parts) + "]"


def _summarize_message_content(content: str, max_chars: int = 320) -> str:
    # 先把消息里的大代码块替换成摘要，再做长度裁剪，给 intent 分类保留关键信息。
    if not content:
        return ""

    summarized = re.sub(r"```(.*?)```", _summarize_code_block, content, flags=re.DOTALL)
    summarized = re.sub(r"\s+", " ", summarized).strip()

    if len(summarized) <= max_chars:
        return summarized
    # 超长文本只保留前半段核心内容，避免历史上下文无限膨胀。
    return summarized[: max_chars - 15].rstrip() + "... [truncated]"


def _build_recent_history_context(messages: list[ChatMessage], max_turns: int = 5) -> str:
    # 把消息流重建成“用户一轮 + 助手若干回复”的对话轮次，
    # 只保留最近几轮历史，兼顾上下文连续性和 token 成本。
    turns: list[dict[str, list[str]]] = []
    current_turn: Optional[dict[str, list[str]]] = None

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "user":
            # 每遇到一个 user 消息，就开启一个新的 turn。
            current_turn = {"user": [message.content], "assistant": []}
            turns.append(current_turn)
            continue
        if current_turn is None:
            # 兜底处理：如果历史异常地以 assistant 开头，也单独归入一个 turn。
            current_turn = {"user": [], "assistant": []}
            turns.append(current_turn)
        current_turn["assistant"].append(message.content)

    if not turns:
        return "(empty)"

    previous_turns = turns[:-1][-max_turns:]
    if not previous_turns:
        return "(no previous turns)"

    blocks: list[str] = []
    for idx, turn in enumerate(previous_turns, start=1):
        # 每一轮内部继续做内容摘要，避免历史里已有长文本或长代码。
        user_text = _summarize_message_content("\n".join(turn["user"]))
        assistant_text = _summarize_message_content("\n".join(turn["assistant"]))
        block_lines = [f"Turn {idx}"]
        if user_text:
            block_lines.append(f"user: {user_text}")
        if assistant_text:
            block_lines.append(f"assistant: {assistant_text}")
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def _log_llm_interaction(*, provider: str, model: str, messages: list[dict], response: str) -> None:
    # 同时输出 terminal 日志和 markdown 日志。
    # terminal 强调可扫读性，文件日志强调结构化留档。
    try:
        terminal_prompt = _format_messages_for_terminal_log(messages)
        markdown_prompt = _format_messages_for_markdown_log(messages)
        print("\n===== LLM LOG BEGIN =====")
        print(f"llm={provider}")
        print(f"model={model}")
        print("prompt messages:")
        print(terminal_prompt)
        print("response:")
        print(response or "(empty)")
        print("===== LLM LOG END =====\n")
        _append_llm_log(provider=provider, model=model, prompt=markdown_prompt, response=response)
    except Exception:
        pass


PRODUCT_PROMPTS: Dict[str, str] = {
    "MaTouch_ESP32S3": (
        "You are an embedded engineer helping a user program the MaTouch_ESP32S3 board. "
        "Always return **complete, compilable** ESP32-S3 example code in C/C++ or Arduino style. "
        "Explain briefly in Chinese first, then give the full code. "
        "When you provide code, wrap it in a single Markdown fenced code block like: ```cpp ... ``` . "
        "If the user asks for pin/connection/configuration instead of full code, provide the relevant pin mapping and wiring guidance (or ask a clarifying question if the exact mapping is unknown). "
        "Do not omit the closing backticks."
    ),
    "ESP32-S3-WROOM-1": (
        "I have an ESP32-S3-WROOM-1 board, IO17 is SDA of I2C, IO18 is SCL of I2C. "
        "If the user asks for I2C pin configuration, answer explicitly: IO17=SDA, IO18=SCL. "
        "When user asks about MPU-6050, generate a code which shows the MPU-6050 data via serial. "
        "When you provide code, wrap it in a single Markdown fenced code block like: ```cpp ... ``` . "
        "If the user asks for wiring/connection, explain how to connect MPU-6050 and other peripherals. "
        "Do not omit the closing backticks."
    ),
}


def build_system_prompt(current_product_model: Optional[str], include_device_context: bool = True) -> str:
    base = (
        "You are Makerfabs' hardware AI assistant. "
        "The user is asking about Makerfabs boards and wants **ready-to-flash code**. "
        "Always answer in Chinese. "
        "When you provide code, put it in Markdown fenced code blocks using triple backticks with a language tag, e.g. ```cpp ... ``` . "
        "Also, format the explanation with proper paragraphs and keep list items on separate lines.\n"
    )
    if include_device_context and current_product_model:
        file_knowledge = get_product_knowledge(current_product_model)
        if file_knowledge:
            return base + "\nDevice-specific background knowledge:\n" + file_knowledge
        if current_product_model in PRODUCT_PROMPTS:
            return base + "\nDevice-specific context:\n" + PRODUCT_PROMPTS[current_product_model]
    return base


async def detect_intent_with_llm(
    *,
    provider: str,
    model: Optional[str],
    messages: list[ChatMessage],
    current_product_model: Optional[str],
    product_model_list: list[str],
) -> Dict[str, Any]:
    # 用独立的分类 prompt 判断当前请求属于：
    # 选产品型号、生成代码，还是普通聊天。
    last_user = ""
    for m in reversed(messages):
        # 只取最后一条 user 消息作为当前轮主问题，
        # 历史上下文则由 recent_history 单独提供。
        if m.role == "user":
            last_user = m.content
            break

    recent_history = _build_recent_history_context(messages)

    system_prompt = (
        "You are an intent classifier for Makerfabs chat.\n"
        "Decide intent from the conversation context.\n"
        "Allowed intent values: set_product_model, generate_code, general_chat.\n"
        "If user is selecting a product model, map only to one exact item from product_model_list.\n"
        "If user is asking for code, set intent to generate_code.\n"
        "Pay attention to the recent conversation history to resolve follow-up requests.\n"
        "Never output any model not in product_model_list.\n"
        "Output strict JSON only. No need to use ```json or any Markdown."
    )
    user_prompt = (
        f"current_product_model={current_product_model}\n"
        f"product_model_list={json.dumps(product_model_list, ensure_ascii=False)}\n"
        f"recent_history={json.dumps(recent_history, ensure_ascii=False)}\n"
        f"last_user_message={json.dumps(last_user, ensure_ascii=False)}\n\n"
        "Return JSON with keys: intent, product_model, reply.\n"
        "- recent_history contains up to 5 previous chat turns, with long code blocks summarized.\n"
        "- reply only used when intent=set_product_model, format: 明白了，您要问的是<型号>。\n"
        "- for other intents reply should be empty string."
    )

    req_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    # intent 分类单独走一次非流式调用，避免影响正式回答链路。
    result = await _chat_completion_non_stream(provider=provider, model=model, messages=req_messages)
    text = (result or "").strip()


    try:
        parsed = json.loads(text)
        intent = parsed.get("intent", "general_chat")

        product_model = parsed.get("product_model")
        reply = parsed.get("reply", "")


        # 模型即使返回了 product_model，也必须再次校验是否在白名单里。
        if product_model and product_model not in product_model_list:
            product_model = None
        if intent not in {"set_product_model", "generate_code", "general_chat"}:
            intent = "general_chat"
        return {"intent": intent, "product_model": product_model, "reply": reply}
    except Exception:
        return {"intent": "general_chat", "product_model": None, "reply": ""}


async def _chat_completion_non_stream(*, provider: str, model: Optional[str], messages: list[dict]) -> str:
    if provider == "claude":
        return await _claude_non_stream(model=model, messages=messages)
    if provider == "openai":
        return await _openai_compatible_non_stream(
            provider_name="openai",
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model_name=model or os.getenv("OPENAI_MODEL", "gpt-5.4-nano"),
            messages=messages,
        )
    if provider == "qwen":
        return await _openai_compatible_non_stream(
            provider_name="qwen",
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("QWEN_API_KEY", ""),
            model_name=model or os.getenv("QWEN_MODEL", "qwen-plus"),
            messages=messages,
        )
    return await _openai_compatible_non_stream(
        provider_name="deepseek",
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        model_name=model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=messages,
    )


async def _openai_compatible_non_stream(
    *,
    provider_name: str,
    base_url: str,
    api_key: str,
    model_name: str,
    messages: list[dict],
) -> str:
    if not api_key:
        return ""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": messages, "stream": False, "temperature": 0}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 300:
            return ""
        obj = resp.json()
        text = (((obj.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        _log_llm_interaction(provider=provider_name, model=model_name, messages=messages, response=text)
        return text


async def _claude_non_stream(*, model: Optional[str], messages: list[dict]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    model_name = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
    system_text = ""
    content_messages: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system_text = (system_text + "\n\n" + m.get("content", "")).strip()
        else:
            content_messages.append({"role": m.get("role"), "content": m.get("content", "")})
    payload: Dict[str, Any] = {
        "model": model_name,
        "max_tokens": 512,
        "messages": content_messages,
    }
    if system_text:
        payload["system"] = system_text
    headers = {
        "x-api-key": api_key,
        "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        "content-type": "application/json",
    }
    url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 300:
            return ""
        obj = resp.json()
        parts = obj.get("content") or []
        text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
        text = "".join(text_parts).strip()
        _log_llm_interaction(provider="claude", model=model_name, messages=messages, response=text)
        return text


async def _stream_openai_compatible(
    *,
    url: str,
    api_key: str,
    model_name: str,
    provider_name: str,
    messages: list[ChatMessage],
    headers_extra: Optional[dict] = None,
    timeout: float = 60.0,
) -> AsyncGenerator[str, None]:
    payload = {
        "model": model_name,
        "stream": True,
        "messages": [m.model_dump() for m in messages],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if headers_extra:
        headers.update(headers_extra)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[len("data: ") :]
                else:
                    data = line
                if data.strip() == "[DONE]":
                    break

                try:
                    obj = json.loads(data)
                except Exception:
                    continue

                for choice in obj.get("choices", []):
                    delta = choice.get("delta", {}) or {}
                    content = delta.get("content")
                    if content:
                        yield content


async def call_qwen(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    api_key = os.getenv("QWEN_API_KEY")
    base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model_name = model or os.getenv("QWEN_MODEL", "qwen-plus")

    if not api_key:
        yield "后端未配置 QWEN_API_KEY，请先在环境变量中设置。"
        return

    url = f"{base_url.rstrip('/')}/chat/completions"
    async for chunk in _stream_openai_compatible(
        url=url, api_key=api_key, model_name=model_name, provider_name="qwen", messages=messages
    ):
        yield chunk


async def call_openai(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-5.4-nano")

    if not api_key:
        yield "后端未配置 OPENAI_API_KEY，请先在环境变量中设置。"
        return

    url = f"{base_url.rstrip('/')}/chat/completions"
    async for chunk in _stream_openai_compatible(
        url=url, api_key=api_key, model_name=model_name, provider_name="openai", messages=messages
    ):
        yield chunk


async def call_deepseek(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    """
    DeepSeek: OpenAI-compatible streaming chat completion.
    Typical endpoint: https://api.deepseek.com/v1/chat/completions
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model_name = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        yield "后端未配置 DEEPSEEK_API_KEY，请先在环境变量中设置。"
        return

    url = f"{base_url.rstrip('/')}/chat/completions"
    async for chunk in _stream_openai_compatible(
        url=url, api_key=api_key, model_name=model_name, provider_name="deepseek", messages=messages
    ):
        yield chunk


async def call_claude(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    """
    Claude streaming via Anthropic Messages API.
    Docs: https://docs.anthropic.com/
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model_name = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
    if not api_key:
        yield "后端未配置 ANTHROPIC_API_KEY，请先在环境变量中设置。"
        return

    system_texts: list[str] = []
    content_messages: list[dict] = []
    for m in messages:
        if m.role == "system":
            system_texts.append(m.content)
        else:
            # Anthropic roles: user/assistant
            content_messages.append({"role": m.role, "content": m.content})

    system_prompt = "\n\n".join(system_texts) if system_texts else None

    url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        "content-type": "application/json",
    }
    payload = {
        "model": model_name,
        "max_tokens": 2048,
        "stream": True,
        "messages": content_messages,
    }
    if system_prompt is not None:
        payload["system"] = system_prompt

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[len("data: ") :]
                else:
                    data = line
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue

                if obj.get("type") == "content_block_delta":
                    delta = obj.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if text:
                            yield text


async def call_provider(state: ChatState) -> AsyncGenerator[str, None]:
    """
    更稳定的流式缓冲策略：
    - 不按 token flush
    - 按“语义片段”输出
    - 保护代码块结构（尽量避免在 ``` 内频繁切割）
    """
    if state.provider == "openai":
        stream = call_openai(state.messages, state.model)
    elif state.provider == "claude":
        stream = call_claude(state.messages, state.model)
    elif state.provider == "deepseek":
        stream = call_deepseek(state.messages, state.model)
    else:
        stream = call_qwen(state.messages, state.model)

    buffer = ""
    full_response = ""
    in_code_block = False
    model_name = _resolve_model_name(state.provider, state.model)
    request_messages = [m.model_dump() for m in state.messages]

    async for chunk in stream:
        if not chunk:
            continue

        full_response += chunk
        buffer += chunk

        # 检测 ``` 代码块状态
        if "```" in buffer:
            parts = buffer.split("```")
            in_code_block = (len(parts) % 2 == 1)

        # 在代码块里：尽量减少切割
        if in_code_block:
            if len(buffer) > 120:
                yield buffer
                buffer = ""
            continue

        # 正常文本：按句子/换行等切
        if any(buffer.endswith(x) for x in ["\n\n", "\n", "。", ".", "！", "？", "!", "?", ";", "；"]):
            yield buffer
            buffer = ""
        elif len(buffer) > 80:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer

    _log_llm_interaction(
        provider=state.provider,
        model=model_name,
        messages=request_messages,
        response=full_response,
    )
