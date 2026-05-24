from langgraph.graph import END, StateGraph

from .app.services.knowledge_service import list_active_board_names, resolve_board_for_chat
from .llm_providers import detect_intent_with_llm
from .product_knowledge import PRODUCTS, list_product_models, normalize_text
from .schemas import GraphState

SET_PRODUCT_MODEL_HINTS = (
    "切到",
    "切换到",
    "改成",
    "换成",
    "选择",
    "用",
    "使用",
    "设为",
    "设置为",
    "现在问的是",
    "我要问的是",
)


def _resolve_product_model_from_text(text: str) -> str | None:
    text_n = normalize_text(text or "")
    if not text_n:
        return None
    board = resolve_board_for_chat(text)
    if board:
        return board["name"]
    for model in list_product_models():
        if normalize_text(model) in text_n:
            return model
    for model, cfg in PRODUCTS.items():
        for alias in cfg.get("aliases", []):
            alias_n = normalize_text(alias)
            if alias_n and alias_n in text_n:
                return model
    return None


def _same_product_model(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_text(left) == normalize_text(right))


def _has_explicit_set_product_model_intent(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in SET_PRODUCT_MODEL_HINTS)


def _should_set_product_model(
    *,
    detected_intent: str,
    explicit_model_in_text: str | None,
    current_product_model: str | None,
    last_user_message: str,
) -> bool:
    if detected_intent == "set_product_model":
        return True
    if not explicit_model_in_text:
        return False
    if _has_explicit_set_product_model_intent(last_user_message):
        return True
    if not current_product_model:
        return True
    return not _same_product_model(explicit_model_in_text, current_product_model)


async def intent_node(state: GraphState) -> GraphState:
    product_model_list = list_active_board_names() or list_product_models()
    info = await detect_intent_with_llm(
        provider=state.provider,
        model=state.model,
        messages=state.messages,
        current_product_model=state.current_product_model,
        product_model_list=product_model_list,
    )

    # print (f"intent_node: info={info}")

    last_user = ""
    for m in reversed(state.messages):
        if m.role == "user":
            last_user = m.content
            break

    explicit_model_in_text = _resolve_product_model_from_text(last_user)
    matched = info.get("product_model") or explicit_model_in_text
    detected_intent = info.get("intent", "general_chat")
    fallback_intent = detected_intent if detected_intent in {"generate_code", "general_chat"} else "general_chat"
    intent = detected_intent
    # set_product_model 表示“修改当前会话上下文”，而不是“消息里出现了板型字符串”。
    if _should_set_product_model(
        detected_intent=detected_intent,
        explicit_model_in_text=explicit_model_in_text,
        current_product_model=state.current_product_model,
        last_user_message=last_user,
    ):
        intent = "set_product_model"

    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent=intent,
        fallback_intent=fallback_intent,
        matched_product_model=matched,
    )


def set_product_model_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="set_product_model",
        fallback_intent=state.fallback_intent,
        matched_product_model=state.matched_product_model,
    )


def generate_code_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="generate_code",
        fallback_intent=state.fallback_intent,
        matched_product_model=state.matched_product_model,
    )


def general_chat_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="general_chat",
        fallback_intent=state.fallback_intent,
        matched_product_model=state.matched_product_model,
    )


def route_by_intent(state: GraphState) -> str:
    if state.intent == "set_product_model":
        return "set_product_model"
    if state.intent == "generate_code":
        return "generate_code"
    return "general_chat"


graph_builder = StateGraph(GraphState)
graph_builder.add_node("intent", intent_node)
graph_builder.add_node("set_product_model", set_product_model_node)
graph_builder.add_node("generate_code", generate_code_node)
graph_builder.add_node("general_chat", general_chat_node)
graph_builder.set_entry_point("intent")
graph_builder.add_conditional_edges(
    "intent",
    route_by_intent,
    {
        "set_product_model": "set_product_model",
        "generate_code": "generate_code",
        "general_chat": "general_chat",
    },
)
graph_builder.add_edge("set_product_model", END)
graph_builder.add_edge("generate_code", END)
graph_builder.add_edge("general_chat", END)

chat_graph = graph_builder.compile()
