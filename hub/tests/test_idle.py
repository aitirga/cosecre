from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from unittest.mock import Mock

import pytest

from conftest import register_admin
from cosecre_hub.idle import ActivityMiddleware, IdleShutdown
from cosecre_hub.models import ExtractionJob, Upload


def controller(hub):
    now = [0.0]
    shutdown = Mock()
    idle = IdleShutdown(600, shutdown, hub[0].app.state.session_factory, clock=lambda: now[0])
    return idle, now, shutdown


@pytest.mark.asyncio
async def test_activity_resets_timer_health_checks_do_not(hub):
    idle, now, shutdown = controller(hub)

    async def noop(*args):
        pass

    middleware = ActivityMiddleware(noop, idle)
    now[0] = 590
    await middleware({'type': 'http', 'path': '/api/v1/meta'}, noop, noop)
    now[0] = 1100
    await middleware({'type': 'http', 'path': '/healthz'}, noop, noop)
    await idle.check()
    shutdown.assert_not_called()
    now[0] = 1190
    await idle.check()
    await idle.check()
    shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_response_background_work_blocks_shutdown(hub):
    idle, now, shutdown = controller(hub)
    sent, release = asyncio.Event(), asyncio.Event()

    async def background_app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})
        sent.set()
        await release.wait()  # response is done; background extraction is not

    async def noop(*args):
        pass

    task = asyncio.create_task(ActivityMiddleware(background_app, idle)(
        {'type': 'http', 'path': '/api/v1/documents/invoices/upload'}, noop, noop))
    await sent.wait()
    now[0] = 1000
    await idle.check()
    shutdown.assert_not_called()
    release.set()
    await task
    now[0] = 1599
    await idle.check()
    shutdown.assert_not_called()
    now[0] = 1600
    await idle.check()
    shutdown.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'processing', 'written_to_sheet'])
async def test_persisted_jobs_block_shutdown(hub, status):
    client, _ = hub
    register_admin(client)
    idle, now, shutdown = controller(hub)
    with client.app.state.session_factory() as session:
        upload = Upload(user_id=1, internal_doc_number='INV-idle', source_file_name='a.jpg',
                        source_file_type='image/jpeg', stored_path='/tmp/a.jpg')
        session.add(ExtractionJob(id='idle-job', user_id=1, upload=upload, status=status))
        session.commit()
    now[0] = 601
    await idle.check()
    shutdown.assert_not_called()
    with client.app.state.session_factory() as session:
        session.get(ExtractionJob, 'idle-job').status = 'needs_validation'
        session.commit()
    await idle.check()
    shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_database_error_and_activity_during_check_prevent_shutdown(hub, monkeypatch):
    idle, now, shutdown = controller(hub)
    now[0] = 601
    monkeypatch.setattr(idle, 'jobs_pending', Mock(side_effect=RuntimeError('database unavailable')))
    await idle.check()
    shutdown.assert_not_called()
    now[0] = 1202

    async def interleaved(_):
        idle.begin()
        idle.end()
        return False

    monkeypatch.setattr(asyncio, 'to_thread', interleaved)
    await idle.check()
    shutdown.assert_not_called()


def test_production_entry_exits_zero_despite_health_polling(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, COSECRE_HOST='127.0.0.1', COSECRE_PORT=str(port),
               COSECRE_IDLE_TIMEOUT_SECONDS='2', COSECRE_DATABASE_URL=f'sqlite:///{tmp_path}/db.sqlite',
               COSECRE_UPLOAD_DIR=str(tmp_path / 'uploads'), COSECRE_BOOTSTRAP_ADMIN_EMAIL='',
               COSECRE_BOOTSTRAP_ADMIN_PASSWORD='', COSECRE_OPENAI_API_KEY='')
    with (tmp_path / 'server.log').open('w+') as output:
        process = subprocess.Popen([sys.executable, '-m', 'cosecre_hub.server'], env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
        health_responses = 0
        try:
            deadline = time.monotonic() + 15
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=0.2) as response:
                        assert response.status == 200
                        health_responses += 1
                except OSError:
                    pass
                time.sleep(0.1)
            assert process.poll() == 0
            assert health_responses > 3
            output.seek(0)
            assert 'Idle shutdown after 2 seconds' in output.read()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
