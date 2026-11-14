import asyncio
from io import BytesIO

import pytest
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import auth, db
from app import main as main_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "PASSWORD_ITERATIONS", 1_000)
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'documents.db'}"
    )
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=db.AsyncSessionLocal.class_,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(main_module, "engine", test_engine)

    try:
        with TestClient(main_module.app) as test_client:
            response = test_client.post(
                "/api/auth/register",
                json={
                    "username": "alice",
                    "email": "alice@example.test",
                    "password": "alice-password",
                },
            )
            assert response.status_code == 201
            yield test_client
    finally:
        asyncio.run(test_engine.dispose())


def test_create_edit_save_and_reopen_document(client):
    editor = client.get("/")
    assert editor.status_code == 200
    assert 'id="register-form"' in editor.text
    assert 'id="login-form"' in editor.text
    assert 'id="share-form"' in editor.text
    assert 'id="toast"' in editor.text
    assert "AUTOSAVE_DELAY = 900" in editor.text
    assert "Changes saved automatically" in editor.text
    assert 'id="toast"' in editor.text
    assert "AUTOSAVE_DELAY = 900" in editor.text
    assert "Changes saved automatically" in editor.text
    assert 'id="document-content"' in editor.text
    assert 'aria-label="Bold"' in editor.text
    assert 'aria-label="Italic"' in editor.text
    assert 'aria-label="Underline"' in editor.text
    assert 'value="h1">Heading 1' in editor.text
    assert 'value="h2">Heading 2' in editor.text
    assert 'aria-label="Bulleted list"' in editor.text
    assert 'aria-label="Numbered list"' in editor.text

    created = client.post(
        "/api/documents",
        json={"title": "Assignment notes", "content": "First draft"},
    )
    assert created.status_code == 201
    assert created.json()["access"] == "owned"
    assert created.json()["owner_username"] == "alice"
    document_id = created.json()["id"]

    saved = client.put(
        f"/api/documents/{document_id}",
        json={"title": "Final notes", "content": "Finished draft"},
    )
    assert saved.status_code == 200
    assert saved.json()["title"] == "Final notes"
    assert saved.json()["content"] == "Finished draft"

    reopened = client.get(f"/api/documents/{document_id}")
    assert reopened.status_code == 200
    assert reopened.json()["title"] == "Final notes"
    assert reopened.json()["content"] == "Finished draft"

    listed = client.get("/api/documents")
    assert [document["id"] for document in listed.json()] == [document_id]


def test_health_check_reports_database_ready(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rich_text_content_survives_save_and_reopen(client):
    created = client.post(
        "/api/documents",
        json={"title": "Formatted notes", "content": ""},
    )
    document_id = created.json()["id"]
    rich_content = "<h1>Title</h1><p><strong>Bold</strong> and <em>italic</em></p><ul><li>Item</li></ul>"

    saved = client.put(
        f"/api/documents/{document_id}",
        json={"content": rich_content},
    )
    assert saved.status_code == 200
    assert saved.json()["content"] == rich_content

    reopened = client.get(f"/api/documents/{document_id}")
    assert reopened.json()["content"] == rich_content


@pytest.mark.parametrize("filename", ["meeting-notes.txt", "meeting-notes.md"])
def test_import_text_file_creates_editable_document(client, filename):
    editor = client.get("/")
    assert 'id="import-file"' in editor.text
    assert 'accept=".txt,.md,.docx"' in editor.text

    response = client.post(
        "/api/documents/import",
        files={"file": (filename, "First line\nSecond <line>".encode())},
    )

    assert response.status_code == 201
    imported = response.json()
    assert imported["title"] == "meeting-notes"
    assert imported["content"] == "First line<br>Second &lt;line&gt;"

    reopened = client.get(f"/api/documents/{imported['id']}")
    assert reopened.json()["content"] == imported["content"]


def test_import_docx_file_creates_document(client):
    word_document = WordDocument()
    word_document.add_paragraph("Imported paragraph")
    word_file = BytesIO()
    word_document.save(word_file)

    response = client.post(
        "/api/documents/import",
        files={
            "file": (
                "report.docx",
                word_file.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["title"] == "report"
    assert response.json()["content"] == "Imported paragraph"


def test_import_rejects_unsupported_and_invalid_files(client):
    unsupported = client.post(
        "/api/documents/import",
        files={"file": ("notes.pdf", b"not supported")},
    )
    assert unsupported.status_code == 415

    invalid_docx = client.post(
        "/api/documents/import",
        files={"file": ("broken.docx", b"not a DOCX file")},
    )
    assert invalid_docx.status_code == 400

    invalid_text = client.post(
        "/api/documents/import",
        files={"file": ("notes.txt", b"\xff")},
    )
    assert invalid_text.status_code == 400

    oversized = client.post(
        "/api/documents/import",
        files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))},
    )
    assert oversized.status_code == 413


def test_document_title_cannot_be_blank(client):
    response = client.post(
        "/api/documents",
        json={"title": "   ", "content": ""},
    )
    assert response.status_code == 422


def test_missing_document_returns_not_found(client):
    response = client.get("/api/documents/999")
    assert response.status_code == 404


def test_accounts_require_login_and_password_is_checked(client):
    protected_response = client.get("/api/documents")
    assert protected_response.status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/documents").status_code == 401

    invalid_login = client.post(
        "/api/auth/login",
        json={"email": "alice@example.test", "password": "wrong-password"},
    )
    assert invalid_login.status_code == 401

    valid_login = client.post(
        "/api/auth/login",
        json={"email": "ALICE@example.test", "password": "alice-password"},
    )
    assert valid_login.status_code == 200
    assert valid_login.json()["email"] == "alice@example.test"
    assert "password" not in valid_login.json()
    assert client.get("/api/auth/me").status_code == 200


def test_registration_rejects_duplicate_account(client):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.test",
            "password": "another-password",
        },
    )
    assert response.status_code == 409


