from fastapi import APIRouter, Request

from ..core.database import get_db
from ..services.auth_service import require_user

# 用户中心相关接口。
router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/profile")
def profile(request: Request) -> dict:
    # 当前阶段直接复用鉴权解析出来的用户信息。
    user = require_user(request)
    with get_db() as conn:
        usage = conn.execute(
            """
            SELECT COALESCE(SUM(ue.total_tokens), 0)::int AS used_tokens
            FROM usage_event ue
            JOIN app_user u ON u.id = ue.user_id
            WHERE ue.user_id = %s
              AND (ue.created_at AT TIME ZONE u.timezone)::date = (NOW() AT TIME ZONE u.timezone)::date
            """,
            (user["id"],),
        ).fetchone()
    profile = dict(user)
    if profile.get("role") == "admin":
        profile["is_unlimited"] = True
    profile["today_used_tokens"] = usage["used_tokens"] if usage else 0
    profile["remaining_tokens"] = None if profile.get("is_unlimited") else max(
        0,
        int((profile.get("daily_token_limit") or 0) - profile["today_used_tokens"]),
    )
    return {"profile": profile}


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
