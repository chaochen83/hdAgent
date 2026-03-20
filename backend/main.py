from .fastapi_app import app

__all__ = ["app"]

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from langgraph.graph import END, StateGraph
from pydantic import BaseModel
# from sse_starlette.sse import EventSourceResponse
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

load_dotenv()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    product_model: Optional[str] = None
    provider: Literal["qwen", "openai", "claude"] = "qwen"
    model: Optional[str] = None


class ChatState(BaseModel):
    messages: list[ChatMessage]
    product_model: Optional[str] = None
    provider: str
    model: Optional[str] = None


PRODUCT_PROMPTS: Dict[str, str] = {
    "MaTouch_ESP32S3": (
        "You are an embedded engineer helping a user program the MaTouch_ESP32S3 board. "
        "Always return **complete, compilable** ESP32-S3 example code in C/C++ or Arduino style. "
        "Explain briefly in Chinese first, then give the full code block."
    ),
    "ESP32-S3-WROOM-1": (
        "I have an ESP32-S3-WROOM-1 board, IO17 is SDA of I2C, IO18 is SCL of I2C. "
        "When user asks about MPU-6050, generate a code which shows the MPU-6050 data via serial."
    ),
}


def build_system_prompt(product_model: Optional[str]) -> str:
    base = (
        "You are Makerfabs' hardware AI assistant. "
        "The user is asking about Makerfabs boards and wants **ready-to-flash code**. "
        "Always answer in Chinese, and then provide full code.\n"
    )
    if product_model and product_model in PRODUCT_PROMPTS:
        return base + "\nDevice-specific context:\n" + PRODUCT_PROMPTS[product_model]
    return base


async def call_qwen(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    """
    Stream responses from Alibaba Qwen via an OpenAI-compatible endpoint.
    Configure env:
      QWEN_API_KEY
      QWEN_BASE_URL (e.g. https://dashscope.aliyuncs.com/compatible-mode/v1)
      QWEN_MODEL (default model name if not provided)
    """
    api_key = os.getenv("QWEN_API_KEY")
    base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model_name = model or os.getenv("QWEN_MODEL", "qwen-plus")

    if not api_key:
        yield "后端未配置 QWEN_API_KEY，请先在环境变量中设置。"
        return

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model_name,
        "stream": True,
        "messages": [m.model_dump() for m in messages],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[len("data: ") :]
                else:
                    data = line
                if data == "[DONE]":
                    break
                try:
                    import json

                    obj = json.loads(data)
                    for choice in obj.get("choices", []):
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except Exception:
                    # Best-effort: ignore malformed lines
                    continue


async def call_openai(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    stream = await client.chat.completions.create(
        model=model_name,
        messages=[m.model_dump() for m in messages],
        stream=True,
    )
    async for chunk in stream:
        for choice in chunk.choices:
            delta = choice.delta
            if delta and delta.content:
                yield delta.content


async def call_claude(messages: list[ChatMessage], model: Optional[str]) -> AsyncGenerator[str, None]:
    """
    Simple streaming wrapper for Claude via Anthropic SDK.
    Requires:
      ANTHROPIC_API_KEY
      CLAUDE_MODEL (e.g. claude-3-5-sonnet-latest)
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()
    model_name = model or os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-latest")

    # Anthropic uses its own message format; map from OpenAI-style
    content_messages = []
    system_texts: list[str] = []

    for m in messages:
        if m.role == "system":
            system_texts.append(m.content)
        else:
            content_messages.append({"role": m.role, "content": m.content})

    system_prompt = "\n\n".join(system_texts) if system_texts else None

    stream = await client.messages.create(
        model=model_name,
        max_tokens=2048,
        stream=True,
        system=system_prompt,
        messages=content_messages,
    )
    async for event in stream:
        if event.type == "content_block_delta":
            delta = event.delta
            if getattr(delta, "type", None) == "text_delta":
                text = getattr(delta, "text", None)
                if text:
                    yield text

async def call_provider(state: "ChatState") -> AsyncGenerator[str, None]:
    """
    更稳定的流式缓冲策略：
    - 不按 token flush
    - 按“语义片段”输出
    - 保护代码块结构
    """

    if state.provider == "openai":
        stream = call_openai(state.messages, state.model)
    elif state.provider == "claude":
        stream = call_claude(state.messages, state.model)
    else:
        stream = call_qwen(state.messages, state.model)

    buffer = ""
    in_code_block = False

    async for chunk in stream:
        if not chunk:
            continue

        buffer += chunk

        # 🔥 检测 ``` 代码块状态
        if "```" in buffer:
            parts = buffer.split("```")
            if len(parts) % 2 == 0:
                in_code_block = False
            else:
                in_code_block = True

        # ✅ 1. 如果在代码块里 → 尽量少切
        if in_code_block:
            if len(buffer) > 120:
                yield buffer
                buffer = ""
            continue

        # ✅ 2. 正常文本：按“句子/换行”切
        if any(buffer.endswith(x) for x in [
            "\n\n", "\n", "。", ".", "！", "？", "!", "?", ";", "；"
        ]):
            yield buffer
            buffer = ""

        # ✅ 3. 兜底：太长也要吐
        elif len(buffer) > 80:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer
# async def call_provider(state: ChatState) -> AsyncGenerator[str, None]:
#     if state.provider == "openai":
#         async for chunk in call_openai(state.messages, state.model):
#             yield chunk
#     elif state.provider == "claude":
#         async for chunk in call_claude(state.messages, state.model):
#             yield chunk
#     else:
#         async for chunk in call_qwen(state.messages, state.model):
#             yield chunk


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 挂载前端静态文件目录，假设为项目根目录下的 frontend
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def root_index() -> HTMLResponse:
    """
    返回前端首页（如果存在），否则给出简单提示。
    访问：http://localhost:8000/ 即可打开前端聊天界面。
    """
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("Makerfabs AI 后端已启动，但未找到前端 index.html，请确认 frontend 目录。")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    SSE 流式输出接口，前端可以随时关闭连接来“暂停”输出。
    """

    system_prompt = build_system_prompt(req.product_model)
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_prompt),
        *req.messages,
    ]

    state = ChatState(
        messages=messages,
        product_model=req.product_model,
        provider=req.provider,
        model=req.model,
    )

    async def event_generator():
        try:
            async for token in call_provider(state):
                yield f"event: token\ndata: {token}\n\n"
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            return

        yield "event: end\ndata: [DONE]\n\n"

    # return EventSourceResponse(event_generator())
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )

# 使用 LangGraph 来描述一个极简的对话图（这里主要演示结构，实际调用仍在 FastAPI 里完成）

class GraphState(BaseModel):
    messages: list[ChatMessage]


def echo_node(state: GraphState) -> GraphState:
    # 示例节点：目前只是原样返回，后续可以扩展工具调用、记忆等
    return state


graph_builder = StateGraph(GraphState)
graph_builder.add_node("echo", echo_node)
graph_builder.set_entry_point("echo")
graph_builder.add_edge("echo", END)
chat_graph = graph_builder.compile()

