from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from ..schemas.auth import EmailCodeRequest, EmailCodeVerifyRequest
from ..services.auth_service import (
    build_auth_config,
    build_google_login_url,
    clear_session_cookie,
    finish_google_login,
    get_current_user,
    logout_current_session,
    request_email_login_code,
    verify_email_login_code,
)

# 认证相关路由统一挂在 `/api/auth` 下。
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    # 前端首屏会先读取这个接口，决定展示哪些登录方式。
    return build_auth_config()


@router.get("/me")
def me(request: Request) -> dict:
    # 返回当前登录用户；如果未登录则返回 {"user": null}。
    user = get_current_user(request)
    return {"user": user}


@router.get("/google/login")
def google_login() -> RedirectResponse:
    # 浏览器点击后直接跳转 Google OAuth。
    return RedirectResponse(build_google_login_url(), status_code=302)


@router.get("/google/callback")
def google_callback(code: str, state: str, response: Response) -> RedirectResponse:
    # Google 回调成功后统一跳回首页，让前端重新读取登录态。
    redirect = RedirectResponse(url="/?auth=success", status_code=302)
    finish_google_login(code=code, state=state, response=redirect)
    return redirect


@router.post("/email/request-code")
def email_request_code(payload: EmailCodeRequest) -> dict:
    # 邮箱登录第一步：发送验证码。
    return request_email_login_code(email=payload.email)


@router.post("/email/verify-code")
def email_verify_code(payload: EmailCodeVerifyRequest, request: Request, response: Response) -> dict:
    # 邮箱登录第二步：验证验证码并写入登录态 cookie。
    user = verify_email_login_code(
        email=payload.email,
        code=payload.code,
        invite_code=payload.invite_code,
        request=request,
        response=response,
    )
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    # 退出当前设备/浏览器的登录态。
    logout_current_session(request)
    clear_session_cookie(response)
    return {"ok": True}
