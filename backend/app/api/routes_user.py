from fastapi import APIRouter, Request

from ..core.database import get_db
from ..services.auth_service import require_user

# 用户中心相关接口。
router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile")
def profile(request: Request) -> dict:
    # 当前阶段直接复用鉴权解析出来的用户信息。
    user = require_user(request)
    return {"profile": user}


@router.get("/usage/daily")
def usage_daily(request: Request) -> dict:
    # 聚合最近 7 天 token 使用量，供左下角用户菜单展示。
    user = require_user(request)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS usage_date,
                   COALESCE(SUM(total_tokens), 0)::int AS total_tokens
            FROM usage_event
            WHERE user_id = %s
              AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY 1
            ORDER BY 1 ASC
            """,
            (user["id"],),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}
