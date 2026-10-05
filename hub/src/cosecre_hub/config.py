from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

#: Slug of the app that owns the invoice/ticket pipeline. Used to namespace its
#: settings in the shared per-app settings bag.
DOCUMENTS_APP_SLUG = "cosecre-docs"


class Settings(BaseSettings):
    """Hub configuration.

    The env prefix is deliberately ``COSECRE_`` rather than ``COSECRE_HUB_``:
    the hub is a drop-in replacement for the old single-purpose backend, so an
    existing ``backend/.env`` can be copied across unchanged.
    """

    model_config = SettingsConfigDict(
        env_prefix="COSECRE_",
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Cosecre Hub"
    api_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    static_dir: Path | None = None
    # Disabled locally; production exits cleanly after this many idle seconds.
    idle_timeout_seconds: int = Field(default=0, ge=0)

    # ---------------------------------------------------------------- identity
    secret_key: str = "change-me-in-production"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30

    #: When false, ``POST /auth/register`` only works while the hub has no users
    #: at all — the bootstrap of the first admin. Afterwards accounts are
    #: created by an admin through ``POST /users``. Closed is the default because
    #: a hub reachable from the internet with open registration is an open door.
    allow_open_registration: bool = False

    #: Optional first-admin bootstrap. Set both to have the account created (or
    #: its password reset) on startup. Preferred over a seed file: nothing
    #: sensitive ends up on disk inside the repo.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    #: Legacy seed file, kept so existing deployments keep working. It holds
    #: plaintext passwords, so it must never be committed — see .gitignore.
    seed_users_file: Path | None = None

    # ---------------------------------------------------------------- storage
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'cosecre.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"

    # -------------------------------------------------------------------- llm
    openai_api_key: str | None = None
    openai_model: str = "gpt-6-luna"
    #: Sent as the Responses API ``reasoning.effort``. Empty disables the field,
    #: which is what non-reasoning models need.
    openai_reasoning_effort: str = "medium"

    #: TypeSafe's Jev, the second opinion on every closed-list field. Optional:
    #: without it the vision model decides alone.
    typesafe_api_key: str | None = None
    jev_model: str = "jev-latest"

    # ----------------------------------------------------------------- google
    google_service_account_file: Path | None = None
    #: One folder for every document, named ``<date>_<number>``.
    google_drive_documents_folder_id: str | None = None
    #: Where the two folders of the invoice/ticket era pointed. The register
    #: falls back to the invoices one when no documents folder is set.
    google_drive_invoices_folder_id: str | None = None
    google_drive_tickets_folder_id: str | None = None
    #: Off-site copy of every backup. Optional; local backups run regardless.
    google_drive_backup_folder_id: str | None = None
    #: The petty-cash ledger read by the statements module, used until someone
    #: sets one in Configuració. Kept out of the code: the repository is public.
    caixeta_spreadsheet_url: str | None = None

    #: How long the statements mirror waits after a change before rewriting the
    #: sheet, so a run of confirmations costs one write. ``0`` writes at once,
    #: in the request — what the tests use.
    statement_mirror_delay_seconds: float = Field(default=5.0, ge=0)

    #: How many documents the models read at once. Reading is almost all
    #: waiting on the model API, so this is about API rate limits and memory
    #: (each in-flight photo is held base64-encoded), not CPU.
    extraction_concurrency: int = Field(default=4, ge=1, le=16)

    # ---------------------------------------------------------------- backups
    #: Defaults to a ``backups`` folder next to a SQLite database, so it lands
    #: on the same persistent volume without extra configuration.
    #: Off only in tests; the scheduler is how backups happen at all.
    backup_enabled: bool = True
    backup_dir: Path | None = None
    backup_keep: int = Field(default=30, ge=1)
    backup_interval_hours: float = Field(default=24, gt=0)

    # ------------------------------------------------------------------- cors
    #: ``file://`` and ``null`` are what a packaged Electron renderer sends as
    #: its Origin. Without them the desktop app cannot reach the hub at all.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "file://",
            "null",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://localhost:9090",
            "http://127.0.0.1:9090",
        ]
    )
    cors_origin_regex: str = (
        r"^https?://("
        r"localhost"
        r"|127\.0\.0\.1"
        r"|(?:\d{1,3}\.){3}\d{1,3}"
        r"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
        r")(?::(4173|5000|5173|8000|9090))?$"
    )

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        self.upload_dir = self._resolve_path(self.upload_dir)
        if self.seed_users_file is not None:
            self.seed_users_file = self._resolve_path(self.seed_users_file)
        if self.google_service_account_file is not None:
            self.google_service_account_file = self._resolve_path(self.google_service_account_file)
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.removeprefix("sqlite:///")
            if raw_path and not Path(raw_path).is_absolute():
                self.database_url = f"sqlite:///{self._resolve_path(Path(raw_path)).as_posix()}"
        if self.backup_dir is not None:
            self.backup_dir = self._resolve_path(self.backup_dir)
        elif self.sqlite_path is not None:
            self.backup_dir = self.sqlite_path.parent / "backups"
        else:
            self.backup_dir = BASE_DIR / "data" / "backups"
        return self

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        raw_path = self.database_url.removeprefix("sqlite:///")
        if raw_path in {"", ":memory:"}:
            return None
        return Path(raw_path)

    @property
    def documents_folder_id(self) -> str | None:
        return self.google_drive_documents_folder_id or self.google_drive_invoices_folder_id

    def _resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        if self.backup_dir is not None:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            database_path = Path(self.database_url.removeprefix("sqlite:///"))
            if str(database_path) not in {"", "."}:
                database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def is_secret_key_default(self) -> bool:
        return self.secret_key == "change-me-in-production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
