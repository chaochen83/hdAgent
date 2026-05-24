from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..schemas.chat import SessionCreateRequest, SessionStreamRequest
from ..services.auth_service import require_user
from ..services.chat_service import create_session, get_session_messages, list_sessions, stream_chat_reply

# 聊天与 Recent 会话相关接口。
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/sessions")
def sessions(request: Request) -> dict:
    # 返回当前用户的 Recent 会话列表。
    user = require_user(request)
    return {"sessions": list_sessions(user_id=user["id"])}


@router.post("/sessions")
def create_chat_session(payload: SessionCreateRequest, request: Request) -> dict:
    # 前端点击 New Chat 时会调用这里。
    user = require_user(request)
    session = create_session(
        user_id=user["id"],
        title=payload.title,
        provider=payload.provider,
        model=payload.model,
        current_product_model=payload.current_product_model,
    )
    return {"session": session}


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, request: Request) -> dict:
    # 恢复某个历史会话的完整消息内容。
    user = require_user(request)
    return {"messages": get_session_messages(user_id=user["id"], session_id=session_id)}


@router.post("/sessions/{session_id}/stream")
async def session_stream(session_id: str, payload: SessionStreamRequest, request: Request) -> StreamingResponse:
    # 与旧版 `/chat/stream` 不同，这里是“按 session 流式聊天”。
    user = require_user(request)
    generator = stream_chat_reply(
        user_id=user["id"],
        session_id=session_id,
        message=payload.message,
        provider=payload.provider,
        model=payload.model,
        current_product_model=payload.current_product_model,
        product_model_switch_decision=payload.product_model_switch_decision,
        pending_product_model=payload.pending_product_model,
        pending_original_message=payload.pending_original_message,
    )
    return StreamingResponse(generator, media_type="text/event-stream")
