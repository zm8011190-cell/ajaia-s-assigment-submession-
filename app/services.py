from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, SharedDocument, User
from app.schemas import DocumentCreate, DocumentUpdate


async def list_documents(db: AsyncSession, user_id: int) -> list[dict]:
    result = await db.execute(
        select(Document, User.username, SharedDocument.permission)
        .join(User, User.id == Document.owner_id)
        .outerjoin(
            SharedDocument,
            and_(
                SharedDocument.document_id == Document.id,
                SharedDocument.shared_with_user_id == user_id,
            ),
        )
        .where(
            or_(
                Document.owner_id == user_id,
                SharedDocument.shared_with_user_id == user_id,
            )
        )
        .order_by(Document.updated_at.desc(), Document.id.desc())
    )
    return [
        {
            "id": document.id,
            "title": document.title,
            "content": document.content,
            "owner_id": document.owner_id,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "access": "owned" if document.owner_id == user_id else "shared",
            "permission": (
                "write" if document.owner_id == user_id else permission
            ),
            "owner_username": owner_username,
        }
        for document, owner_username, permission in result.all()
    ]


async def get_owned_document(
    db: AsyncSession, document_id: int, owner_id: int
) -> Document | None:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == owner_id,
        )
    )
    return result.scalar_one_or_none()


async def get_accessible_document(
    db: AsyncSession, document_id: int, user_id: int
) -> tuple[Document, str | None] | None:
    result = await db.execute(
        select(Document, SharedDocument.permission)
        .outerjoin(
            SharedDocument,
            and_(
                SharedDocument.document_id == Document.id,
                SharedDocument.shared_with_user_id == user_id,
            ),
        )
        .where(
            Document.id == document_id,
            or_(
                Document.owner_id == user_id,
                SharedDocument.shared_with_user_id == user_id,
            ),
        )
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def create_document(
    db: AsyncSession, document_data: DocumentCreate, owner_id: int
) -> Document:
    document = Document(
        title=document_data.title,
        content=document_data.content,
        owner_id=owner_id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def update_document(
    db: AsyncSession, document: Document, document_data: DocumentUpdate
) -> Document:
    changes = document_data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(document, field, value)
    await db.commit()
    await db.refresh(document)
    return document