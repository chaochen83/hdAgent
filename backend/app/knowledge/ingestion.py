from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..core.config import settings
from .chunking import chunk_sheet_rows, chunk_text, estimate_token_count


@dataclass
class ParsedKnowledge:
    title: str
    knowledge_type: str
    source_type: str
    source_name: str
    raw_text: str
    chunks: list[dict[str, Any]]
    metadata: dict[str, Any]
    file_ext: str | None = None
    mime_type: str | None = None
    checksum_sha256: str | None = None
    file_size: int | None = None
    storage_path: str | None = None
    file_name: str | None = None


_STORAGE_DIR = Path(settings.knowledge_storage_dir).expanduser()


def _ensure_storage_dir() -> Path:
    _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _STORAGE_DIR


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _render_workbook(data: bytes) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    workbook = load_workbook(filename=BytesIO(data), data_only=True, read_only=True)
    all_texts: list[str] = []
    all_chunks: list[dict[str, Any]] = []
    sheet_names: list[str] = []
    for sheet_name in workbook.sheetnames:
        ws = workbook[sheet_name]
        sheet_names.append(sheet_name)
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                rows.append(values)
        if not rows:
            continue
        rendered_lines = [" | ".join([cell.strip() for cell in row if cell and cell.strip()]) for row in rows]
        all_texts.append(f"Sheet: {sheet_name}\n" + "\n".join(rendered_lines))
        all_chunks.extend(chunk_sheet_rows(sheet_name, rows, chunk_size=settings.knowledge_chunk_size))
    return "\n\n".join(all_texts).strip(), all_chunks, {"sheet_names": sheet_names}


def detect_knowledge_type_from_file_name(file_name: str) -> str:
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext == ".txt":
        return "txt"
    if ext in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return "excel"
    raise ValueError("Only .txt and .xlsx files are supported for knowledge ingestion right now.")


def store_upload_file(*, file_name: str, data: bytes, mime_type: str | None = None) -> dict[str, Any]:
    ext = os.path.splitext(file_name or "")[1].lower()
    knowledge_type = detect_knowledge_type_from_file_name(file_name)
    checksum = _sha256(data)
    storage_dir = _ensure_storage_dir()
    storage_path = storage_dir / f"{checksum}{ext}"
    storage_path.write_bytes(data)
    return {
        "knowledge_type": knowledge_type,
        "file_ext": ext.lstrip("."),
        "mime_type": mime_type,
        "checksum_sha256": checksum,
        "file_size": len(data),
        "storage_path": str(storage_path),
    }


def read_stored_upload(storage_path: str) -> bytes:
    path = Path(storage_path)
    if not path.is_file():
        raise FileNotFoundError(f"Stored upload not found: {storage_path}")
    return path.read_bytes()


def parse_text_input(*, title: str, text: str) -> ParsedKnowledge:
    raw_text = (text or "").strip()
    chunks = chunk_text(
        raw_text,
        chunk_size=settings.knowledge_chunk_size,
        chunk_overlap=settings.knowledge_chunk_overlap,
    )
    return ParsedKnowledge(
        title=title.strip() or "未命名文本知识",
        knowledge_type="text",
        source_type="text",
        source_name=title.strip() or "text",
        raw_text=raw_text,
        chunks=chunks,
        metadata={"input_method": "text"},
    )


def parse_upload(*, file_name: str, data: bytes, mime_type: str | None = None) -> ParsedKnowledge:
    ext = os.path.splitext(file_name or "")[1].lower()

    if ext == ".txt":
        raw_text = _decode_text(data).strip()
        chunks = chunk_text(
            raw_text,
            chunk_size=settings.knowledge_chunk_size,
            chunk_overlap=settings.knowledge_chunk_overlap,
        )
        knowledge_type = "txt"
        metadata = {"content_type": "text"}
    elif ext in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        raw_text, chunks, metadata = _render_workbook(data)
        knowledge_type = "excel"
    else:
        raise ValueError("Only .txt and .xlsx files are supported for knowledge ingestion right now.")

    stored = store_upload_file(file_name=file_name, data=data, mime_type=mime_type)
    title = os.path.splitext(os.path.basename(file_name or "知识文件"))[0] or "知识文件"
    return ParsedKnowledge(
        title=title,
        knowledge_type=knowledge_type,
        source_type="file",
        source_name=file_name,
        raw_text=raw_text,
        chunks=chunks,
        metadata=metadata,
        file_ext=stored["file_ext"],
        mime_type=stored["mime_type"],
        checksum_sha256=stored["checksum_sha256"],
        file_size=stored["file_size"],
        storage_path=stored["storage_path"],
        file_name=file_name,
    )


def summarize_parsed_knowledge(parsed: ParsedKnowledge) -> dict[str, Any]:
    return {
        "chunk_count": len(parsed.chunks),
        "token_count": estimate_token_count(parsed.raw_text),
        "metadata": parsed.metadata,
    }
