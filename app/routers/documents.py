from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from docx import Document as WordDocument
from docx.opc.exceptions import PackageNotFoundError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from lxml.etree import XMLSyntaxError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Document, SharedDocument, User
from app.schemas import (
    DocumentCreate,
    DocumentOut,
    DocumentUpdate,
    ShareCreate,
    ShareOut,
)
from app.services import (
    create_document,
    get_accessible_document,
    get_owned_document,
    list_documents,
    update_document,
)


router = APIRouter(prefix="/api/documents", tags=["documents"])
MAX_UPLOAD_SIZE = 5 * 1024 * 1024
SUPPORTED_UPLOAD_EXTENSIONS = {".txt", ".md", ".docx"}


async def document_response(
    db: AsyncSession,
    document: Document,
    access: str = "owned",
    permission: str = "write",
) -> DocumentOut:
    result = await db.execute(
        select(User.username).where(User.id == document.owner_id)
    )
    return DocumentOut.model_validate(document).model_copy(
        update={
            "access": access,
            "permission": permission,
            "owner_username": result.scalar_one(),
        }
    )


def extract_document_content(filename: str, data: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension == ".docx":
        try:
            word_document = WordDocument(BytesIO(data))
        except (BadZipFile, PackageNotFoundError, KeyError, XMLSyntaxError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded DOCX file is invalid",
            ) from error
        text = "\n".join(paragraph.text for paragraph in word_document.paragraphs)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Text files must use UTF-8 encoding",
            ) from error

    return escape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


@router.get("", response_model=list[DocumentOut])
async def read_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    return await list_documents(db, user.id)


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_document(
    document_data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    document = await create_document(db, document_data, user.id)
    return await document_response(db, document)


@router.post(
    "/import",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a .txt, .md, or .docx file",
        )

    data = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The uploaded file must be 5 MB or smaller",
        )

    content = extract_document_content(filename, data)
    title = Path(filename).stem.strip()[:100] or "Imported document"
    document = await create_document(
        db,
        DocumentCreate(title=title, content=content),
        user.id,
    )
    return await document_response(db, document)


@router.get("/{document_id}", response_model=DocumentOut)
async def read_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    access_result = await get_accessible_document(db, document_id, user.id)
    if access_result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, permission = access_result
    access = "owned" if document.owner_id == user.id else "shared"
    return await document_response(
        db,
        document,
        access=access,
        permission="write" if access == "owned" else permission or "read",
    )


@router.put("/{document_id}", response_model=DocumentOut)
async def save_document(
    document_id: int,
    document_data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentOut:
    access_result = await get_accessible_document(db, document_id, user.id)
    if access_result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, permission = access_result
    access = "owned" if document.owner_id == user.id else "shared"
    if access == "shared" and permission != "write":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have read-only access to this document",
        )
    document = await update_document(db, document, document_data)
    return await document_response(
        db,
        document,
        access=access,
        permission="write" if access == "owned" else permission or "read",
    )


@router.get("/{document_id}/shares", response_model=list[ShareOut])
async def read_shares(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ShareOut]:
    document = await get_owned_document(db, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    result = await db.execute(
        select(SharedDocument, User.username, User.email)
        .join(User, User.id == SharedDocument.shared_with_user_id)
        .where(SharedDocument.document_id == document_id)
        .order_by(User.username)
    )
    return [
        ShareOut(
            id=share.id,
            document_id=share.document_id,
            shared_with_user_id=share.shared_with_user_id,
            username=username,
            email=email,
            permission=share.permission,
            created_at=share.created_at,
        )
        for share, username, email in result.all()
    ]


@router.post(
    "/{document_id}/shares",
    response_model=ShareOut,
    status_code=status.HTTP_201_CREATED,
)
async def grant_document_access(
    document_id: int,
    share_data: ShareCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ShareOut:
    document = await get_owned_document(db, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    recipient_result = await db.execute(
        select(User).where(User.email == share_data.email)
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="User account not found")
    if recipient.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already own this document",
        )

    share_result = await db.execute(
        select(SharedDocument).where(
            SharedDocument.document_id == document_id,
            SharedDocument.shared_with_user_id == recipient.id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        share = SharedDocument(
            document_id=document_id,
            shared_with_user_id=recipient.id,
            permission=share_data.permission,
        )
        db.add(share)
    else:
        share.permission = share_data.permission
    await db.commit()
    await db.refresh(share)
    return ShareOut(
        id=share.id,
        document_id=share.document_id,
        shared_with_user_id=recipient.id,
        username=recipient.username,
        email=recipient.email,
        permission=share.permission,
        created_at=share.created_at,
    )


@router.delete(
    "/{document_id}/shares/{shared_with_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_document_access(
    document_id: int,
    shared_with_user_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    document = await get_owned_document(db, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    result = await db.execute(
        select(SharedDocument).where(
            SharedDocument.document_id == document_id,
            SharedDocument.shared_with_user_id == shared_with_user_id,
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.delete(share)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)