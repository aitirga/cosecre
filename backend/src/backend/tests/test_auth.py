from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.models import WorkspaceSetting


def build_test_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        secret_key="test-secret-with-at-least-thirty-two-bytes",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        seed_users_file=tmp_path / "seed_users.json",
        openai_api_key="test-key",
    )
    return TestClient(create_app(settings))


def test_register_login_and_me(tmp_path: Path):
    with build_test_client(tmp_path) as client:
        register_response = client.post(
            "/api/auth/register",
            json={"email": "admin@example.com", "password": "supersecure"},
        )
        assert register_response.status_code == 201
        payload = register_response.json()
        assert payload["user"]["is_admin"] is True

        login_response = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "supersecure"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["access_token"]

        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "admin@example.com"


def test_admin_can_update_workspace_settings(tmp_path: Path):
    with build_test_client(tmp_path) as client:
        auth_response = client.post(
            "/api/auth/register",
            json={"email": "admin@example.com", "password": "supersecure"},
        )
        access_token = auth_response.json()["access_token"]
        update_response = client.put(
            "/api/settings",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
                "sheet_name": "Factures",
                "openai_model": "gpt-5.4",
                "extraction_prompt": "Use the schema.",
                "polling_interval_seconds": 30,
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["sheet_name"] == "Factures"


def test_seeded_users_can_login(tmp_path: Path):
    seed_file = tmp_path / "seed_users.json"
    seed_file.write_text(
        json.dumps(
            [
                {
                    "email": "gerecaste91@gmail.com",
                    "password": "admin",
                    "is_admin": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    with build_test_client(tmp_path) as client:
        login_response = client.post(
            "/api/auth/login",
            json={"email": "gerecaste91@gmail.com", "password": "admin"},
        )
        assert login_response.status_code == 200
        payload = login_response.json()
        assert payload["user"]["email"] == "gerecaste91@gmail.com"
        assert payload["user"]["is_admin"] is True


def test_workspace_settings_migrates_legacy_default_model(tmp_path: Path):
    settings = Settings(
        secret_key="test-secret-with-at-least-thirty-two-bytes",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        seed_users_file=tmp_path / "seed_users.json",
        openai_api_key="test-key",
    )

    with TestClient(create_app(settings)) as client:
        session = client.app.state.session_factory()
        try:
            workspace = session.get(WorkspaceSetting, 1)
            assert workspace is not None
            workspace.openai_model = "gpt-4.1-mini"
            session.commit()
        finally:
            session.close()

    with TestClient(create_app(settings)) as client:
        session = client.app.state.session_factory()
        try:
            workspace = session.get(WorkspaceSetting, 1)
            assert workspace is not None
            assert workspace.openai_model == "gpt-5.4"
        finally:
            session.close()
