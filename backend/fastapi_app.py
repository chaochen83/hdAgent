import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .llm_providers import build_system_prompt, call_provider
from .langgraph_agent import chat_graph
from .product_knowledge import PRODUCT_MODEL_LIST, get_product_hint
from .schemas import ChatMessage, ChatRequest, ChatState, GraphState

# 在使用 fastapi_app 作为入口时也加载 .env
load_dotenv()


def sse_event(event: str, data: str) -> str:
    normalized = (data or "").replace("\r\n", "\n").replace("\r", "\n")
    data_lines = normalized.split("\n")
    payload = "\n".join(f"data: {line}" for line in data_lines)
    return f"event: {event}\n{payload}\n\n"


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
    async def event_generator():
        graph_state = GraphState(
            messages=req.messages,
            current_product_model=req.current_product_model,
            provider=req.provider,
            model=req.model,
        )
        routed = await chat_graph.ainvoke(graph_state)
        if isinstance(routed, GraphState):
            current_product_model = routed.current_product_model
            intent = routed.intent
            matched_product_model = routed.matched_product_model
        else:
            current_product_model = routed.get("current_product_model")
            intent = routed.get("intent")
            matched_product_model = routed.get("matched_product_model")

        # intent node 判断到用户正在设置产品型号：仅在 product_model_list 中确认，不额外返回列表
        if intent == "set_product_model" and matched_product_model in PRODUCT_MODEL_LIST:
            current_product_model = matched_product_model
            yield sse_event("product_model", current_product_model)
            yield sse_event("token", f"明白了，您要问的是{current_product_model}。{get_product_hint(current_product_model)}")
            yield sse_event("end", "[DONE]")
            return

        # 没有已设置型号，且当前又不是设置型号，则仅追问一次型号
        if not current_product_model:
            yield sse_event("token", "你好，欢迎进入 Makerfabs AI， 你需要问关于那个产品的问题呢？")
            yield sse_event("end", "[DONE]")
            return

        wants_device_context = intent == "generate_code"
        system_prompt = build_system_prompt(current_product_model, include_device_context=wants_device_context)
        messages = [ChatMessage(role="system", content=system_prompt), *req.messages]
        state = ChatState(
            messages=messages,
            current_product_model=current_product_model,
            provider=req.provider,
            model=req.model,
        )

        try:
            async for token in call_provider(state):
                yield sse_event("token", token)
                await asyncio.sleep(0)  # allow cancellation
        except asyncio.CancelledError:
            return
        except Exception as e:
            # 将异常通过 SSE 返回给前端，以便展示“服务器错误（...）”
            detail = str(e).replace("\n", "\\n").replace("\r", "\\r")
            yield sse_event("error", detail)
            yield sse_event("end", "[DONE]")
            return
        yield sse_event("end", "[DONE]")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/product-model-list")
async def product_model_list() -> dict:
    return {"product_model_list": PRODUCT_MODEL_LIST}


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
