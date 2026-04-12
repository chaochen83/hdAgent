from __future__ import annotations

import json
import os
from typing import Any

from fastapi import HTTPException, UploadFile

from ..core.database import get_db
from ..knowledge.chunking import chunk_text
from ..knowledge.embeddings import EmbeddingUnavailableError, embed_texts, vector_literal
from ..knowledge.ingestion import (
    ParsedKnowledge,
    parse_text_input,
    parse_upload,
    read_stored_upload,
    store_upload_file,
    summarize_parsed_knowledge,
)
from ..knowledge.retrieval import retrieve_chunks_for_query
from ..knowledge.worker import start_background_job


def _normalize_alias(text: str) -> str:
    return "".join(ch.lower() for ch in (text or "") if ch.isalnum())


def _knowledge_tables_ready(conn) -> bool:
    row = conn.execute(
        "SELECT to_regclass('public.board_type') AS board_type, to_regclass('public.knowledge_document_v2') AS knowledge_document_v2"
    ).fetchone()
    return bool(row and row["board_type"] and row["knowledge_document_v2"])


def list_boards(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    with get_db() as conn:
        if not _knowledge_tables_ready(conn):
            return []
        where = "" if include_deleted else "WHERE bt.deleted_at IS NULL"
        rows = conn.execute(
            f"""
            SELECT
              bt.id,
              bt.code,
              bt.name,
              bt.description,
              bt.default_hint,
              bt.is_enabled,
              bt.deleted_at,
              bt.created_at,
              bt.updated_at,
              COALESCE(COUNT(DISTINCT ba.id), 0)::int AS alias_count,
              COALESCE(COUNT(DISTINCT kd.id), 0)::int AS knowledge_count
            FROM board_type bt
            LEFT JOIN board_alias ba ON ba.board_type_id = bt.id
            LEFT JOIN knowledge_document_v2 kd ON kd.board_type_id = bt.id AND kd.deleted_at IS NULL
            {where}
            GROUP BY bt.id
            ORDER BY bt.deleted_at NULLS FIRST, bt.created_at DESC
            """
        ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            board = dict(row)
            aliases = conn.execute(
                "SELECT alias FROM board_alias WHERE board_type_id = %s ORDER BY alias ASC",
                (board["id"],),
            ).fetchall()
            board["aliases"] = [item["alias"] for item in aliases]
            items.append(board)
        return items


def list_active_board_names() -> list[str]:
    with get_db() as conn:
        if not _knowledge_tables_ready(conn):
            return []
        rows = conn.execute(
            "SELECT name FROM board_type WHERE deleted_at IS NULL AND is_enabled = TRUE ORDER BY created_at ASC"
        ).fetchall()
        return [row["name"] for row in rows]


def resolve_board_for_chat(product_model: str | None) -> dict[str, Any] | None:
    if not product_model:
        return None
    normalized = _normalize_alias(product_model)
    if not normalized:
        return None
    with get_db() as conn:
        if not _knowledge_tables_ready(conn):
            return None
        row = conn.execute(
            """
            SELECT bt.id, bt.code, bt.name, bt.default_hint, bt.is_enabled, bt.deleted_at
            FROM board_type bt
            LEFT JOIN board_alias ba ON ba.board_type_id = bt.id
            WHERE bt.deleted_at IS NULL
              AND (
                LOWER(bt.name) = LOWER(%s)
                OR LOWER(bt.code) = LOWER(%s)
                OR ba.normalized_alias = %s
              )
            ORDER BY bt.id ASC
            LIMIT 1
            """,
            (product_model, product_model, normalized),
        ).fetchone()
        return dict(row) if row else None


def create_board(*, created_by_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    aliases = payload.pop("aliases", [])
    with get_db() as conn:
        if not _knowledge_tables_ready(conn):
            raise HTTPException(status_code=500, detail="Knowledge tables are not ready. Please run the migration first.")
        row = conn.execute(
            """
            INSERT INTO board_type (code, name, description, default_hint, is_enabled, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payload["code"].strip(),
                payload["name"].strip(),
                payload.get("description"),
                payload.get("default_hint"),
                payload.get("is_enabled", True),
                created_by_user_id,
                created_by_user_id,
            ),
        ).fetchone()
        board_id = row["id"]
        _replace_board_aliases(conn, board_id=board_id, aliases=aliases)
    return get_board(board_id=board_id)


def update_board(*, board_id: int, updated_by_user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    board = get_board(board_id=board_id, include_deleted=True)
    aliases = payload.pop("aliases", None)
    final = {
        "code": payload.get("code", board["code"]),
        "name": payload.get("name", board["name"]),
        "description": payload.get("description", board.get("description")),
        "default_hint": payload.get("default_hint", board.get("default_hint")),
        "is_enabled": payload.get("is_enabled", board.get("is_enabled", True)),
    }
    with get_db() as conn:
        conn.execute(
            """
            UPDATE board_type
            SET code = %s,
                name = %s,
                description = %s,
                default_hint = %s,
                is_enabled = %s,
                updated_by = %s
            WHERE id = %s
            """,
            (
                final["code"].strip(),
                final["name"].strip(),
                final["description"],
                final["default_hint"],
                final["is_enabled"],
                updated_by_user_id,
                board_id,
            ),
        )
        if aliases is not None:
            _replace_board_aliases(conn, board_id=board_id, aliases=aliases)
    return get_board(board_id=board_id, include_deleted=True)


def soft_delete_board(*, board_id: int, deleted_by_user_id: int) -> dict[str, Any]:
    board = get_board(board_id=board_id, include_deleted=True)
    if board.get("deleted_at"):
        return board
    with get_db() as conn:
        conn.execute(
            """
            UPDATE board_type
            SET deleted_at = NOW(), deleted_by = %s, updated_by = %s
            WHERE id = %s
            """,
            (deleted_by_user_id, deleted_by_user_id, board_id),
        )
    return get_board(board_id=board_id, include_deleted=True)


def get_board(*, board_id: int, include_deleted: bool = False) -> dict[str, Any]:
    with get_db() as conn:
        where = "" if include_deleted else "AND bt.deleted_at IS NULL"
        row = conn.execute(
            f"""
            SELECT bt.id, bt.code, bt.name, bt.description, bt.default_hint, bt.is_enabled,
                   bt.deleted_at, bt.created_at, bt.updated_at
            FROM board_type bt
            WHERE bt.id = %s {where}
            """,
            (board_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Board type not found.")
        board = dict(row)
        aliases = conn.execute("SELECT alias FROM board_alias WHERE board_type_id = %s ORDER BY alias ASC", (board_id,)).fetchall()
        board["aliases"] = [item["alias"] for item in aliases]
        return board


def _replace_board_aliases(conn, *, board_id: int, aliases: list[str]) -> None:
    conn.execute("DELETE FROM board_alias WHERE board_type_id = %s", (board_id,))
    cleaned = []
    for alias in aliases:
        alias = (alias or "").strip()
        normalized = _normalize_alias(alias)
        if alias and normalized:
            cleaned.append((alias, normalized))
    for alias, normalized in cleaned:
        conn.execute(
            "INSERT INTO board_alias (board_type_id, alias, normalized_alias) VALUES (%s, %s, %s) ON CONFLICT (normalized_alias) DO NOTHING",
            (board_id, alias, normalized),
        )


def list_knowledge_documents(
    *,
    board_type_id: int | None = None,
    knowledge_type: str | None = None,
    parse_status: str | None = None,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    with get_db() as conn:
        if not _knowledge_tables_ready(conn):
            return []
        clauses = []
        params: list[Any] = []
        if board_type_id is not None:
            clauses.append("kd.board_type_id = %s")
            params.append(board_type_id)
        if knowledge_type:
            clauses.append("kd.knowledge_type = %s")
            params.append(knowledge_type)
        if parse_status:
            clauses.append("kd.parse_status = %s")
            params.append(parse_status)
        if not include_deleted:
            clauses.append("kd.deleted_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT kd.id::text AS id,
                   kd.board_type_id,
                   bt.name AS board_name,
                   kd.title,
                   kd.knowledge_type,
                   kd.source_type,
                   kd.source_name,
                   kd.file_name,
                   kd.parse_status,
                   kd.parse_error,
                   kd.chunk_count,
                   kd.storage_path,
                   kd.created_at,
                   kd.updated_at,
                   kd.deleted_at
            FROM knowledge_document_v2 kd
            JOIN board_type bt ON bt.id = kd.board_type_id
            {where}
            ORDER BY kd.created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def get_knowledge_document(*, document_id: str, include_deleted: bool = False) -> dict[str, Any]:
    with get_db() as conn:
        where = "" if include_deleted else "AND kd.deleted_at IS NULL"
        row = conn.execute(
            f"""
            SELECT kd.id::text AS id,
                   kd.board_type_id,
                   bt.name AS board_name,
                   kd.title,
                   kd.knowledge_type,
                   kd.source_type,
                   kd.source_name,
                   kd.source_url,
                   kd.raw_text,
                   kd.file_name,
                   kd.file_ext,
                   kd.mime_type,
                   kd.storage_path,
                   kd.file_size,
                   kd.parse_status,
                   kd.parse_error,
                   kd.chunk_count,
                   kd.token_count,
                   kd.metadata,
                   kd.created_at,
                   kd.updated_at,
                   kd.deleted_at
            FROM knowledge_document_v2 kd
            JOIN board_type bt ON bt.id = kd.board_type_id
            WHERE kd.id = %s::uuid {where}
            """,
            (document_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge document not found.")
        return dict(row)


def _queue_document_ingestion(*, document_id: str) -> None:
    start_background_job(lambda: process_knowledge_document_job(document_id))


def create_text_knowledge_document(*, board_type_id: int, title: str, text: str, created_by_user_id: int) -> dict[str, Any]:
    parsed = parse_text_input(title=title, text=text)
    document_id = _create_pending_document(
        board_type_id=board_type_id,
        parsed=parsed,
        created_by_user_id=created_by_user_id,
        source_url=None,
    )
    _queue_document_ingestion(document_id=document_id)
    return get_knowledge_document(document_id=document_id)


def create_website_knowledge_document(
    *, board_type_id: int, title: str, source_url: str, content: str, created_by_user_id: int
) -> dict[str, Any]:
    parsed = ParsedKnowledge(
        title=title.strip(),
        knowledge_type="website",
        source_type="url",
        source_name=source_url.strip(),
        raw_text=(content or "").strip(),
        chunks=[],
        metadata={"source_url": source_url.strip(), "mcp_reserved": True},
    )
    document_id = _create_pending_document(
        board_type_id=board_type_id,
        parsed=parsed,
        created_by_user_id=created_by_user_id,
        source_url=source_url.strip(),
    )
    _queue_document_ingestion(document_id=document_id)
    return get_knowledge_document(document_id=document_id)


async def create_file_knowledge_document(*, board_type_id: int, upload: UploadFile, created_by_user_id: int) -> dict[str, Any]:
    data = await upload.read()
    file_name = upload.filename or "knowledge.txt"
    stored = store_upload_file(file_name=file_name, data=data, mime_type=upload.content_type)
    parsed = ParsedKnowledge(
        title=os.path.splitext(os.path.basename(file_name))[0] or "知识文件",
        knowledge_type=stored["knowledge_type"],
        source_type="file",
        source_name=file_name,
        raw_text="",
        chunks=[],
        metadata={"content_type": "file_upload"},
        file_ext=stored["file_ext"],
        mime_type=stored["mime_type"],
        checksum_sha256=stored["checksum_sha256"],
        file_size=stored["file_size"],
        storage_path=stored["storage_path"],
        file_name=file_name,
    )
    document_id = _create_pending_document(
        board_type_id=board_type_id,
        parsed=parsed,
        created_by_user_id=created_by_user_id,
        source_url=None,
    )
    _queue_document_ingestion(document_id=document_id)
    return get_knowledge_document(document_id=document_id)


def _create_pending_document(
    *, board_type_id: int, parsed: ParsedKnowledge, created_by_user_id: int, source_url: str | None
) -> str:
    board = get_board(board_id=board_type_id)
    if board.get("deleted_at"):
        raise HTTPException(status_code=400, detail="Cannot attach knowledge to a deleted board type.")
    if not board.get("is_enabled"):
        raise HTTPException(status_code=400, detail="Cannot attach knowledge to a disabled board type.")

    initial_status = "uploaded" if parsed.source_type == "file" else "queued"
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO knowledge_document_v2 (
              board_type_id, title, knowledge_type, source_type, source_name, source_url,
              raw_text, file_name, file_ext, mime_type, storage_path, file_size,
              checksum_sha256, parse_status, chunk_count, token_count, metadata,
              created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0, %s::jsonb, %s, %s)
            RETURNING id::text AS id
            """,
            (
                board_type_id,
                parsed.title,
                parsed.knowledge_type,
                parsed.source_type,
                parsed.source_name,
                source_url,
                parsed.raw_text,
                parsed.file_name,
                parsed.file_ext,
                parsed.mime_type,
                parsed.storage_path,
                parsed.file_size,
                parsed.checksum_sha256,
                initial_status,
                json.dumps(parsed.metadata, ensure_ascii=False),
                created_by_user_id,
                created_by_user_id,
            ),
        ).fetchone()
        document_id = row["id"]
        conn.execute(
            """
            INSERT INTO knowledge_job_v2 (knowledge_document_id, board_type_id, job_type, status, payload)
            VALUES (%s::uuid, %s, 'ingest', 'queued', %s::jsonb)
            """,
            (
                document_id,
                board_type_id,
                json.dumps({"source_type": parsed.source_type, "knowledge_type": parsed.knowledge_type}, ensure_ascii=False),
            ),
        )
    return document_id


def process_knowledge_document_job(document_id: str) -> None:
    try:
        document = get_knowledge_document(document_id=document_id, include_deleted=True)
    except HTTPException:
        return

    with get_db() as conn:
        job = conn.execute(
            """
            SELECT id::text AS id
            FROM knowledge_job_v2
            WHERE knowledge_document_id = %s::uuid AND job_type = 'ingest'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        if not job:
            return
        job_id = job["id"]
        conn.execute(
            "UPDATE knowledge_job_v2 SET status = 'running', attempt_count = attempt_count + 1, started_at = NOW() WHERE id = %s::uuid",
            (job_id,),
        )
        conn.execute(
            "UPDATE knowledge_document_v2 SET parse_status = 'queued', parse_error = NULL WHERE id = %s::uuid",
            (document_id,),
        )
    with get_db() as conn:
        conn.execute("UPDATE knowledge_document_v2 SET parse_status = 'parsing' WHERE id = %s::uuid", (document_id,))

    try:
        parsed = _parse_document_record(document)
        summary = summarize_parsed_knowledge(parsed)

        with get_db() as conn:
            conn.execute("DELETE FROM knowledge_chunk_v2 WHERE knowledge_document_id = %s::uuid", (document_id,))
            conn.execute(
                "UPDATE knowledge_document_v2 SET raw_text = %s, parse_status = 'chunking' WHERE id = %s::uuid",
                (parsed.raw_text, document_id),
            )

        embeddings = []
        embedding_enabled = True
        try:
            with get_db() as conn:
                conn.execute("UPDATE knowledge_document_v2 SET parse_status = 'embedding' WHERE id = %s::uuid", (document_id,))
            embeddings = embed_texts([item["content"] for item in parsed.chunks]) if parsed.chunks else []
        except EmbeddingUnavailableError as exc:
            embedding_enabled = False
            embeddings = [None for _ in parsed.chunks]
            with get_db() as conn:
                conn.execute(
                    "UPDATE knowledge_document_v2 SET parse_error = %s WHERE id = %s::uuid",
                    (str(exc), document_id),
                )

        with get_db() as conn:
            for index, chunk in enumerate(parsed.chunks):
                vector = vector_literal(embeddings[index] if index < len(embeddings) else None)
                metadata = json.dumps(chunk["metadata"], ensure_ascii=False)
                if vector:
                    conn.execute(
                        """
                        INSERT INTO knowledge_chunk_v2 (
                          knowledge_document_id, board_type_id, chunk_index, content, metadata, token_count, embedding
                        ) VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s, %s::vector)
                        """,
                        (document_id, document["board_type_id"], index, chunk["content"], metadata, chunk["token_count"], vector),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO knowledge_chunk_v2 (
                          knowledge_document_id, board_type_id, chunk_index, content, metadata, token_count
                        ) VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (document_id, document["board_type_id"], index, chunk["content"], metadata, chunk["token_count"]),
                    )
            conn.execute(
                """
                UPDATE knowledge_document_v2
                SET parse_status = 'completed',
                    chunk_count = %s,
                    token_count = %s,
                    metadata = metadata || %s::jsonb
                WHERE id = %s::uuid
                """,
                (
                    len(parsed.chunks),
                    summary["token_count"],
                    json.dumps({"embedding_enabled": embedding_enabled} | (parsed.metadata or {}), ensure_ascii=False),
                    document_id,
                ),
            )
            conn.execute(
                """
                UPDATE knowledge_job_v2
                SET status = 'succeeded', result = %s::jsonb, finished_at = NOW(), error_message = NULL
                WHERE id = %s::uuid
                """,
                (
                    json.dumps(
                        {
                            "chunk_count": len(parsed.chunks),
                            "token_count": summary["token_count"],
                            "embedding_enabled": embedding_enabled,
                        },
                        ensure_ascii=False,
                    ),
                    job_id,
                ),
            )
    except Exception as exc:
        with get_db() as conn:
            _mark_document_failed(conn, document_id=document_id, job_id=job_id, error=str(exc))


def list_knowledge_jobs(*, document_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, knowledge_document_id::text AS knowledge_document_id,
                   job_type, status, attempt_count, payload, result, error_message,
                   started_at, finished_at, created_at, updated_at
            FROM knowledge_job_v2
            WHERE knowledge_document_id = %s::uuid
            ORDER BY created_at DESC
            """,
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_knowledge_chunks(*, document_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT id, chunk_index, content, metadata, token_count, created_at
            FROM knowledge_chunk_v2
            WHERE knowledge_document_id = %s::uuid
            ORDER BY chunk_index ASC
            LIMIT {int(limit)}
            """,
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def retry_knowledge_document(*, document_id: str, requested_by_user_id: int) -> dict[str, Any]:
    document = get_knowledge_document(document_id=document_id, include_deleted=True)
    if document.get("deleted_at"):
        raise HTTPException(status_code=400, detail="Deleted knowledge document cannot be retried.")
    if document.get("parse_status") not in {"failed", "completed"}:
        raise HTTPException(status_code=400, detail="Only failed or completed knowledge documents can be retried.")

    with get_db() as conn:
        conn.execute("DELETE FROM knowledge_chunk_v2 WHERE knowledge_document_id = %s::uuid", (document_id,))
        conn.execute(
            """
            UPDATE knowledge_document_v2
            SET parse_status = 'queued',
                parse_error = NULL,
                chunk_count = 0,
                token_count = 0,
                updated_by = %s
            WHERE id = %s::uuid
            """,
            (requested_by_user_id, document_id),
        )
        conn.execute(
            """
            INSERT INTO knowledge_job_v2 (knowledge_document_id, board_type_id, job_type, status, payload)
            VALUES (%s::uuid, %s, 'ingest', 'queued', %s::jsonb)
            """,
            (
                document_id,
                document["board_type_id"],
                json.dumps({"retry": True, "requested_by_user_id": requested_by_user_id}, ensure_ascii=False),
            ),
        )
    _queue_document_ingestion(document_id=document_id)
    return get_knowledge_document(document_id=document_id)


def _parse_document_record(document: dict[str, Any]) -> ParsedKnowledge:
    knowledge_type = document.get("knowledge_type")
    source_type = document.get("source_type")
    title = document.get("title") or "知识条目"

    if source_type == "file":
        data = read_stored_upload(document["storage_path"])
        return parse_upload(file_name=document.get("file_name") or document.get("source_name") or title, data=data, mime_type=document.get("mime_type"))

    if knowledge_type == "text":
        return parse_text_input(title=title, text=document.get("raw_text") or "")

    if knowledge_type == "website":
        source_url = document.get("source_url") or document.get("source_name") or ""
        parsed = ParsedKnowledge(
            title=title,
            knowledge_type="website",
            source_type="url",
            source_name=document.get("source_name") or source_url,
            raw_text=(document.get("raw_text") or "").strip(),
            chunks=[],
            metadata={"source_url": source_url, "mcp_reserved": True},
        )
        parsed.chunks = [
            {
                "content": chunk["content"],
                "token_count": chunk["token_count"],
                "metadata": {**chunk["metadata"], "source_url": source_url},
            }
            for chunk in chunk_text(
                parsed.raw_text,
                chunk_size=1200,
                chunk_overlap=180,
                prefix=f"Source URL: {source_url}",
                base_metadata={"content_type": "website"},
            )
        ]
        return parsed

    raise ValueError(f"Unsupported knowledge document type: {knowledge_type}/{source_type}")


def _mark_document_failed(conn, *, document_id: str, job_id: str, error: str) -> None:
    conn.execute(
        "UPDATE knowledge_document_v2 SET parse_status = 'failed', parse_error = %s WHERE id = %s::uuid",
        (error, document_id),
    )
    conn.execute(
        "UPDATE knowledge_job_v2 SET status = 'failed', error_message = %s, finished_at = NOW() WHERE id = %s::uuid",
        (error, job_id),
    )


def soft_delete_knowledge_document(*, document_id: str, deleted_by_user_id: int) -> dict[str, Any]:
    get_knowledge_document(document_id=document_id, include_deleted=True)
    with get_db() as conn:
        conn.execute(
            """
            UPDATE knowledge_document_v2
            SET deleted_at = NOW(), deleted_by = %s, updated_by = %s
            WHERE id = %s::uuid AND deleted_at IS NULL
            """,
            (deleted_by_user_id, deleted_by_user_id, document_id),
        )
    return get_knowledge_document(document_id=document_id, include_deleted=True)


def get_document_download_path(*, document_id: str) -> tuple[str, str]:
    doc = get_knowledge_document(document_id=document_id)
    if doc.get("knowledge_type") not in {"txt", "excel"} or not doc.get("storage_path"):
        raise HTTPException(status_code=404, detail="Source download is only available for uploaded txt/excel files.")
    path = doc["storage_path"]
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Source file not found on disk.")
    return path, doc.get("file_name") or os.path.basename(path)


async def retrieve_board_knowledge(*, board_type_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    return await retrieve_chunks_for_query(board_type_id=board_type_id, query=query, limit=top_k)


def get_knowledge_chunk_detail(*, chunk_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
              kc.id,
              kc.chunk_index,
              kc.content,
              kc.metadata,
              kc.token_count,
              kc.created_at,
              kd.id::text AS knowledge_document_id,
              kd.title,
              kd.knowledge_type,
              kd.source_type,
              kd.source_name,
              kd.source_url,
              kd.file_name,
              kd.parse_status,
              bt.id AS board_type_id,
              bt.name AS board_name,
              bt.code AS board_code
            FROM knowledge_chunk_v2 kc
            JOIN knowledge_document_v2 kd ON kd.id = kc.knowledge_document_id
            JOIN board_type bt ON bt.id = kc.board_type_id
            WHERE kc.id = %s
              AND kd.deleted_at IS NULL
              AND bt.deleted_at IS NULL
            """,
            (chunk_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge chunk not found.")
        return dict(row)