def test_owner_can_share_read_and_write_access(client):
    created = client.post(
        "/api/documents",
        json={"title": "Shared notes", "content": "Original"},
    )
    document_id = created.json()["id"]

    registration = client.post(
        "/api/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.test",
            "password": "bob-password",
        },
    )
    assert registration.status_code == 201
    bob_id = registration.json()["id"]
    assert client.get(f"/api/documents/{document_id}").status_code == 404

    client.post(
        "/api/auth/logout",
    )
    login_alice = client.post(
        "/api/auth/login",
        json={"email": "alice@example.test", "password": "alice-password"},
    )
    assert login_alice.status_code == 200

    share_response = client.post(
        f"/api/documents/{document_id}/shares",
        json={"email": "bob@example.test"},
    )
    assert share_response.status_code == 201
    assert share_response.json()["permission"] == "read"

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "bob@example.test", "password": "bob-password"},
    )
    shared_list = client.get("/api/documents")
    assert shared_list.status_code == 200
    assert shared_list.json()[0]["access"] == "shared"
    assert shared_list.json()[0]["owner_username"] == "alice"

    shared_document = client.get(f"/api/documents/{document_id}")
    assert shared_document.status_code == 200
    assert shared_document.json()["access"] == "shared"
    assert shared_document.json()["permission"] == "read"
    assert client.post(
        f"/api/documents/{document_id}/shares",
        json={"email": "alice@example.test"},
    ).status_code == 404
    assert client.put(
        f"/api/documents/{document_id}",
        json={"content": "Not allowed"},
    ).status_code == 403

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "alice@example.test", "password": "alice-password"},
    )
    upgraded_share = client.post(
        f"/api/documents/{document_id}/shares",
        json={"email": "bob@example.test", "permission": "write"},
    )
    assert upgraded_share.status_code == 201
    assert upgraded_share.json()["permission"] == "write"
    assert client.get(f"/api/documents/{document_id}/shares").json()[0]["username"] == "bob"

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "bob@example.test", "password": "bob-password"},
    )
    editable_document = client.get(f"/api/documents/{document_id}")
    assert editable_document.json()["permission"] == "write"
    updated = client.put(
        f"/api/documents/{document_id}",
        json={"content": "Bob edited this"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Bob edited this"

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "alice@example.test", "password": "alice-password"},
    )
    assert client.delete(
        f"/api/documents/{document_id}/shares/{bob_id}"
    ).status_code == 204
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "bob@example.test", "password": "bob-password"},
    )
    assert client.get(f"/api/documents/{document_id}").status_code == 404


def test_documents_formatting_and_shares_survive_app_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "PASSWORD_ITERATIONS", 1_000)
    database_path = tmp_path / "restart-documents.db"
    first_engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}"
    )
    first_session_factory = async_sessionmaker(
        bind=first_engine,
        class_=db.AsyncSessionLocal.class_,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db, "engine", first_engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", first_session_factory)
    monkeypatch.setattr(main_module, "engine", first_engine)

    try:
        with TestClient(main_module.app) as first_client:
            owner = first_client.post(
                "/api/auth/register",
                json={
                    "username": "owner",
                    "email": "owner@example.test",
                    "password": "owner-password",
                },
            )
            assert owner.status_code == 201
            owner_cookie = first_client.cookies.get("doc_session")

            first_client.post(
                "/api/auth/register",
                json={
                    "username": "reader",
                    "email": "reader@example.test",
                    "password": "reader-password",
                },
            )
            first_client.post("/api/auth/logout")
            first_client.post(
                "/api/auth/login",
                json={
                    "email": "owner@example.test",
                    "password": "owner-password",
                },
            )

            rich_content = (
                "<h1>Persisted title</h1><p><strong>Formatted text</strong></p>"
                "<ol><li>First item</li></ol>"
            )
            created = first_client.post(
                "/api/documents",
                json={"title": "Persistent document", "content": rich_content},
            )
            assert created.status_code == 201
            document_id = created.json()["id"]

            share = first_client.post(
                f"/api/documents/{document_id}/shares",
                json={"email": "reader@example.test", "permission": "read"},
            )
            assert share.status_code == 201
    finally:
        asyncio.run(first_engine.dispose())

    second_engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}"
    )
    second_session_factory = async_sessionmaker(
        bind=second_engine,
        class_=db.AsyncSessionLocal.class_,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db, "engine", second_engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", second_session_factory)
    monkeypatch.setattr(main_module, "engine", second_engine)

    try:
        with TestClient(main_module.app) as second_client:
            second_client.cookies.set("doc_session", owner_cookie)
            reopened = second_client.get(f"/api/documents/{document_id}")
            assert reopened.status_code == 200
            assert reopened.json()["content"] == rich_content
            assert second_client.get(
                f"/api/documents/{document_id}/shares"
            ).json()[0]["email"] == "reader@example.test"

            second_client.post("/api/auth/logout")
            login = second_client.post(
                "/api/auth/login",
                json={
                    "email": "reader@example.test",
                    "password": "reader-password",
                },
            )
            assert login.status_code == 200

            shared_list = second_client.get("/api/documents")
            assert shared_list.status_code == 200
            assert shared_list.json()[0]["access"] == "shared"
            assert shared_list.json()[0]["permission"] == "read"

            shared_document = second_client.get(
                f"/api/documents/{document_id}"
            )
            assert shared_document.json()["content"] == rich_content
            assert second_client.put(
                f"/api/documents/{document_id}",
                json={"content": "Reader cannot edit"},
            ).status_code == 403
    finally:
        asyncio.run(second_engine.dispose())
