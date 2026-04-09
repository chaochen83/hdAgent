from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, Response, status

from ..core.config import settings
from ..core.database import get_db
from ..core.security import (
    future_time,
    generate_email_code,
    generate_session_token,
    hash_text,
    sign_value,
    unsign_value,
    utcnow,
)
from .email_service import send_login_code_email


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def build_auth_config() -> dict[str, Any]:
    # 返回给前端的认证能力开关。
    # 前端据此决定显示哪些登录方式、哪些入口标记为“开发中”。
    return {
        "googleAuthEnabled": settings.google_auth_enabled,
        "phoneLoginEnabled": settings.phone_login_enabled,
        "emailProvider": settings.email_provider,
    }


def _set_session_cookie(response: Response, raw_token: str) -> None:
    # 当前先用 HttpOnly Cookie 承载登录态。
    # 生产环境建议在 HTTPS 下把 secure 改为 True。
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # 退出登录时清除浏览器侧 cookie。
    response.delete_cookie(settings.session_cookie_name, path="/")


def build_google_login_url() -> str:
    # 生成跳转到 Google OAuth 的完整 URL。
    # state 会经过签名，用来防止回调被伪造。
    if not settings.google_auth_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google auth is not configured.")
    state = sign_value("google-oauth-state", {"ts": utcnow().isoformat()})
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _upsert_google_user(profile: dict[str, Any]) -> dict[str, Any]:
    # Google 登录回调后，把 Google 用户映射到本地用户体系。
    # 已存在则更新，不存在则创建。
    email = profile.get("email")
    subject = profile.get("sub")
    name = profile.get("name") or (email.split("@")[0] if email else "Makerfabs User")
    avatar_url = profile.get("picture")

    if not subject:
        raise HTTPException(status_code=400, detail="Google profile missing subject.")

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.avatar_url,
                   u.role, u.quota_tier_code, u.is_unlimited,
                   COALESCE(qt.daily_token_limit, %s) AS daily_token_limit
            FROM user_identity i
            JOIN app_user u ON u.id = i.user_id
            LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
            WHERE i.provider = 'google' AND i.provider_subject = %s
            """,
            (settings.default_daily_token_limit, subject),
        ).fetchone()
        if existing:
            # 已绑定过 Google 身份时，只更新展示信息和最近登录时间。
            conn.execute(
                """
                UPDATE app_user
                SET email = COALESCE(%s, email),
                    display_name = %s,
                    avatar_url = COALESCE(%s, avatar_url),
                    is_email_verified = TRUE,
                    last_login_at = NOW()
                WHERE id = %s
                """,
                (email, name, avatar_url, existing["id"]),
            )
            return dict(existing) | {"display_name": name, "avatar_url": avatar_url}

        raise HTTPException(status_code=403, detail="Google 首次注册暂未开放，请先使用邀请码完成邮箱注册。")


def finish_google_login(*, code: str, state: str, response: Response) -> dict[str, Any]:
    # Google OAuth 回调完整收尾流程：
    # 1. 校验 state
    # 2. 用 code 换 access token
    # 3. 拉取 Google 用户资料
    # 4. 同步到本地用户
    # 5. 建立本地 session 并写 cookie
    try:
        unsign_value("google-oauth-state", state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.") from exc

    token_resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20.0,
    )
    token_resp.raise_for_status()
    token_payload = token_resp.json()
    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Google token exchange failed.")

    profile_resp = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    profile_resp.raise_for_status()
    profile = profile_resp.json()

    user = _upsert_google_user(profile)
    raw_token = create_app_session(
        user_id=user["id"],
        user_agent=None,
        ip_address=None,
    )
    _set_session_cookie(response, raw_token)
    return user


def create_app_session(*, user_id: int, user_agent: str | None, ip_address: str | None) -> str:
    # 创建一条本地登录会话记录，并把原始 token 返回给调用方写 cookie。
    raw_token = generate_session_token()
    token_hash = hash_text(raw_token)
    expires_at = future_time(hours=settings.session_ttl_hours)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO auth_session (user_id, session_token_hash, user_agent, ip_address, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, token_hash, user_agent, ip_address, expires_at),
        )
        conn.execute("UPDATE app_user SET last_login_at = NOW() WHERE id = %s", (user_id,))
    return raw_token


def get_current_user(request: Request) -> dict[str, Any] | None:
    # 根据浏览器 cookie 里的 session token 识别当前用户。
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None
    token_hash = hash_text(raw_token)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.avatar_url, u.timezone, u.locale, u.status,
                   u.role, u.quota_tier_code, u.is_unlimited,
                   COALESCE(qt.daily_token_limit, %s) AS daily_token_limit
            FROM auth_session s
            JOIN app_user u ON u.id = s.user_id
            LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
            WHERE s.session_token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
            """,
            (settings.default_daily_token_limit, token_hash),
        ).fetchone()
        if not row:
            return None
        # 每次成功识别用户都刷新 last_seen_at，便于后续统计活跃会话。
        conn.execute(
            "UPDATE auth_session SET last_seen_at = NOW() WHERE session_token_hash = %s",
            (token_hash,),
        )
        return dict(row)


