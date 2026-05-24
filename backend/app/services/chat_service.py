import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import HTTPException

from ...llm_providers import build_system_prompt, call_provider
from ...langgraph_agent import chat_graph
from ...product_knowledge import get_product_hint
from ...schemas import ChatMessage, ChatState, GraphState
from ..core.config import settings
from ..core.database import get_db
from ..knowledge.retrieval import build_rag_context
from .knowledge_service import resolve_board_for_chat


def sse_event(event: str, data: str) -> str:
    # 手工拼装 SSE 文本协议，兼容前端 fetch + ReadableStream 的解析方式。
    normalized = (data or "").replace("\r\n", "\n").replace("\r", "\n")
    payload = "\n".join(f"data: {line}" for line in normalized.split("\n"))
    return f"event: {event}\n{payload}\n\n"


def list_sessions(*, user_id: int) -> list[dict[str, Any]]:
    # Recent 列表按最近消息时间倒序返回。
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, title, current_product_model, provider, model,
                   created_at, updated_at, last_message_at
            FROM chat_session
            WHERE user_id = %s AND archived_at IS NULL
            ORDER BY last_message_at DESC, created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_session(
    *,
    user_id: int,
    title: str | None,
    provider: str,
    model: str | None,
    current_product_model: str | None,
) -> dict[str, Any]:
    # 新建聊天 session。标题先给默认值，首条用户消息进来后再自动覆盖。
    final_title = (title or "New chat").strip() or "New chat"
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO chat_session (user_id, title, provider, model, current_product_model)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id::text AS id, title, current_product_model, provider, model,
                      created_at, updated_at, last_message_at
            """,
            (user_id, final_title[:200], provider, model, current_product_model),
        ).fetchone()
    return dict(row)


def get_session(*, user_id: int, session_id: str) -> dict[str, Any]:
    # 先校验 session 属于当前登录用户，避免越权访问别人的历史会话。
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id::text AS id, user_id, title, current_product_model, provider, model,
                   created_at, updated_at, last_message_at
            FROM chat_session
            WHERE id = %s::uuid AND user_id = %s AND archived_at IS NULL
            """,
            (session_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found.")
    return dict(row)


def get_session_messages(*, user_id: int, session_id: str) -> list[dict[str, Any]]:
    # 拉取单个会话下的完整消息历史，供前端恢复对话。
    get_session(user_id=user_id, session_id=session_id)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM chat_message
            WHERE session_id = %s::uuid
            ORDER BY created_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _estimate_tokens(text: str) -> int:
    # 当前只是轻量估算，目的是先把 usage 和 message 表结构跑通。
    # 后续可替换成按模型精确计数。
    return max(1, len((text or "").strip()) // 4) if text and text.strip() else 0


def _truncate_title(text: str) -> str:
    # 用首条用户消息生成 Recent 列表标题。
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return "New chat"
    return normalized[:80]


def _build_knowledge_links(rows: list[dict[str, Any]], *, max_items: int = 3) -> str:
    if not rows:
        return ""
    items = []
    for index, row in enumerate(rows[:max_items], start=1):
        label = row.get("title") or row.get("source_name") or f"板卡资料 {index}"
        items.append(f"- [板卡资料 {index}: {label}](/knowledge/chunks/{row['id']})")
    return "\n".join(items)


def _same_product_model(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().lower() == right.strip().lower())


def _should_confirm_product_model_switch(
    *,
    current_product_model: str | None,
    matched_product_model: str | None,
    intent: str | None,
    switch_decision: str | None,
) -> bool:
    return bool(
        not switch_decision
        and current_product_model
        and matched_product_model
        and intent == "set_product_model"
        and not _same_product_model(current_product_model, matched_product_model)
    )


def _assert_chat_rate_limit(*, user_id: int) -> None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int AS request_count
            FROM chat_request_log
            WHERE user_id = %s
              AND created_at >= NOW() - (%s || ' seconds')::interval
            """,
            (user_id, settings.chat_rate_limit_window_seconds),
        ).fetchone()
        if row and row["request_count"] >= settings.chat_rate_limit_count:
            raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试。")
        conn.execute(
            """
            INSERT INTO chat_request_log (user_id)
            VALUES (%s)
            """,
            (user_id,),
        )


def _assert_daily_quota(*, user_id: int) -> None:
    with get_db() as conn:
        user = conn.execute(
            """
            SELECT u.role, u.is_unlimited, qt.daily_token_limit
            FROM app_user u
            LEFT JOIN quota_tier qt ON qt.code = u.quota_tier_code
            WHERE u.id = %s
            """,
            (user_id,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        if user["role"] == "admin" or user["is_unlimited"]:
            return

        daily_limit = user["daily_token_limit"] or settings.default_daily_token_limit
        used = conn.execute(
            """
            SELECT COALESCE(SUM(ue.total_tokens), 0)::int AS used_tokens
            FROM usage_event ue
            JOIN app_user u ON u.id = ue.user_id
            WHERE ue.user_id = %s
              AND (ue.created_at AT TIME ZONE u.timezone)::date = (NOW() AT TIME ZONE u.timezone)::date
            """,
            (user_id,),
        ).fetchone()
        if used and used["used_tokens"] >= daily_limit:
            raise HTTPException(status_code=403, detail="超出当日额度，请联系管理员升级账号。")


async def stream_chat_reply(
    *,
    user_id: int,
    session_id: str,
    message: str | None,
    provider: str,
    model: str | None,
    current_product_model: str | None,
    product_model_switch_decision: str | None = None,
    pending_product_model: str | None = None,
    pending_original_message: str | None = None,
) -> AsyncGenerator[str, None]:
    # 聊天主流程：
    # 1. 写入用户消息
    # 2. 还原历史上下文
    # 3. 交给 LangGraph 判断意图
    # 4. 若需要先确认产品型号，则直接回复
    # 5. 否则进入大模型流式生成
    # 6. 把 assistant 回复和 usage 落库
    session = get_session(user_id=user_id, session_id=session_id)
    incoming_message = pending_original_message if product_model_switch_decision else message
    text = (incoming_message or "").strip()
    answer_prefix = ""
    if not text:
        yield sse_event("error", "消息不能为空。")
        yield sse_event("end", "[DONE]")
        return
    try:
        _assert_chat_rate_limit(user_id=user_id)
        _assert_daily_quota(user_id=user_id)
    except HTTPException as exc:
        yield sse_event("error", str(exc.detail))
        yield sse_event("end", "[DONE]")
        return

    if not product_model_switch_decision:
        with get_db() as conn:
            # 先落用户消息，确保刷新页面后历史能立即看到。
            conn.execute(
                """
                INSERT INTO chat_message (session_id, role, content, prompt_tokens, total_tokens)
                VALUES (%s::uuid, 'user', %s, %s, %s)
                """,
                (session_id, text, _estimate_tokens(text), _estimate_tokens(text)),
            )
            conn.execute(
                """
                UPDATE chat_session
                SET provider = %s,
                    model = %s,
                    current_product_model = COALESCE(%s, current_product_model),
                    last_message_at = NOW(),
                    title = CASE WHEN title = 'New chat' THEN %s ELSE title END
                WHERE id = %s::uuid
                """,
                (provider, model, current_product_model, _truncate_title(text), session_id),
            )

    history_rows = get_session_messages(user_id=user_id, session_id=session_id)
    history = [ChatMessage(role=row["role"], content=row["content"]) for row in history_rows]
    if product_model_switch_decision and history and history[-1].role == "assistant":
        history = history[:-1]
    session_product_model = current_product_model or session.get("current_product_model")

    if product_model_switch_decision == "yes" and pending_product_model:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE chat_session
                SET current_product_model = %s, provider = %s, model = %s, last_message_at = NOW()
                WHERE id = %s::uuid
                """,
                (pending_product_model, provider, model, session_id),
            )
        session_product_model = pending_product_model
        answer_prefix = f"已切换到{pending_product_model}，下面继续回答你的问题。\n\n"

    graph_state = GraphState(
        messages=history,
        current_product_model=session_product_model,
        provider=provider,
        model=model,
    )
    routed = await chat_graph.ainvoke(graph_state)
    state = routed if isinstance(routed, GraphState) else GraphState(**routed)
    resolved_product_model = state.current_product_model
    persist_product_model = resolved_product_model

    if _should_confirm_product_model_switch(
        current_product_model=session_product_model,
        matched_product_model=state.matched_product_model,
        intent=state.intent,
        switch_decision=product_model_switch_decision,
    ):
        content = (
            f"当前会话已经是{session_product_model}，检测到你这次提到了{state.matched_product_model}。"
            "要切换当前会话板型吗？"
        )
        payload = json.dumps(
            {
                "current_product_model": session_product_model,
                "pending_product_model": state.matched_product_model,
                "original_message": text,
            },
            ensure_ascii=False,
        )
        with get_db() as conn:
            completion_tokens = _estimate_tokens(content)
            conn.execute(
                """
                INSERT INTO chat_message (session_id, role, content, completion_tokens, total_tokens)
                VALUES (%s::uuid, 'assistant', %s, %s, %s)
                """,
                (session_id, content, completion_tokens, completion_tokens),
            )
            conn.execute(
                """
                INSERT INTO usage_event (user_id, session_id, provider, model, completion_tokens, total_tokens)
                VALUES (%s, %s::uuid, %s, %s, %s, %s)
                """,
                (user_id, session_id, provider, model, completion_tokens, completion_tokens),
            )
        yield sse_event("confirm_product_model_switch", payload)
        yield sse_event("token", content)
        yield sse_event("end", "[DONE]")
        return

    if product_model_switch_decision == "no":
        state.intent = state.fallback_intent or "general_chat"
        if pending_product_model:
            resolved_product_model = pending_product_model
        persist_product_model = session_product_model

    if (
        product_model_switch_decision == "yes"
        and state.intent == "set_product_model"
        and _same_product_model(state.matched_product_model, session_product_model)
    ):
        state.intent = state.fallback_intent or "general_chat"
        resolved_product_model = session_product_model
        persist_product_model = session_product_model

    if state.intent == "set_product_model" and state.matched_product_model:
        # 如果本轮是在“设置产品型号”，就不调用大模型，直接写回会话状态并回复确认文案。
        resolved_product_model = state.matched_product_model
        persist_product_model = resolved_product_model
        with get_db() as conn:
            conn.execute(
                """
                UPDATE chat_session
                SET current_product_model = %s, last_message_at = NOW()
                WHERE id = %s::uuid
                """,
                (resolved_product_model, session_id),
            )
        content = f"明白了，您要问的是{resolved_product_model}。{get_product_hint(resolved_product_model)}"
        with get_db() as conn:
            completion_tokens = _estimate_tokens(content)
            conn.execute(
                """
                INSERT INTO chat_message (session_id, role, content, completion_tokens, total_tokens)
                VALUES (%s::uuid, 'assistant', %s, %s, %s)
                """,
                (session_id, content, completion_tokens, completion_tokens),
            )
            conn.execute(
                """
                INSERT INTO usage_event (user_id, session_id, provider, model, completion_tokens, total_tokens)
                VALUES (%s, %s::uuid, %s, %s, %s, %s)
                """,
                (user_id, session_id, provider, model, completion_tokens, completion_tokens),
            )
        yield sse_event("product_model", resolved_product_model)
        yield sse_event("token", content)
        yield sse_event("end", "[DONE]")
        return

    if not resolved_product_model:
        # 没拿到产品型号时，统一先追问一次型号。
        content = "你好，欢迎进入 Makerfabs Agent。请先告诉我你在问哪个产品型号。"
        with get_db() as conn:
            completion_tokens = _estimate_tokens(content)
            conn.execute(
                """
                INSERT INTO chat_message (session_id, role, content, completion_tokens, total_tokens)
                VALUES (%s::uuid, 'assistant', %s, %s, %s)
                """,
                (session_id, content, completion_tokens, completion_tokens),
            )
        yield sse_event("token", content)
        yield sse_event("end", "[DONE]")
        return

    system_prompt = build_system_prompt(
        resolved_product_model,
        include_device_context=state.intent == "generate_code",
    )
    board = resolve_board_for_chat(resolved_product_model)
    rag_rows: list[dict[str, Any]] = []
    if board and board.get("id"):
        rag_context, rag_rows = await build_rag_context(
            board_type_id=board["id"],
            query=text,
            limit=settings.knowledge_top_k,
        )
        if rag_context:
            system_prompt = (
                f"{system_prompt}\n\n"
                "Board knowledge retrieved from the managed knowledge base:\n"
                f"{rag_context}\n\n"
                "Use the retrieved knowledge when it is relevant. If it conflicts with the user's latest input, explain the conflict."
            )
    messages = [ChatMessage(role="system", content=system_prompt), *history]
    llm_state = ChatState(
        messages=messages,
        current_product_model=resolved_product_model,
        provider=provider,
        model=model,
    )

    buffer = ""
    started_at = time.perf_counter()
    try:
        if resolved_product_model and _same_product_model(resolved_product_model, persist_product_model):
            yield sse_event("product_model", resolved_product_model)
        if answer_prefix:
            buffer += answer_prefix
            yield sse_event("token", answer_prefix)
        # 真正的大模型流式输出在这里发生。
        async for token in call_provider(llm_state):
            buffer += token
            yield sse_event("token", token)
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        yield sse_event("error", str(exc))
        yield sse_event("end", "[DONE]")
        return

    source_links = _build_knowledge_links(rag_rows)
    if source_links:
        citation_block = f"\n\n参考资料：\n{source_links}"
        buffer += citation_block
        yield sse_event("token", citation_block)

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    prompt_tokens = sum(_estimate_tokens(item.content) for item in messages)
    completion_tokens = _estimate_tokens(buffer)
    total_tokens = prompt_tokens + completion_tokens
    with get_db() as conn:
        # 回复完成后，再把 assistant 消息、usage 和最新产品型号一次性写回数据库。
        conn.execute(
            """
            INSERT INTO chat_message (
              session_id, role, content, prompt_tokens, completion_tokens, total_tokens, latency_ms
            )
            VALUES (%s::uuid, 'assistant', %s, %s, %s, %s, %s)
            """,
            (session_id, buffer, prompt_tokens, completion_tokens, total_tokens, latency_ms),
        )
        conn.execute(
            """
            UPDATE chat_session
            SET current_product_model = %s, last_message_at = NOW()
            WHERE id = %s::uuid
            """,
            (persist_product_model, session_id),
        )
        conn.execute(
            """
            INSERT INTO usage_event (
              user_id, session_id, provider, model, prompt_tokens, completion_tokens, total_tokens
            )
            VALUES (%s, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (user_id, session_id, provider, model, prompt_tokens, completion_tokens, total_tokens),
        )
    yield sse_event("end", "[DONE]")
