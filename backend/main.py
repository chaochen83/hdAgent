"""Backward-compatible ASGI entrypoint.

Use `backend.fastapi_app:app` as the canonical app module.
This module remains only so older commands importing `backend.main:app`
continue to work without carrying a second copy of the routes.
"""

# 继续保留旧入口，避免外部部署脚本或文档中的老命令直接失效。
from .app.main import app

__all__ = ["app"]
