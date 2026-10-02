from fastapi.testclient import TestClient

from cosecre_hub.config import Settings
from cosecre_hub.main import create_app


def test_production_web_routes_and_api(tmp_path):
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'index.html').write_text('<html>Cosecre</html>')
    settings = Settings(
        database_url=f'sqlite:///{tmp_path}/test.db',
        upload_dir=tmp_path / 'uploads',
        static_dir=web,
        secret_key='test-secret',
    )
    with TestClient(create_app(settings)) as client:
        assert client.get('/').text == '<html>Cosecre</html>'
        assert client.get('/settings/team').text == '<html>Cosecre</html>'
        assert client.get('/healthz').json()['status'] == 'ok'
        assert client.get('/api/v1/nonexistent').status_code == 404
        assert client.get('/assets/missing.js').status_code == 404
