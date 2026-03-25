from langgraph.graph import END, StateGraph

from .llm_providers import detect_intent_with_llm
from .product_knowledge import PRODUCTS, list_product_models, normalize_text
from .schemas import GraphState


def _resolve_product_model_from_text(text: str) -> str | None:
    text_n = normalize_text(text or "")
    if not text_n:
        return None
    for model in list_product_models():
        if normalize_text(model) in text_n:
            return model
    for model, cfg in PRODUCTS.items():
        for alias in cfg.get("aliases", []):
            alias_n = normalize_text(alias)
            if alias_n and alias_n in text_n:
                return model
    return None


async def intent_node(state: GraphState) -> GraphState:
    info = await detect_intent_with_llm(
        provider=state.provider,
        model=state.model,
        messages=state.messages,
        current_product_model=state.current_product_model,
        product_model_list=list_product_models(),
    )

    # print (f"intent_node: info={info}")

    last_user = ""
    for m in reversed(state.messages):
        if m.role == "user":
            last_user = m.content
            break

    explicit_model_in_text = _resolve_product_model_from_text(last_user)
    matched = info.get("product_model") or explicit_model_in_text
    intent = info.get("intent", "general_chat")
    # 仅当用户这轮文本里明确出现型号/别名，或模型明确判定 set_product_model 时，才进入设置型号分支
    if intent == "set_product_model" or explicit_model_in_text:
        intent = "set_product_model"

    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent=intent,
        matched_product_model=matched,
    )


def set_product_model_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="set_product_model",
        matched_product_model=state.matched_product_model,
    )


def generate_code_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="generate_code",
        matched_product_model=state.matched_product_model,
    )


def general_chat_node(state: GraphState) -> GraphState:
    return GraphState(
        messages=state.messages,
        current_product_model=state.current_product_model,
        provider=state.provider,
        model=state.model,
        intent="general_chat",
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

