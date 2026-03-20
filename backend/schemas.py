from typing import Literal, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    product_model: Optional[str] = None
    provider: Literal["qwen", "openai", "claude", "deepseek"] = "deepseek"
    model: Optional[str] = None


class ChatState(BaseModel):
    messages: list[ChatMessage]
    product_model: Optional[str] = None
    provider: str
    model: Optional[str] = None


class GraphState(BaseModel):
    messages: list[ChatMessage]

