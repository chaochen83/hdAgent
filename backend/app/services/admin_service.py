from typing import Any

from fastapi import HTTPException

from ..core.config import settings
from ..core.database import get_db


RANGE_TO_DAYS = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
}


def normalize_range(range_key: str) -> tuple[str, int]:
    value = (range_key or "7d").lower()
    days = RANGE_TO_DAYS.get(value)
    if not days:
        raise HTTPException(status_code=400, detail="Unsupported range.")
    return value, days


def get_admin_overview(*, range_key: str) -> dict[str, Any]:
    normalized_range, days = normalize_range(range_key)
    with get_db() as conn:
        summary = conn.execute(
            """
            SELECT COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens,
                   COUNT(DISTINCT user_id)::int AS active_users
            FROM usage_event
            WHERE created_at >= NOW() - (%s || ' days')::interval
            """,
            (days,),
        ).fetchone()
        if normalized_range == "1d":
            timeline = conn.execute(
                """
                WITH series AS (
                  SELECT generate_series(
                    date_trunc('hour', NOW() - INTERVAL '23 hours'),
                    date_trunc('hour', NOW()),
                    INTERVAL '1 hour'
                  ) AS bucket
                ),
                usage AS (
                  SELECT date_trunc('hour', created_at) AS bucket,
                         SUM(total_tokens)::bigint AS total_tokens
                  FROM usage_event
                  WHERE created_at >= NOW() - INTERVAL '24 hours'
                  GROUP BY 1
                )
                SELECT TO_CHAR(series.bucket, 'YYYY-MM-DD HH24:00') AS usage_date,
                       EXTRACT(HOUR FROM series.bucket)::int AS usage_hour,
                       COALESCE(usage.total_tokens, 0)::bigint AS total_tokens
                FROM series
                LEFT JOIN usage ON usage.bucket = series.bucket
                ORDER BY series.bucket ASC
                """
            ).fetchall()
        else:
            timeline = conn.execute(
                """
                WITH series AS (
                  SELECT generate_series(
                    date_trunc('day', NOW() - (%s - 1) * INTERVAL '1 day'),
                    date_trunc('day', NOW()),
                    INTERVAL '1 day'
                  ) AS bucket
                ),
                usage AS (
                  SELECT date_trunc('day', created_at) AS bucket,
                         SUM(total_tokens)::bigint AS total_tokens
                  FROM usage_event
                  WHERE created_at >= NOW() - (%s || ' days')::interval
                  GROUP BY 1
                )
                SELECT TO_CHAR(series.bucket, 'YYYY-MM-DD') AS usage_date,
                       COALESCE(usage.total_tokens, 0)::bigint AS total_tokens
                FROM series
                LEFT JOIN usage ON usage.bucket = series.bucket
                ORDER BY series.bucket ASC
                """,
                (days, days),
            ).fetchall()
        top_users = conn.execute(
            """
            SELECT u.id, u.display_name, COALESCE(u.email, '') AS email,
                   COALESCE(SUM(ue.total_tokens), 0)::bigint AS total_tokens
            FROM app_user u
            LEFT JOIN usage_event ue
              ON ue.user_id = u.id
             AND ue.created_at >= NOW() - (%s || ' days')::interval
            GROUP BY u.id, u.display_name, u.email
            ORDER BY total_tokens DESC, u.id ASC
            LIMIT 10
            """,
            (days,),
        ).fetchall()

    total_tokens = int(summary["total_tokens"] if summary else 0)
    active_users = int(summary["active_users"] if summary else 0)
    average_tokens = int(total_tokens / active_users) if active_users else 0
    return {
        "range": range_key,
        "summary": {
            "total_tokens": total_tokens,
            "active_users": active_users,
            "average_tokens": average_tokens,
        },
        "timeline": [dict(row) for row in timeline],
        "top_users": [dict(row) for row in top_users],
    }


