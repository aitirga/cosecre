"""Read RAM usage from the running Fly worker without installing an agent."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess


REMOTE = '''
from pathlib import Path
import json

def fields(path):
    return {key: value.strip() for key, value in
            (line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)}

memory = fields(Path('/proc/meminfo'))
workers = []
for path in Path('/proc').glob('[0-9]*/status'):
    try:
        info = fields(path)
        command = (path.parent / 'cmdline').read_bytes().split(bytes([0]))
        if info['Name'] == 'uvicorn' or b'cosecre_hub.server' in command:
            workers.append({key: info[key] for key in ('Pid', 'VmRSS', 'VmHWM', 'Threads')})
    except FileNotFoundError:
        pass
print(json.dumps({'system': {key: memory[key] for key in ('MemTotal', 'MemAvailable')},
                  'workers': workers}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='cosecre-aitirga')
    args = parser.parse_args()
    machines = json.loads(subprocess.check_output(
        ['flyctl', 'machine', 'list', '--json', '-a', args.app], text=True
    ))
    running = [machine for machine in machines if machine['state'] == 'started']
    if not running:
        raise SystemExit('No running Fly machine; check just status.')
    for machine in running:
        result = subprocess.check_output([
            'flyctl', 'machine', 'exec', machine['id'],
            shlex.join(['/app/hub/.venv/bin/python', '-c', REMOTE]),
            '-a', args.app, '--timeout', '15',
        ], text=True)
        report = json.loads(result)

        def mib(value):
            return f'{int(value.split()[0]) / 1024:.1f} MiB'

        print(f"Machine {machine['id']}: "
              f"{mib(report['system']['MemAvailable'])} available / "
              f"{mib(report['system']['MemTotal'])} total RAM")
        for worker in report['workers']:
            print(f"  Uvicorn PID {worker['Pid']}: RSS {mib(worker['VmRSS'])}, "
                  f"peak {mib(worker['VmHWM'])}, {worker['Threads']} threads")


if __name__ == '__main__':
    main()
