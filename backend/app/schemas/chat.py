from typing import Literal

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    title: str | None = None
    provider: Literal["qwen", "openai", "claude", "deepseek"] = "openai"
    model: str | None = None
    current_product_model: str | None = None


class SessionStreamRequest(BaseModel):
    message: str
    provider: Literal["qwen", "openai", "claude", "deepseek"] = "openai"
    model: str | None = None
    current_product_model: str | None = None

