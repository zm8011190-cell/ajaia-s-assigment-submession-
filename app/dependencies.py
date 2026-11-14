from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_session_token
from app.db import get_db
from app.models import User, UserSession


async def get_current_user(
    doc_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if doc_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue",
        )

    result = await db.execute(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(doc_session),
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please log in again",
        )
    return user