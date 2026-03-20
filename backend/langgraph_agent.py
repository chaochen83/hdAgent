from langgraph.graph import END, StateGraph

from .schemas import GraphState


def echo_node(state: GraphState) -> GraphState:
    # 示例节点：目前只是原样返回，后续可以扩展工具调用、记忆等
    return state


graph_builder = StateGraph(GraphState)
graph_builder.add_node("echo", echo_node)
graph_builder.set_entry_point("echo")
graph_builder.add_edge("echo", END)

# 当前图仅用于占位/演示结构；真正的 LLM 调用在 FastAPI 层实现流式输出
chat_graph = graph_builder.compile()