def require_user(request: Request) -> dict[str, Any]:
    # 路由层使用的鉴权保护函数。
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


def logout_current_session(request: Request) -> None:
    # 仅撤销当前这一个 session，不影响该用户其他设备的登录态。
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return
    token_hash = hash_text(raw_token)
    with get_db() as conn:
        conn.execute(
            "UPDATE auth_session SET revoked_at = NOW() WHERE session_token_hash = %s",
            (token_hash,),
        )


def request_email_login_code(*, email: str) -> dict[str, Any]:
    # 邮箱登录第一步：生成验证码、落库、发送邮件。
    code = generate_email_code()
    code_hash = hash_text(code)
    expires_at = future_time(minutes=10)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO email_login_code (email, code_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (email, code_hash, expires_at),
        )
    send_login_code_email(to_email=email, code=code)

    payload: dict[str, Any] = {"ok": True}
    if settings.email_provider == "console" and settings.email_debug_expose_code:
        # 开发模式下把验证码回传给前端，方便本地调试。
        payload["dev_code"] = code
    return payload


def _load_user_with_quota(conn: Any, *, user_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT u.id, u.email, u.display_name, u.avatar_url, u.timezone, u.locale, u.status,
               u.role, u.quota_tier_code, u.is_unlimited,
               COALESCE(qt.daily_token_limit, %s) AS daily_token_limit
        FROM app_user u
        LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
        WHERE u.id = %s
        """,
        (settings.default_daily_token_limit, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return dict(row)


def _consume_invite_code(conn: Any, *, invite_code: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT code, assigned_quota_tier_code, used_count, max_uses, expires_at, status
        FROM invite_code
        WHERE code = %s
        """,
        (invite_code,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="邀请码无效。")
    invite = dict(row)
    if invite["status"] != "active":
        raise HTTPException(status_code=400, detail="邀请码不可用。")
    if invite["expires_at"] and invite["expires_at"] <= utcnow():
        raise HTTPException(status_code=400, detail="邀请码已过期。")
    if invite["used_count"] >= invite["max_uses"]:
        raise HTTPException(status_code=400, detail="邀请码已使用完。")

    conn.execute(
        """
        UPDATE invite_code
        SET used_count = used_count + 1
        WHERE code = %s
        """,
        (invite_code,),
    )
    return invite


def verify_email_login_code(
    *,
    email: str,
    code: str,
    invite_code: str | None,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    # 邮箱登录第二步：校验验证码，必要时自动创建用户，再建立登录态。
    code_hash = hash_text(code)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM email_login_code
            WHERE email = %s
              AND code_hash = %s
              AND used_at IS NULL
              AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (email, code_hash),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="验证码无效或已过期。")

        conn.execute("UPDATE email_login_code SET used_at = NOW() WHERE id = %s", (row["id"],))

        user = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.avatar_url, u.role, u.quota_tier_code,
                   u.is_unlimited, COALESCE(qt.daily_token_limit, %s) AS daily_token_limit
            FROM app_user u
            LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
            WHERE u.email = %s
            """,
            (settings.default_daily_token_limit, email),
        ).fetchone()
        if not user:
            # 邮箱首次登录时，自动完成注册。
            if not invite_code:
                raise HTTPException(status_code=400, detail="新用户注册需要邀请码。")
            invite = _consume_invite_code(conn, invite_code=invite_code.strip())
            fallback_name = email.split("@")[0]
            user = conn.execute(
                """
                INSERT INTO app_user (
                  email, display_name, is_email_verified, last_login_at,
                  role, quota_tier_code, invited_by_code
                )
                VALUES (%s, %s, TRUE, NOW(), 'user', %s, %s)
                RETURNING id
                """,
                (
                    email,
                    fallback_name,
                    invite.get("assigned_quota_tier_code") or settings.default_user_quota_tier,
                    invite["code"],
                ),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO user_identity (user_id, provider, provider_subject, provider_email)
                VALUES (%s, 'email', %s, %s)
                ON CONFLICT (provider, provider_subject) DO NOTHING
                """,
                (user["id"], email, email),
            )
            user = _load_user_with_quota(conn, user_id=user["id"])
        else:
            # 老用户二次登录时，只刷新验证状态与最近登录时间。
            conn.execute(
                """
                UPDATE app_user
                SET is_email_verified = TRUE, last_login_at = NOW()
                WHERE id = %s
                """,
                (user["id"],),
            )
            user = _load_user_with_quota(conn, user_id=user["id"])

    raw_token = create_app_session(
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_session_cookie(response, raw_token)
    return dict(user)
