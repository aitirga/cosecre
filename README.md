# Cosecre

AI secretary assistant MVP for invoice intake, extraction, validation, and Google Sheets sync.

## Stack

- Frontend: Vue 3 + Vite + PWA + Vue Query
- Backend: FastAPI + SQLite + OpenAI + Google Sheets
- Python environment: `uv`

## Project structure

- [frontend](/Users/aitoriraolagalarza/dev/personal/cosecre/frontend)
- [backend](/Users/aitoriraolagalarza/dev/personal/cosecre/backend)

## Backend setup

1. Copy [backend/.env.example](/Users/aitoriraolagalarza/dev/personal/cosecre/backend/.env.example) to `backend/.env`.
2. Edit [backend/seed_users.json](/Users/aitoriraolagalarza/dev/personal/cosecre/backend/seed_users.json) to manage preset accounts. On startup the backend upserts every listed user.
3. Share the target Google Sheet with the service account from your credentials file.
4. Install and sync Python dependencies:

```bash
uv sync --project backend
```

5. Run the API:

```bash
uv run --project backend backend
```

## Frontend setup

```bash
npm install --prefix frontend
npm run --prefix frontend dev
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.
