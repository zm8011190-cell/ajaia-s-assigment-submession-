import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

default_database_path = Path(__file__).resolve().parent.parent / "docsapp.db"
database_path = Path(
    os.environ.get("DOCSAPP_DATABASE_PATH", default_database_path)
).expanduser().resolve()
database_path.parent.mkdir(parents=True, exist_ok=True)
db_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
engine = create_async_engine(db_url)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session