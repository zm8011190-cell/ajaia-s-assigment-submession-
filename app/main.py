from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import inspect, text

from app import models
from app.db import Base, engine
from app.routers.auth import router as auth_router
from app.routers.documents import router as documents_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        share_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("shared_documents")
            }
        )
        if "permission" not in share_columns:
            await connection.execute(
                text(
                    "ALTER TABLE shared_documents "
                    "ADD COLUMN permission VARCHAR(10) NOT NULL DEFAULT 'read'"
                )
            )

    yield


app = FastAPI(title="Documents Mockup", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(documents_router)


@app.get("/health", include_in_schema=False)
async def health_check() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.exec_driver_sql("SELECT 1")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def document_editor() -> FileResponse:
    editor_path = Path(__file__).parent / "templates" / "editor.html"
    return FileResponse(editor_path, media_type="text/html")