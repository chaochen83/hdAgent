from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from ..schemas.knowledge import (
    BoardUpdateRequest,
    BoardUpsertRequest,
    KnowledgeRetrieveRequest,
    KnowledgeTextCreateRequest,
    KnowledgeWebsiteCreateRequest,
)
from ..services.auth_service import require_admin
from ..services.knowledge_service import (
    create_board,
    create_text_knowledge_document,
    create_website_knowledge_document,
    create_file_knowledge_document,
    get_board,
    get_document_download_path,
    get_knowledge_document,
    list_knowledge_chunks,
    list_knowledge_jobs,
    list_boards,
    list_knowledge_documents,
    retry_knowledge_document,
    retrieve_board_knowledge,
    soft_delete_board,
    soft_delete_knowledge_document,
    update_board,
)

router = APIRouter(prefix="/api/admin", tags=["knowledge"])


@router.get("/boards")
def boards(request: Request, include_deleted: bool = False) -> dict:
    require_admin(request)
    return {"items": list_boards(include_deleted=include_deleted)}


@router.get("/boards/{board_id}")
def board_detail(board_id: int, request: Request, include_deleted: bool = False) -> dict:
    require_admin(request)
    return {"board": get_board(board_id=board_id, include_deleted=include_deleted)}


@router.post("/boards")
def create_board_route(payload: BoardUpsertRequest, request: Request) -> dict:
    admin = require_admin(request)
    return {"board": create_board(created_by_user_id=admin["id"], payload=payload.model_dump())}


@router.patch("/boards/{board_id}")
def update_board_route(board_id: int, payload: BoardUpdateRequest, request: Request) -> dict:
    admin = require_admin(request)
    return {"board": update_board(board_id=board_id, updated_by_user_id=admin["id"], payload=payload.model_dump(exclude_unset=True))}


@router.delete("/boards/{board_id}")
def delete_board_route(board_id: int, request: Request) -> dict:
    admin = require_admin(request)
    return {"board": soft_delete_board(board_id=board_id, deleted_by_user_id=admin["id"])}


@router.get("/knowledge/documents")
def knowledge_documents(
    request: Request,
    board_type_id: int | None = None,
    knowledge_type: str | None = None,
    parse_status: str | None = None,
    include_deleted: bool = False,
) -> dict:
    require_admin(request)
    return {
        "items": list_knowledge_documents(
            board_type_id=board_type_id,
            knowledge_type=knowledge_type,
            parse_status=parse_status,
            include_deleted=include_deleted,
        )
    }


@router.get("/knowledge/documents/{document_id}")
def knowledge_document_detail(document_id: str, request: Request, include_deleted: bool = False) -> dict:
    require_admin(request)
    return {"document": get_knowledge_document(document_id=document_id, include_deleted=include_deleted)}


@router.get("/knowledge/documents/{document_id}/jobs")
def knowledge_document_jobs(document_id: str, request: Request) -> dict:
    require_admin(request)
    return {"items": list_knowledge_jobs(document_id=document_id)}


@router.get("/knowledge/documents/{document_id}/chunks")
def knowledge_document_chunks(document_id: str, request: Request, limit: int = 20) -> dict:
    require_admin(request)
    return {"items": list_knowledge_chunks(document_id=document_id, limit=limit)}


@router.post("/knowledge/documents/text")
def create_text_document(payload: KnowledgeTextCreateRequest, request: Request) -> dict:
    admin = require_admin(request)
    return {
        "document": create_text_knowledge_document(
            board_type_id=payload.board_type_id,
            title=payload.title,
            text=payload.text,
            created_by_user_id=admin["id"],
        )
    }


@router.post("/knowledge/documents/website")
def create_website_document(payload: KnowledgeWebsiteCreateRequest, request: Request) -> dict:
    admin = require_admin(request)
    return {
        "document": create_website_knowledge_document(
            board_type_id=payload.board_type_id,
            title=payload.title,
            source_url=payload.source_url,
            content=payload.content,
            created_by_user_id=admin["id"],
        )
    }


@router.post("/knowledge/documents/file")
async def create_file_document(
    request: Request,
    board_type_id: int = Form(...),
    file: UploadFile = File(...),
) -> dict:
    admin = require_admin(request)
    return {
        "document": await create_file_knowledge_document(
            board_type_id=board_type_id,
            upload=file,
            created_by_user_id=admin["id"],
        )
    }


@router.delete("/knowledge/documents/{document_id}")
def delete_document(document_id: str, request: Request) -> dict:
    admin = require_admin(request)
    return {"document": soft_delete_knowledge_document(document_id=document_id, deleted_by_user_id=admin["id"])}


@router.post("/knowledge/documents/{document_id}/retry")
def retry_document(document_id: str, request: Request) -> dict:
    admin = require_admin(request)
    return {"document": retry_knowledge_document(document_id=document_id, requested_by_user_id=admin["id"])}


@router.get("/knowledge/documents/{document_id}/download")
def download_document(document_id: str, request: Request) -> FileResponse:
    require_admin(request)
    path, filename = get_document_download_path(document_id=document_id)
    return FileResponse(path, filename=filename)


@router.post("/knowledge/retrieve")
async def retrieve_knowledge(payload: KnowledgeRetrieveRequest, request: Request) -> dict:
    require_admin(request)
    rows = await retrieve_board_knowledge(board_type_id=payload.board_type_id, query=payload.query, top_k=payload.top_k)
    return {"items": rows}
