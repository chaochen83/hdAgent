"""兼容旧启动命令的入口文件。

历史上项目是直接从 `backend.fastapi_app:app` 启动的。
现在真正的主入口已经迁移到 `backend.app.main:app`，
这里仅保留一个轻量转发，避免旧脚本失效。
"""

from .app.main import app

__all__ = ["app"]
