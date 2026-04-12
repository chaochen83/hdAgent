import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes_auth import router as auth_router
from .api.routes_admin import router as admin_router
from .api.routes_chat import router as chat_router
from .api.routes_knowledge import router as knowledge_router
from .api.routes_knowledge_public import router as knowledge_public_router
from .api.routes_user import router as user_router
from .core.config import settings

load_dotenv()

# 前端静态资源目录仍然由 FastAPI 直接托管，方便当前阶段快速联调。
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 这里预留给后续初始化逻辑，例如：
    # 连接池、后台任务调度器、向量库客户端等。
    yield


# 当前主应用入口。`backend.fastapi_app:app` 和 `backend.main:app`
# 都只是兼容旧命令，最终都会转发到这里。
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# 路由按业务模块拆分，便于后续继续扩展知识库模块。
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(knowledge_public_router)
app.include_router(user_router)


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    # 前端首屏初始化接口。
    # 返回一些不会频繁变化的运行时能力开关，避免前端写死。
    return {
        "appName": settings.app_name,
        "features": {
            "knowledgeBase": True,
            "adminPanel": True,
            "phoneLogin": settings.phone_login_enabled,
            "mcpGithub": settings.mcp_github_enabled,
        },
        "auth": {
            "googleEnabled": settings.google_auth_enabled,
        },
    }


@app.get("/product-model-list")
def product_model_list() -> dict:
    from ..product_knowledge import PRODUCT_MODEL_LIST
    from .services.knowledge_service import list_active_board_names

    # 当前支持的产品型号列表，前端用它来渲染下拉框。
    return {"product_model_list": list_active_board_names() or PRODUCT_MODEL_LIST}


@app.get("/health")
def health() -> dict:
    # 基础健康检查接口，部署时可用于 readiness/liveness 探测。
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    # 根路由始终返回前端首页，让前后端保持同域。
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
