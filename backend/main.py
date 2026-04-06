"""Backward-compatible ASGI entrypoint.

Use `backend.fastapi_app:app` as the canonical app module.
This module remains only so older commands importing `backend.main:app`
continue to work without carrying a second copy of the routes.
"""

from .fastapi_app import app

__all__ = ["app"]
