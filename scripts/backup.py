"""Download a consistent SQLite copy and uploaded files from the Fly machine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def remote(token, cleanup=False):
    token = str(UUID(token))
    stage = Path('/data') / f'.backup-{token}'
    if cleanup:
        if stage.exists():
            shutil.rmtree(stage)
        Path(__file__).unlink()
        return
    stage.mkdir(mode=0o700)
    with sqlite3.connect('file:/data/cosecre.db?mode=ro', uri=True) as source:
        with sqlite3.connect(stage / 'cosecre.db') as target:
            source.backup(target)
            assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            rows = target.execute('SELECT id, stored_path FROM uploads').fetchall()
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                'missing_upload_ids': [uid for uid, p in rows if not Path(p).is_file()],
                'files': {}}
    archive_path = stage / 'backup.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as archive:
        archive.add(stage / 'cosecre.db', arcname='cosecre.db')
        for path in sorted(Path('/data/uploads').rglob('*')):
            if path.is_file() and not path.is_symlink():
                name = str(path.relative_to('/data'))
                archive.add(path, arcname=name)
                manifest['files'][name] = path.stat().st_size
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        archive.add(stage / 'manifest.json', arcname='manifest.json')
    print('BACKUP_SHA256=' + digest(archive_path), flush=True)


def main():
    os.umask(0o077)
    token = str(uuid4())
    root = Path(__file__).resolve().parents[1]
    app = 'cosecre-aitirga'
    directory = root / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = directory / f'cosecre-{stamp}-{token[:8]}.tar.gz'
    partial = output.with_suffix('.gz.partial')
    script = f'/tmp/cosecre-backup-{token}.py'
    remote_archive = f'/data/.backup-{token}/backup.tar.gz'

    def fly(*args, capture=False):
        return subprocess.run(['fly', *args, '-a', app], check=True,
                              text=True, stdout=subprocess.PIPE if capture else None)

    # Pin all operations to the same machine (volumes are machine-local).
    machines = json.loads(fly('machine', 'list', '--json', capture=True).stdout)
    running = [m['id'] for m in machines if m['state'] == 'started']
    if len(running) != 1:
        raise RuntimeError('Expected one running Fly machine; start the app and retry.')
    machine = running[0]
    fly('ssh', 'sftp', 'put', str(Path(__file__).resolve()), script, '--machine', machine)
    try:
        print('Creating database snapshot and document archive on Fly…', flush=True)
        result = fly('ssh', 'console', '--machine', machine, '-C',
                     shlex.join(['/app/hub/.venv/bin/python', script, '--remote', token]),
                     capture=True)
        checksum = next(line.split('=', 1)[1] for line in result.stdout.splitlines()
                        if line.startswith('BACKUP_SHA256='))
        fly('ssh', 'sftp', 'get', remote_archive, str(partial), '--machine', machine)
        if digest(partial) != checksum:
            raise RuntimeError('Downloaded archive checksum mismatch')
        with tarfile.open(partial) as archive, tempfile.TemporaryDirectory() as temp:
            manifest = json.load(archive.extractfile('manifest.json'))
            db_path = Path(temp) / 'cosecre.db'
            with archive.extractfile('cosecre.db') as src, db_path.open('wb') as dest:
                shutil.copyfileobj(src, dest)
            with sqlite3.connect(db_path) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            for name, size in manifest['files'].items():
                if archive.getmember(name).size != size:
                    raise RuntimeError(f'Archive file size mismatch: {name}')
        partial.rename(output)
        output.with_suffix('.gz.sha256').write_text(f'{checksum}  {output.name}\n')
        print(f'Verified backup: {output}', flush=True)
        if manifest['missing_upload_ids']:
            print('Warning: source files already missing for upload IDs: '
                  + str(manifest['missing_upload_ids']))
    finally:
        try:
            fly('ssh', 'console', '--machine', machine, '-C',
                shlex.join(['/app/hub/.venv/bin/python', script, '--cleanup', token]))
        except subprocess.CalledProcessError:
            print(f'Warning: temporary backup remains on Fly at /data/.backup-{token}',
                  file=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] in {'--remote', '--cleanup'}:
        os.umask(0o077)
        remote(sys.argv[2], cleanup=sys.argv[1] == '--cleanup')
    else:
        main()
