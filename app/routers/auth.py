from datetime import datetime, timedelta, timezone
import os
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, hash_session_token, verify_password
from app.db import get_db
from app.dependencies import get_current_user
from app.models import User, UserSession
from app.schemas import UserCreate, UserLogin, UserOut


router = APIRouter(prefix="/api/auth", tags=["authentication"])
SESSION_COOKIE = "doc_session"
SESSION_DURATION = timedelta(days=30)
COOKIE_SECURE = os.environ.get("DOCSAPP_COOKIE_SECURE", "false").lower() in {
    "1",
    "true",
    "yes",
}


async def start_session(
    response: Response,
    db: AsyncSession,
    user: User,
) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_DURATION
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )
    )
    await db.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    user_data: UserCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(
        select(User).where(
            or_(
                User.email == user_data.email,
                User.username == user_data.username,
            )
        )
    )
    existing_user = result.scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email or username is already registered",
        )

    user = User(
        username=user_data.username,
        email=user_data.email,
        password=hash_password(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await start_session(response, db, user)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    user_data: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.email == user_data.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(user_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    await start_session(response, db, user)
    return user


@router.get("/me", response_model=UserOut)
async def read_current_user(
    user: User = Depends(get_current_user),
) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    doc_session: str | None = Cookie(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.token_hash == hash_session_token(doc_session or ""),
        )
    )
    session = result.scalar_one_or_none()
    if session is not None:
        await db.delete(session)
        await db.commit()
    response.delete_cookie(key=SESSION_COOKIE, path="/", samesite="lax")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
