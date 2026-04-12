from __future__ import annotations

import re
from typing import Any


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 180


def estimate_token_count(text: str) -> int:
    normalized = (text or "").strip()
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


def _normalize_whitespace(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _split_paragraphs(text: str) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    return parts or [normalized]


def _trim_with_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text
    return text[-overlap:]


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    prefix: str = "",
    base_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    prefix = prefix.strip()
    prefix_block = f"{prefix}\n\n" if prefix else ""
    chunks: list[dict[str, Any]] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        content = buffer.strip()
        if not content:
            buffer = ""
            return
        chunk_body = f"{prefix_block}{content}".strip()
        meta = dict(base_metadata or {})
        meta.setdefault("content_length", len(chunk_body))
        chunks.append(
            {
                "content": chunk_body,
                "token_count": estimate_token_count(chunk_body),
                "metadata": meta,
            }
        )
        buffer = _trim_with_overlap(content, chunk_overlap)

    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        if buffer:
            flush()
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= chunk_size:
                buffer = candidate
                continue

        # 超长段落按句子和字符双重兜底切分。
        sentences = re.split(r"(?<=[。！？!?\.])\s+", paragraph)
        local = buffer
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            maybe = f"{local}\n{sentence}".strip() if local else sentence
            if len(maybe) <= chunk_size:
                local = maybe
                continue
            if local:
                buffer = local
                flush()
                local = ""
            while len(sentence) > chunk_size:
                buffer = sentence[:chunk_size]
                flush()
                sentence = sentence[max(chunk_size - chunk_overlap, 1) :]
            local = sentence
        buffer = local

    if buffer:
        flush()

    return chunks


def chunk_sheet_rows(sheet_name: str, rows: list[list[str]], *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[dict[str, Any]]:
    rendered_rows = []
    for row in rows:
        cleaned = [cell.strip() for cell in row if cell and cell.strip()]
        if cleaned:
            rendered_rows.append(" | ".join(cleaned))
    text = "\n".join(rendered_rows)
    if not text:
        return []
    return chunk_text(
        text,
        chunk_size=chunk_size,
        chunk_overlap=120,
        prefix=f"Sheet: {sheet_name}",
        base_metadata={"sheet_name": sheet_name, "content_type": "table"},
    )
