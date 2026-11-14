# Documents Mockup

A small Google Docs-style assignment project with accounts, document editing,
file import, and owner-managed sharing.

## Requirements

- Python 3.11 or newer
- PowerShell on Windows (or an equivalent terminal)
- Docker Desktop only if running the container

## Set up and run locally

From the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r app\dependencies.txt
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), register an account, and
create a document. The SQLite database is stored in `docsapp.db` in the project
root by default. To store it elsewhere, set `DOCSAPP_DATABASE_PATH` to an
absolute file path before starting the app.

The API schema is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests cover account registration and login, document creation and editing,
rich-text persistence, file imports, sharing permissions, and reopening the app
against the same database.

## Run with Docker

```powershell
docker build -t documents-mockup .
docker volume create documents-data
docker run --rm -p 8000:8000 `
  -v documents-data:/var/data `
  -e DOCSAPP_DATABASE_PATH=/var/data/docsapp.db `
  -e DOCSAPP_COOKIE_SECURE=false `
  documents-mockup
```

The named volume keeps the SQLite database when the container is replaced.
`DOCSAPP_COOKIE_SECURE=false` is for local HTTP only; use secure cookies behind
HTTPS.

## Deploy for reviewer access

The repository includes a Render Blueprint in `render.yaml`. To publish it:

1. Push this repository to a Git provider supported by Render.
2. In Render, choose **New → Blueprint**, connect the repository, and apply the
   blueprint.
3. Wait for the service health check to pass, then open the generated
   `onrender.com` URL and register an account.

The Blueprint uses a Docker web service, an attached persistent disk for the
SQLite database, and secure session cookies for HTTPS. The persistent disk
requires a Render plan that supports disks. A public URL is created by Render
when the Blueprint is applied; it cannot be created from this local workspace
without access to the hosting account and a remote repository.

## Architecture

- FastAPI serves the editor and JSON endpoints; async SQLAlchemy with SQLite
  stores users, sessions, documents, and share permissions.
- The browser editor stores rich-text structure as HTML in each document. The
  editor sanitizes loaded content to keep supported formatting tags while
  removing unsupported markup.
- Owners can grant read or write access to another registered account. Access
  is checked by the API on every document request, rather than relying on the
  UI alone.
- For this assignment, the priorities are straightforward persistence,
  demonstrable sharing behavior, and a small deployment footprint. SQLite and
  a single app instance keep setup simple; this is not intended as a
  multi-instance production service.

This is an educational mockup, not a production identity or document service.
