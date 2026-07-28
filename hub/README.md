# Cosecre Hub

The shared backend every Cosecre app talks to. It owns the three things no client
app should have to own for itself:

- **Identity** — accounts, password hashing, access/refresh tokens, per-device sessions.
- **Storage** — the database, uploaded files, and a per-app settings bag.
- **Model access** — a provider-agnostic LLM gateway, so an API key lives here and nowhere else.

Domain features sit on top of that core. The invoice/ticket pipeline is the first
one, and the [web app](../frontend) and [desktop app](../desktop) are both just
clients.

```
┌──────────────┐   ┌──────────────┐   ┌───────────────┐
│  web (Vue)   │   │   desktop    │   │  any new app  │
└──────┬───────┘   └──────┬───────┘   └───────┬───────┘
       └──────────────────┼───────────────────┘
                   HTTPS + bearer tokens
                          ▼
                  ┌───────────────┐        ┌──────────┐
                  │  cosecre-hub  │───────▶│ provider │
                  └───────┬───────┘        └──────────┘
                    SQLite/Postgres
```

## Running it

```bash
uv sync
```

```bash
cp .env.example .env
```

```bash
uv run cosecre-hub
```

The API is served under `/api/v1`, with interactive docs at
[`/docs`](http://127.0.0.1:8000/docs) and a liveness probe at `/healthz`.

### First account

Set both variables and restart — the account is created, or its password reset, on
startup:

```bash
COSECRE_BOOTSTRAP_ADMIN_EMAIL=you@example.com
COSECRE_BOOTSTRAP_ADMIN_PASSWORD=something-long-and-unguessable
```

That is also the documented way back in after a lockout. Alternatively, register
the very first account through the API or the web app's sign-in screen: while the
hub has no users, `POST /auth/register` is open and the first account it creates
is an admin.

**Registration closes as soon as one account exists.** After that, accounts are
created by an admin (`POST /users`), which is what replaces the old
`seed_users.json` and its plaintext passwords. Set
`COSECRE_ALLOW_OPEN_REGISTRATION=true` only if you actually want anyone who can
reach the hub to be able to sign up.

## API

Everything below is prefixed with `/api/v1`.

| Area | Endpoint | Notes |
|---|---|---|
| Discovery | `GET /meta` | **No token.** What a client reads to validate a hub URL. |
| Auth | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all` | Refresh tokens rotate on use. |
| Auth | `GET /auth/me`, `GET /auth/sessions`, `POST /auth/password` | Sessions are listed per client app. |
| Users | `GET/POST /users`, `PATCH/DELETE /users/{id}` | Admin only. Accounts are disabled, never deleted. |
| Apps | `GET /apps`, `GET/PUT /apps/{slug}/settings`, `GET/PUT/DELETE /apps/{slug}/settings/{key}` | Read: any user. Write: admin. |
| LLM | `GET /llm/providers`, `POST /llm/complete`, `/llm/structured`, `/llm/extract` | `structured` takes a JSON Schema; `extract` takes a file. |
| Documents | `GET/PUT /documents/settings` | Google Sheet target, tab names, model, prompt. |
| Documents | `.../documents/invoices`, `.../documents/tickets` | `upload`, list, get, `PATCH`, `validate`, `file`, `DELETE`, `jobs/{id}` |

### `GET /meta` is the integration point

A new app does not need to be told what a hub can do — it asks:

```json
{
  "product": "cosecre-hub",
  "version": "0.1.0",
  "api_version": "1",
  "api_prefix": "/api/v1",
  "capabilities": { "auth": true, "app_settings": true, "llm": true, "documents": true,
                    "google_sheets": false },
  "apps": ["cosecre-docs", "cosecre-print"],
  "accepts_registration": false,
  "has_users": true
}
```

This endpoint is deliberately unauthenticated and deliberately dull: it reports
*presence*, never values. A client has to be able to check a URL someone just
typed before it holds any credentials for it.

### Adding a Cosecre app

1. Pick a slug (`cosecre-print`).
2. Sign in against `/auth/login`, sending `client` so the session is identifiable.
3. Read and write your configuration at `/apps/<slug>/settings` — one JSON bundle.
4. Call models through `/llm/*` instead of shipping an API key.

No server-side change is needed for any of that.

## Design notes

**Refresh tokens are stored hashed and rotate on every use.** A leaked database
cannot be replayed as a set of live sessions, and a stolen token stops working
the moment the real client refreshes. `POST /auth/logout` retires one session;
changing a password retires all of them.

**`is_active` is checked on every request, not only at sign-in.** An access token
stays cryptographically valid until it expires, so disabling an account has to
take effect against the token that already exists.

**The last admin cannot be demoted or disabled.** Both would leave a hub that
nobody can administer and no API path back.

**The LLM registry is injected, not imported.** `create_app(settings,
llm_registry=…)` is what lets the whole test suite exercise the model paths
without a network call, and what makes a second provider a one-file change.

**Strict JSON Schema is normalised for you.** Structured-output modes require
every object to list all its properties as required and to forbid extras;
`to_strict_json_schema` does that, and drops `default` (which cannot apply once
everything is required, and which some providers reject).

## Migrating from the old `backend/`

The hub is schema-compatible with the database the previous single-purpose
backend created: same tables, same columns, with everything it adds either
nullable or defaulted. Point it at the existing file and it picks up your users,
uploads, jobs and workspace settings as they are:

```bash
COSECRE_DATABASE_URL=sqlite:////absolute/path/to/backend/data/cosecre.db
COSECRE_UPLOAD_DIR=/absolute/path/to/backend/data/uploads
```

On startup any missing column is added (see `ADDED_COLUMNS` in
[`bootstrap.py`](src/cosecre_hub/bootstrap.py)), so there is no migration step to
run. Copy the rest of `backend/.env` across unchanged — the env prefix is still
`COSECRE_` precisely so that works.

What changed for clients:

| Old | New |
|---|---|
| `/api/auth/*` | `/api/v1/auth/*` |
| `/api/invoices`, `/api/tickets` | `/api/v1/documents/invoices`, `/api/v1/documents/tickets` |
| `/api/settings` | `/api/v1/documents/settings` |
| — | `/api/v1/meta`, `/api/v1/users`, `/api/v1/apps/*`, `/api/v1/llm/*` |

`seed_users.json` still works if `COSECRE_SEED_USERS_FILE` points at one, but it
holds plaintext passwords and the hub logs a warning on every start. Prefer the
bootstrap-admin variables plus admin-managed accounts.

## Tests

```bash
uv run pytest
```

Every test runs against a fake model provider and a dict standing in for Google
Sheets, so the suite needs no credentials and makes no network calls.

## Configuration

Every variable, its default, and why it exists is in
[`.env.example`](.env.example). The ones that matter most:

| Variable | Default | Notes |
|---|---|---|
| `COSECRE_SECRET_KEY` | `change-me-in-production` | Signs access tokens. The hub warns on every start until you change it. |
| `COSECRE_DATABASE_URL` | `sqlite:///hub/data/cosecre.db` | Any SQLAlchemy URL. |
| `COSECRE_ALLOW_OPEN_REGISTRATION` | `false` | Leave off unless you mean it. |
| `COSECRE_OPENAI_API_KEY` | — | Without it, `/llm/*` answers 503 and `capabilities.llm` is false. |
| `COSECRE_GOOGLE_SERVICE_ACCOUNT_FILE` | — | Needed for the documents module's Sheets/Drive sync. |
