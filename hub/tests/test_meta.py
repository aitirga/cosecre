from __future__ import annotations

from pathlib import Path

from conftest import FakeProvider, build_client, register_admin


def test_meta_is_reachable_without_credentials(hub):
    client, _ = hub

    response = client.get("/api/v1/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product"] == "cosecre-hub"
    assert payload["api_prefix"] == "/api/v1"
    assert payload["capabilities"]["auth"] is True
    assert payload["capabilities"]["documents"] is True


def test_meta_reports_a_fresh_hub_as_accepting_registration(hub):
    client, _ = hub

    before = client.get("/api/v1/meta").json()
    assert before["has_users"] is False
    assert before["accepts_registration"] is True

    register_admin(client)

    after = client.get("/api/v1/meta").json()
    assert after["has_users"] is True
    # Registration closes behind the first account unless it was opened explicitly.
    assert after["accepts_registration"] is False


def test_meta_reports_llm_availability(tmp_path: Path):
    client, _ = build_client(tmp_path, provider=FakeProvider(configured=False))
    with client:
        assert client.get("/api/v1/meta").json()["capabilities"]["llm"] is False

    client, _ = build_client(tmp_path / "configured", provider=FakeProvider(configured=True))
    with client:
        assert client.get("/api/v1/meta").json()["capabilities"]["llm"] is True


def test_healthcheck_returns_ok(hub):
    client, _ = hub

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
