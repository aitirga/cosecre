from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COSECRE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Cosecre API"
    api_prefix: str = "/api"
    secret_key: str = "change-me-in-production"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'cosecre.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    seed_users_file: Path = BASE_DIR / "seed_users.json"
    google_service_account_file: Path | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        self.upload_dir = self._resolve_path(self.upload_dir)
        self.seed_users_file = self._resolve_path(self.seed_users_file)
        if self.google_service_account_file is not None:
            self.google_service_account_file = self._resolve_path(self.google_service_account_file)
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.removeprefix("sqlite:///")
            if not Path(raw_path).is_absolute():
                self.database_url = f"sqlite:///{self._resolve_path(Path(raw_path)).as_posix()}"
        return self

    def _resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            database_path = Path(self.database_url.removeprefix("sqlite:///"))
            database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
