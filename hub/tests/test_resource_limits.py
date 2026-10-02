from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import MagicMock

import pytest

from conftest import build_settings, register_admin
from cosecre_hub.api.documents import register, routes
from cosecre_hub.bootstrap import recover_interrupted_jobs
from cosecre_hub.models import ExtractionJob, Upload, WorkspaceSetting
from cosecre_hub.services import sheets


def test_polling_reuses_google_clients_and_shutdown_closes_them(tmp_path, monkeypatch):
    client = MagicMock()
    spreadsheets = client.spreadsheets.return_value
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"sheetId": 1, "title": "Registre documents comptables",
                                   "gridProperties": {"rowCount": 1000, "columnCount": 30}}}]
    }
    spreadsheets.values.return_value.get.return_value.execute.return_value = {
        "values": [[column.header for column in sheets.REGISTER_COLUMNS]]
    }
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(sheets, "build", factory)
    monkeypatch.setattr(sheets.GoogleSheetsService, "_credentials", lambda self: None)
    service = sheets.GoogleSheetsService(build_settings(tmp_path))
    workspace = WorkspaceSetting(spreadsheet_id="test", registry_sheet_name="Registre documents comptables")
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: service.read_register(workspace), range(100)))
    assert results == [[]] * 100
    assert factory.call_count == 1
    client.spreadsheets.assert_called_once()
    spreadsheets.values.assert_called_once()
    # The column layout is cached, not re-discovered on every poll.
    assert spreadsheets.get.call_count == 1
    service.close()
    client.close.assert_called_once()


def test_concurrent_appends_choose_distinct_rows(tmp_path, monkeypatch):
    service = sheets.GoogleSheetsService(build_settings(tmp_path))
    rows: list[sheets.SheetRow] = []
    layout = sheets.RegisterLayout("test", 1, "Registre", {"num_doc_intern": 0}, 1, 1000)
    monkeypatch.setattr(service, "register_layout", lambda *args, **kwargs: layout)
    monkeypatch.setattr(service, "read_register", lambda *args: list(rows))

    def batch(_spreadsheet_id, requests):
        # Yield to competing calls after choosing a row. Without operation-wide
        # serialization two requests can overwrite the same spreadsheet row.
        import time
        time.sleep(0.01)
        row = requests[0]["updateCells"]["start"]["rowIndex"] + 1
        rows.append(sheets.SheetRow(row, {"num_doc_intern": str(row)}))

    monkeypatch.setattr(service, "_batch", batch)
    workspace = WorkspaceSetting(spreadsheet_id="test")
    with ThreadPoolExecutor(max_workers=4) as workers:
        result = list(workers.map(
            lambda i: service.append_row(workspace, {"num_doc_intern": str(i)}), range(8)
        ))
    assert sorted(result) == list(range(2, 10))


@pytest.mark.parametrize("fails", [False, True])
def test_drive_streams_bounded_chunks_and_closes_file(tmp_path, monkeypatch, fails):
    service = sheets.GoogleSheetsService(build_settings(tmp_path))
    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-1.7")
    client = MagicMock()
    media_seen = []

    def create(**kwargs):
        media = kwargs["media_body"]
        media_seen.append(media)
        assert media.resumable()
        assert media.chunksize() == 1024 * 1024
        assert not media.stream().closed
        request = MagicMock()
        if fails:
            request.execute.side_effect = RuntimeError("Network failed")
        else:
            request.execute.return_value = {"id": "file-id", "webViewLink": "https://example.com"}
        return request

    client.files.return_value.create.side_effect = create
    monkeypatch.setattr(service, "_drive_service", lambda: client)
    if fails:
        with pytest.raises(RuntimeError, match="Network failed"):
            service.upload_file_to_drive(path, "document.pdf", "application/pdf")
    else:
        service.upload_file_to_drive(path, "document.pdf", "application/pdf")
    assert media_seen[0].stream().closed


@pytest.mark.asyncio
async def test_extractions_wait_without_occupying_worker_threads(hub, monkeypatch):
    client, _ = hub
    started, release = Event(), Event()
    lock = Lock()
    active = peak = completed = 0

    def work(app, job_id):
        nonlocal active, peak, completed
        with lock:
            active += 1
            peak = max(peak, active)
        started.set()
        assert release.wait(timeout=5)
        with lock:
            active -= 1
            completed += 1

    monkeypatch.setattr(routes, "process_job", work)
    assert register.process_job is not work
    tasks = [asyncio.create_task(routes.process_job_in_background(client.app, str(i))) for i in range(12)]
    try:
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0.05)
        limit = client.app.state.settings.extraction_concurrency
        assert peak == limit  # parallel up to the limit, never past it
        assert client.get("/healthz").status_code == 200
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert completed == 12
    assert peak == limit


def test_restart_marks_orphans_without_losing_payload_or_upload(hub):
    client, _ = hub
    register_admin(client)
    with client.app.state.session_factory() as session:
        for i, state in enumerate(["pending", "processing", "written_to_sheet", "needs_validation"]):
            upload = Upload(user_id=1, internal_doc_number=f"INV-{i}",
                            source_file_name="invoice.pdf", source_file_type="application/pdf",
                            stored_path=f"/tmp/invoice-{i}.pdf", status=state)
            session.add(ExtractionJob(id=str(i), user_id=1, upload=upload, status=state,
                                      extracted_payload={"proveidor": "Preserved"}))
        session.commit()
        assert recover_interrupted_jobs(session) == 3
        assert recover_interrupted_jobs(session) == 0
        jobs = session.query(ExtractionJob).order_by(ExtractionJob.id).all()
        assert [job.status for job in jobs] == ["error", "error", "error", "needs_validation"]
        assert all(job.extracted_payload == {"proveidor": "Preserved"} for job in jobs)
        assert session.query(Upload).count() == 4


@pytest.mark.asyncio
async def test_enrichment_runs_in_parallel_but_leaves_a_slot_for_live_photos(hub, monkeypatch):
    from cosecre_hub.api.documents import migration

    client, _ = hub
    limit = client.app.state.settings.extraction_concurrency
    release = Event()
    lock = Lock()
    active = peak = 0

    def slow_enrich(app, document_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        assert release.wait(timeout=5)
        with lock:
            active -= 1

    live_done = Event()
    monkeypatch.setattr(migration, "pending_enrichment", lambda session: list(range(20)))
    monkeypatch.setattr(migration, "enrich_one", slow_enrich)
    monkeypatch.setattr(routes, "process_job", lambda app, job_id: live_done.set())

    enrichment = asyncio.create_task(migration.enrich_all(client.app))
    try:
        await asyncio.sleep(0.1)
        assert peak == limit - 1
        # A photo taken now is read straight away, not after the migration.
        await routes.process_job_in_background(client.app, "live")
        assert live_done.is_set()
    finally:
        release.set()
        await enrichment
    assert peak == limit - 1