def list_admin_users() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.role, u.status,
                   u.quota_tier_code, u.is_unlimited, u.created_at, u.last_login_at,
                   COALESCE(qt.daily_token_limit, %s) AS daily_token_limit,
                   COALESCE(today.total_tokens, 0)::bigint AS today_tokens,
                   COALESCE(seven.total_tokens, 0)::bigint AS last_7d_tokens,
                   COALESCE(thirty.total_tokens, 0)::bigint AS last_30d_tokens
            FROM app_user u
            LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
            LEFT JOIN (
              SELECT ue.user_id, SUM(ue.total_tokens) AS total_tokens
              FROM usage_event ue
              JOIN app_user au ON au.id = ue.user_id
              WHERE (ue.created_at AT TIME ZONE au.timezone)::date = (NOW() AT TIME ZONE au.timezone)::date
              GROUP BY ue.user_id
            ) today ON today.user_id = u.id
            LEFT JOIN (
              SELECT user_id, SUM(total_tokens) AS total_tokens
              FROM usage_event
              WHERE created_at >= NOW() - INTERVAL '7 days'
              GROUP BY user_id
            ) seven ON seven.user_id = u.id
            LEFT JOIN (
              SELECT user_id, SUM(total_tokens) AS total_tokens
              FROM usage_event
              WHERE created_at >= NOW() - INTERVAL '30 days'
              GROUP BY user_id
            ) thirty ON thirty.user_id = u.id
            ORDER BY u.created_at DESC, u.id DESC
            """,
            (settings.default_daily_token_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_admin_user(*, user_id: int, role: str | None, quota_tier_code: str | None, is_unlimited: bool | None) -> dict[str, Any]:
    updates: list[str] = []
    params: list[Any] = []
    if role is not None:
        if role not in {"user", "admin"}:
            raise HTTPException(status_code=400, detail="Invalid role.")
        updates.append("role = %s")
        params.append(role)
    if quota_tier_code is not None:
        if quota_tier_code:
            with get_db() as conn:
                exists = conn.execute("SELECT 1 FROM quota_tier WHERE code = %s AND is_active = TRUE", (quota_tier_code,)).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail="Quota tier not found.")
        updates.append("quota_tier_code = %s")
        params.append(quota_tier_code or None)
    if is_unlimited is not None:
        updates.append("is_unlimited = %s")
        params.append(is_unlimited)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes submitted.")

    params.append(user_id)
    with get_db() as conn:
        row = conn.execute(
            f"""
            UPDATE app_user
            SET {", ".join(updates)}
            WHERE id = %s
            RETURNING id
            """,
            tuple(params),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
    users = list_admin_users()
    for user in users:
        if user["id"] == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found.")


def list_invite_codes() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT code, assigned_quota_tier_code, max_uses, used_count, expires_at, status, created_at
            FROM invite_code
            ORDER BY created_at DESC, code DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_invite_code(*, code: str, assigned_quota_tier_code: str | None, max_uses: int, expires_at: str | None, created_by_user_id: int) -> dict[str, Any]:
    with get_db() as conn:
        if assigned_quota_tier_code:
            exists = conn.execute("SELECT 1 FROM quota_tier WHERE code = %s AND is_active = TRUE", (assigned_quota_tier_code,)).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail="Quota tier not found.")
        row = conn.execute(
            """
            INSERT INTO invite_code (
              code, created_by_user_id, assigned_quota_tier_code, max_uses, expires_at
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING code, assigned_quota_tier_code, max_uses, used_count, expires_at, status, created_at
            """,
            (code, created_by_user_id, assigned_quota_tier_code, max_uses, expires_at),
        ).fetchone()
    return dict(row)


def list_chat_sessions_for_admin(*, user_id: int | None, range_key: str) -> list[dict[str, Any]]:
    _, days = normalize_range(range_key)
    params: list[Any] = [days]
    where = ["cs.created_at >= NOW() - (%s || ' days')::interval"]
    if user_id is not None:
        where.append("cs.user_id = %s")
        params.append(user_id)

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT cs.id::text AS id, cs.user_id, cs.title, cs.provider, cs.model,
                   cs.current_product_model, cs.created_at, cs.last_message_at,
                   u.display_name, COALESCE(u.email, '') AS email
            FROM chat_session cs
            JOIN app_user u ON u.id = cs.user_id
            WHERE {" AND ".join(where)}
            ORDER BY cs.last_message_at DESC, cs.created_at DESC
            LIMIT 200
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat_messages_for_admin(*, session_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT cm.id, cm.role, cm.content, cm.prompt_tokens, cm.completion_tokens,
                   cm.total_tokens, cm.created_at
            FROM chat_message cm
            WHERE cm.session_id = %s::uuid
            ORDER BY cm.created_at ASC, cm.id ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]
