import os
import json
from typing import AsyncGenerator, Dict, Literal, Optional

import httpx

from .schemas import ChatMessage, ChatState


PRODUCT_PROMPTS: Dict[str, str] = {
    "MaTouch_ESP32S3": (
        "You are an embedded engineer helping a user program the MaTouch_ESP32S3 board. "
        "Always return **complete, compilable** ESP32-S3 example code in C/C++ or Arduino style. "
        "Explain briefly in Chinese first, then give the full code. "
        "When you provide code, wrap it in a single Markdown fenced code block like: ```cpp ... ``` . "
        "Do not omit the closing backticks."
    ),
    "ESP32-S3-WROOM-1": (
        "I have an ESP32-S3-WROOM-1 board, IO17 is SDA of I2C, IO18 is SCL of I2C. "
        "When user asks about MPU-6050, generate a code which shows the MPU-6050 data via serial. "
        "When you provide code, wrap it in a single Markdown fenced code block like: ```cpp ... ``` . "
        "Do not omit the closing backticks."
    ),
}


def build_system_prompt(product_model: Optional[str]) -> str:
    base = (
        "You are Makerfabs' hardware AI assistant. "
        "The user is asking about Makerfabs boards and wants **ready-to-flash code**. "
        "Always answer in Chinese. "
        "When you provide code, put it in Markdown fenced code blocks using triple backticks with a language tag, e.g. ```cpp ... ``` . "
        "Also, format the explanation with proper paragraphs and keep list items on separate lines.\n"
    )
    if product_model and product_model in PRODUCT_PROMPTS:
        return base + "\nDevice-specific context:\n" + PRODUCT_PROMPTS[product_model]
    return base


async def _stream_openai_compatible(
    *,
    url: str,
    api_key: str,
    model_name: str,
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
    async for chunk in _stream_openai_compatible(url=url, api_key=api_key, model_name=model_name, messages=messages):
        yield chunk


async def call_openai(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    if not api_key:
        yield "后端未配置 OPENAI_API_KEY，请先在环境变量中设置。"
        return

    url = f"{base_url.rstrip('/')}/chat/completions"
    async for chunk in _stream_openai_compatible(url=url, api_key=api_key, model_name=model_name, messages=messages):
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
    async for chunk in _stream_openai_compatible(url=url, api_key=api_key, model_name=model_name, messages=messages):
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

