import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .llm_providers import build_system_prompt, call_provider
from .langgraph_agent import chat_graph  # currently not used by routing
from .schemas import ChatMessage, ChatRequest, ChatState


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 预留：后续可在这里做模型初始化、工具准备等
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
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("Makerfabs AI 后端已启动，但未找到前端 index.html，请确认 frontend 目录。")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """
    SSE 流式输出接口，前端可以随时关闭连接来“暂停”输出。
    """
    system_prompt = build_system_prompt(req.product_model)
    messages = [ChatMessage(role="system", content=system_prompt), *req.messages]

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
                await asyncio.sleep(0)  # allow cancellation
        except asyncio.CancelledError:
            return
        yield "event: end\ndata: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}

