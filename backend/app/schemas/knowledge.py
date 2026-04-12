from typing import Literal

from pydantic import BaseModel, Field


KnowledgeType = Literal["txt", "excel", "text", "website"]


class BoardUpsertRequest(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    default_hint: str | None = None
    aliases: list[str] = Field(default_factory=list)
    is_enabled: bool = True


class BoardUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=80)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    default_hint: str | None = None
    aliases: list[str] | None = None
    is_enabled: bool | None = None


class KnowledgeTextCreateRequest(BaseModel):
    board_type_id: int
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class KnowledgeWebsiteCreateRequest(BaseModel):
    board_type_id: int
    title: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=4)
    content: str = Field(min_length=1, description="Pre-cleaned website content for the current phase.")


class KnowledgeRetrieveRequest(BaseModel):
    board_type_id: int
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
