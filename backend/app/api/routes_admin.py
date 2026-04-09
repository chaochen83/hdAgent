from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services.admin_service import (
    create_invite_code,
    get_admin_overview,
    get_chat_messages_for_admin,
    list_admin_users,
    list_chat_sessions_for_admin,
    list_invite_codes,
    update_admin_user,
)
from ..services.auth_service import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserUpdateRequest(BaseModel):
    role: str | None = None
    quota_tier_code: str | None = None
    is_unlimited: bool | None = None


class InviteCodeCreateRequest(BaseModel):
    code: str
    assigned_quota_tier_code: str | None = None
    max_uses: int = 1
    expires_at: str | None = None


@router.get("/overview")
def overview(request: Request, range: str = "7d") -> dict:
    require_admin(request)
    return get_admin_overview(range_key=range)


@router.get("/users")
def users(request: Request) -> dict:
    require_admin(request)
    return {"items": list_admin_users()}


@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: AdminUserUpdateRequest, request: Request) -> dict:
    require_admin(request)
    return {
        "user": update_admin_user(
            user_id=user_id,
            role=payload.role,
            quota_tier_code=payload.quota_tier_code,
            is_unlimited=payload.is_unlimited,
        )
    }


@router.get("/invite-codes")
def invite_codes(request: Request) -> dict:
    require_admin(request)
    return {"items": list_invite_codes()}


@router.post("/invite-codes")
def create_invite(payload: InviteCodeCreateRequest, request: Request) -> dict:
    admin = require_admin(request)
    return {
        "invite_code": create_invite_code(
            code=payload.code.strip(),
            assigned_quota_tier_code=payload.assigned_quota_tier_code,
            max_uses=payload.max_uses,
            expires_at=payload.expires_at,
            created_by_user_id=admin["id"],
        )
    }


@router.get("/chats")
def chats(request: Request, range: str = "7d", user_id: int | None = None) -> dict:
    require_admin(request)
    return {"items": list_chat_sessions_for_admin(user_id=user_id, range_key=range)}


@router.get("/chats/{session_id}/messages")
def chat_messages(session_id: str, request: Request) -> dict:
    require_admin(request)
    return {"items": get_chat_messages_for_admin(session_id=session_id)}
