# Architecture Note

## Structure

- `app/main.py` creates the FastAPI application, initializes database tables,
  registers the API routers, and serves the editor page.
- `app/routers/auth.py` handles account registration, login, and logout.
  Passwords are PBKDF2-hashed; opaque session tokens are stored as hashes in
  the database and sent to the browser in an HTTP-only cookie.
- `app/routers/documents.py` provides document, import, and sharing endpoints.
  `app/services.py` contains the database operations used by those endpoints.
- `app/models.py` defines users, sessions, documents, and document shares.
  `app/schemas.py` validates API input and shapes API responses.
- `app/templates/editor.html` is the browser UI. It edits supported rich-text
  HTML, autosaves changes, and shows owned and shared documents.
- `app/db.py` configures async SQLAlchemy with SQLite. The database location
  can be overridden with `DOCSAPP_DATABASE_PATH`.

## Main data flows

1. A user registers or logs in; the server verifies the password and creates a
   persistent session.
2. The browser requests documents for the signed-in user. The API returns
   documents they own and documents shared with them.
3. Editing sends the document title and formatted HTML to the API. The server
   checks ownership or write permission before updating the database.
4. An owner shares by a registered account email and selects read or write
   access. The recipient sees the document in their list after login or refresh.
   The API enforces the permission on every read or write request.

## Priorities and tradeoffs

For a small assignment, the implementation prioritizes an end-to-end,
demonstrable workflow, explicit API validation, persistence, and server-side
permission checks. SQLite keeps local setup simple and is backed by a mounted
volume in the deployment. It assumes one application replica; SQLite on a
single mounted volume is not a multi-replica database strategy. The app does
not attempt to provide production-grade account recovery, collaboration
presence, or concurrent rich-text editing.
