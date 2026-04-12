from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..services.auth_service import require_user
from ..services.knowledge_service import get_knowledge_chunk_detail

router = APIRouter(tags=["knowledge-public"])


@router.get("/api/knowledge/chunks/{chunk_id}")
def knowledge_chunk_json(chunk_id: int, request: Request) -> dict:
    require_user(request)
    return {"chunk": get_knowledge_chunk_detail(chunk_id=chunk_id)}


@router.get("/knowledge/chunks/{chunk_id}", response_class=HTMLResponse)
def knowledge_chunk_page(chunk_id: int, request: Request) -> HTMLResponse:
    require_user(request)
    chunk = get_knowledge_chunk_detail(chunk_id=chunk_id)
    metadata_html = escape(str(chunk.get("metadata") or {}))
    source_url = chunk.get("source_url")
    source_link = (
        f'<a href="{escape(source_url)}" target="_blank" rel="noreferrer">{escape(source_url)}</a>' if source_url else "-"
    )
    html = f"""
    <!doctype html>
    <html lang=\"zh-CN\">
      <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>{escape(chunk.get('title') or 'Knowledge Chunk')}</title>
        <style>
          :root {{
            color-scheme: dark;
            --bg: #171717;
            --panel: #242424;
            --border: rgba(255,255,255,.1);
            --text: #ececec;
            --muted: #a9a9a9;
            --accent: #10a37f;
          }}
          * {{ box-sizing: border-box; }}
          body {{ margin: 0; font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; background: linear-gradient(180deg, #202123 0%, #171717 100%); color: var(--text); }}
          .wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }}
          .card {{ border: 1px solid var(--border); background: var(--panel); border-radius: 24px; padding: 22px; box-shadow: 0 20px 44px rgba(0,0,0,.22); }}
          .meta {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin: 18px 0 22px; }}
          .meta-item {{ border: 1px solid var(--border); background: rgba(255,255,255,.03); border-radius: 16px; padding: 12px 14px; }}
          .label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em; }}
          pre {{ white-space: pre-wrap; word-break: break-word; border-radius: 18px; padding: 18px; background: rgba(0,0,0,.28); border: 1px solid var(--border); overflow: auto; }}
          a {{ color: #7dd3fc; text-decoration: none; }}
          .muted {{ color: var(--muted); }}
          .badge {{ display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; background: rgba(16,163,127,.12); border: 1px solid rgba(16,163,127,.26); color: #bbf7d0; font-size: 12px; }}
          @media (max-width: 720px) {{ .meta {{ grid-template-columns: 1fr; }} }}
        </style>
      </head>
      <body>
        <main class=\"wrap\">
          <section class=\"card\">
            <div class=\"badge\">Chunk #{chunk['id']}</div>
            <h1>{escape(chunk.get('title') or 'Untitled')}</h1>
            <p class=\"muted\">板型知识库片段详情页。这个链接可以直接从聊天记录中的参考资料打开。</p>
            <div class=\"meta\">
              <div class=\"meta-item\"><span class=\"label\">板型</span>{escape(chunk.get('board_name') or '-')}</div>
              <div class=\"meta-item\"><span class=\"label\">知识类型</span>{escape(chunk.get('knowledge_type') or '-')}</div>
              <div class=\"meta-item\"><span class=\"label\">来源</span>{escape(chunk.get('source_name') or '-')}</div>
              <div class=\"meta-item\"><span class=\"label\">源链接</span>{source_link}</div>
              <div class=\"meta-item\"><span class=\"label\">Chunk 序号</span>{chunk.get('chunk_index', 0)}</div>
              <div class=\"meta-item\"><span class=\"label\">Token 估算</span>{chunk.get('token_count', 0)}</div>
            </div>
            <h2>内容</h2>
            <pre>{escape(chunk.get('content') or '')}</pre>
            <h2>Metadata</h2>
            <pre>{metadata_html}</pre>
          </section>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html)
