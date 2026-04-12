from __future__ import annotations

from typing import Any

import httpx

from ..core.config import settings


class EmbeddingUnavailableError(RuntimeError):
    pass


def is_embedding_enabled() -> bool:
    return bool(settings.embedding_api_key and settings.embedding_base_url and settings.embedding_model)


def _embedding_url() -> str:
    return f"{settings.embedding_base_url.rstrip('/')}/embeddings"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.embedding_api_key}",
        "Content-Type": "application/json",
    }


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    if not texts:
        return []
    if not is_embedding_enabled():
        return [None for _ in texts]

    payload: dict[str, Any] = {
        "model": settings.embedding_model,
        "input": texts,
    }
    try:
        with httpx.Client(timeout=settings.embedding_timeout_seconds) as client:
            response = client.post(_embedding_url(), json=payload, headers=_headers())
            response.raise_for_status()
    except Exception as exc:
        raise EmbeddingUnavailableError(str(exc)) from exc

    body = response.json()
    items = body.get("data") or []
    if not isinstance(items, list) or len(items) != len(texts):
        raise EmbeddingUnavailableError("Embedding API returned unexpected payload.")

    return [item.get("embedding") for item in items]


async def embed_query(text: str) -> list[float] | None:
    results = embed_texts([text])
    return results[0] if results else None


def vector_literal(values: list[float] | None) -> str | None:
    if not values:
        return None
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"
