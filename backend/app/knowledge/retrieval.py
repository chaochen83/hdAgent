from __future__ import annotations

from typing import Any

from ..core.database import get_db
from .embeddings import embed_query, vector_literal


def _vector_query_sql(limit: int) -> str:
    return f"""
        SELECT
          kc.id,
          kc.knowledge_document_id::text AS knowledge_document_id,
          kc.content,
          kc.metadata,
          kd.title,
          kd.knowledge_type,
          kd.source_name,
          (kc.embedding <=> %s::vector) AS score,
          'vector' AS retrieval_mode
        FROM knowledge_chunk_v2 kc
        JOIN knowledge_document_v2 kd ON kd.id = kc.knowledge_document_id
        JOIN board_type bt ON bt.id = kc.board_type_id
        WHERE kc.board_type_id = %s
          AND kd.deleted_at IS NULL
          AND kd.parse_status = 'completed'
          AND bt.deleted_at IS NULL
          AND bt.is_enabled = TRUE
          AND kc.embedding IS NOT NULL
        ORDER BY kc.embedding <=> %s::vector
        LIMIT {int(limit)}
    """


async def retrieve_chunks_for_query(*, board_type_id: int, query: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        embedding = await embed_query(query)
        rows: list[dict[str, Any]] = []
        with get_db() as conn:
            if embedding:
                literal = vector_literal(embedding)
                rows = [
                    dict(row)
                    for row in conn.execute(_vector_query_sql(limit), (literal, board_type_id, literal)).fetchall()
                ]
            if rows:
                return rows

            lexical_rows = conn.execute(
                f"""
                SELECT
                  kc.id,
                  kc.knowledge_document_id::text AS knowledge_document_id,
                  kc.content,
                  kc.metadata,
                  kd.title,
                  kd.knowledge_type,
                  kd.source_name,
                  ts_rank_cd(kc.content_tsv, websearch_to_tsquery('simple', %s)) AS score,
                  'lexical' AS retrieval_mode
                FROM knowledge_chunk_v2 kc
                JOIN knowledge_document_v2 kd ON kd.id = kc.knowledge_document_id
                JOIN board_type bt ON bt.id = kc.board_type_id
                WHERE kc.board_type_id = %s
                  AND kd.deleted_at IS NULL
                  AND kd.parse_status = 'completed'
                  AND bt.deleted_at IS NULL
                  AND bt.is_enabled = TRUE
                  AND kc.content_tsv @@ websearch_to_tsquery('simple', %s)
                ORDER BY score DESC, kc.id ASC
                LIMIT {int(limit)}
                """,
                (query, board_type_id, query),
            ).fetchall()
            return [dict(row) for row in lexical_rows]
    except Exception:
        return []


async def build_rag_context(*, board_type_id: int, query: str, limit: int = 5) -> tuple[str, list[dict[str, Any]]]:
    rows = await retrieve_chunks_for_query(board_type_id=board_type_id, query=query, limit=limit)
    if not rows:
        return "", []
    blocks = []
    for index, row in enumerate(rows, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[Knowledge {index}]",
                    f"Title: {row.get('title') or 'Untitled'}",
                    f"Type: {row.get('knowledge_type') or 'unknown'}",
                    row.get("content") or "",
                ]
            ).strip()
        )
    return "\n\n".join(blocks), rows
