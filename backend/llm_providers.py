import os
import json
from typing import Any, AsyncGenerator, Dict, Literal, Optional

import httpx

from .product_knowledge import get_product_knowledge
from .schemas import ChatMessage, ChatState


def _debug_print_llm_request(
    *,
    provider: str,
    model: str,
    api_kind: str,
    messages: list[dict],
) -> None:
    try:
        system_prompt = "\n\n".join(
            m.get("content", "") for m in messages if isinstance(m, dict) and m.get("role") == "system"
        ).strip()
        print("\n===== LLM REQUEST BEGIN =====")
        print(f"provider={provider} model={model} api_kind={api_kind}")
        print("----- SYSTEM PROMPT BEGIN -----")
        print(system_prompt if system_prompt else "(empty)")
        print("----- SYSTEM PROMPT END -------")
        print("----- MESSAGES BEGIN ----------")
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            print(f"[{i}] role={m.get('role')}\n{m.get('content', '')}\n")
        print("----- MESSAGES END ------------")
        print("===== LLM REQUEST END =====\n")
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
    """
    Return JSON:
      {"intent":"set_product_model"|"generate_code"|"general_chat","product_model":"...", "reply":"..."}
    """
    last_user = ""
    for m in reversed(messages):
        if m.role == "user":
            last_user = m.content
            break

    system_prompt = (
        "You are an intent classifier for Makerfabs chat.\n"
        "Decide intent from the conversation context.\n"
        "Allowed intent values: set_product_model, generate_code, general_chat.\n"
        "If user is selecting a product model, map only to one exact item from product_model_list.\n"
        "Never output any model not in product_model_list.\n"
        "Output strict JSON only."
    )
    user_prompt = (
        f"current_product_model={current_product_model}\n"
        f"product_model_list={json.dumps(product_model_list, ensure_ascii=False)}\n"
        f"last_user_message={json.dumps(last_user, ensure_ascii=False)}\n\n"
        "Return JSON with keys: intent, product_model, reply.\n"
        "- reply only used when intent=set_product_model, format: 明白了，您要问的是<型号>。\n"
        "- for other intents reply should be empty string."
    )

    req_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    result = await _chat_completion_non_stream(provider=provider, model=model, messages=req_messages)
    text = (result or "").strip()
    try:
        parsed = json.loads(text)
        intent = parsed.get("intent", "general_chat")
        product_model = parsed.get("product_model")
        reply = parsed.get("reply", "")
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
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model_name=model or os.getenv("OPENAI_MODEL", "gpt-5.4-nano"),
            messages=messages,
        )
    if provider == "qwen":
        return await _openai_compatible_non_stream(
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=os.getenv("QWEN_API_KEY", ""),
            model_name=model or os.getenv("QWEN_MODEL", "qwen-plus"),
            messages=messages,
        )
    return await _openai_compatible_non_stream(
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        model_name=model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=messages,
    )


async def _openai_compatible_non_stream(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    messages: list[dict],
) -> str:
    if not api_key:
        return ""
    _debug_print_llm_request(
        provider=base_url,
        model=model_name,
        api_kind="non-stream",
        messages=messages,
    )
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": messages, "stream": False, "temperature": 0}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 300:
            return ""
        obj = resp.json()
        return (((obj.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()


async def _claude_non_stream(*, model: Optional[str], messages: list[dict]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    model_name = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")
    _debug_print_llm_request(
        provider="claude",
        model=model_name,
        api_kind="non-stream",
        messages=messages,
    )
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
        return "".join(text_parts).strip()


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
    _debug_print_llm_request(
        provider=provider_name,
        model=model_name,
        api_kind="stream",
        messages=[m.model_dump() for m in messages],
    )
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
    _debug_print_llm_request(
        provider="claude",
        model=model_name,
        api_kind="stream",
        messages=[m.model_dump() for m in messages],
    )
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
    in_code_block = False

    async for chunk in stream:
        if not chunk:
            continue

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

