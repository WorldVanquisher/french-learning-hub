"""Isolated FLH-016 checks. Run from repository root; Docker access required."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path.cwd()
RUN = Path(tempfile.mkdtemp(prefix='flh-016-'))
SRC = RUN / 'source'
SRC.mkdir()
for name in ('cmd', 'internal', 'migrations', 'web'):
    shutil.copytree(ROOT / name, SRC / name, ignore=shutil.ignore_patterns(
        '.env*', '*.db*', '*.sqlite*', '*.pem', '*.key', '*credentials*',
        '*secret*', '.netrc', '.envrc', 'node_modules', 'dist', '*.tsbuildinfo'))
for name in ('Makefile', 'go.mod', 'go.sum', 'Dockerfile', '.dockerignore', 'compose.yaml'):
    shutil.copy2(ROOT / name, SRC / name)
(RUN / 'home').mkdir()
(RUN / 'docker').mkdir()
env = {'PATH': os.environ['PATH'], 'HOME': str(RUN / 'home'),
       'DOCKER_CONFIG': str(RUN / 'docker'), 'GOFLAGS': '-buildvcs=false',
       'GOCACHE': str(RUN / 'gocache'), 'GOMODCACHE': subprocess.check_output(
           ['go', 'env', 'GOMODCACHE'], text=True).strip(),
       'AI_PROVIDER': 'rule-based', 'EXTRACTOR_PROVIDER': 'disabled',
       'EMBEDDING_PROVIDER': 'disabled', 'FLH_UID': str(os.getuid()),
       'FLH_GID': str(os.getgid())}
for name in ('OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'OPENAI_TIMEOUT',
             'EMBEDDING_API_KEY', 'EMBEDDING_MODEL', 'EMBEDDING_BASE_URL',
             'EMBEDDING_TIMEOUT', 'HTTP_READ_TIMEOUT', 'HTTP_WRITE_TIMEOUT'):
    env[name] = ''

def run(args, check=True, extra=None, cwd=SRC):
    result = subprocess.run(args, cwd=cwd, env=env | (extra or {}),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with (RUN / 'commands.log').open('a') as log:
        log.write(f'{args!r}\nexit={result.returncode}\n{result.stdout}\n')
    if check and result.returncode:
        raise RuntimeError(f'{args!r}: {result.stdout}')
    return result

text = (ROOT / 'docs/RELEASE.md').read_text()
def block(section):
    part = text.split('## ' + section + '\n', 1)[1].split('\n## ', 1)[0]
    return re.search(r'```bash\n(.*?)```', part, re.S).group(1)

# Execute documented blocks; substitute only fixture paths and Compose transport.
def documented(section, active, backup, source=None, compose='true'):
    script = block(section).replace('docker compose', compose)
    script = script.replace('active=./data/release', 'active="$TEST_ACTIVE"')
    script = re.sub(r'^backup=.*$', 'backup="$TEST_BACKUP"', script, flags=re.M)
    script = script.replace('source_db=./data/app.db', 'source_db="$TEST_SOURCE"')
    return run(['bash', '-c', script], check=False, extra={
        'TEST_ACTIVE': str(active), 'TEST_BACKUP': str(backup),
        'TEST_SOURCE': str(source or ''), 'backup': str(backup)})

print(f'RUN_DIR={RUN}', flush=True)
# Fake nested daily layout; no real data directory is accessed.
fake = SRC / 'data'
fake.mkdir()
for name in ('release', 'local-trial', 'flh-synthetic-demo', 'backups'):
    (fake / name).mkdir()
    (fake / name / 'unrelated.db').write_text('CANARY')
run(['sqlite3', str(fake / 'app.db'), "CREATE TABLE marker(v); INSERT INTO marker VALUES('daily');"])
migration = RUN / 'daily-backup'
assert documented('Migrate the daily database', fake / 'release', migration, fake / 'app.db').returncode == 0
assert sorted(p.name for p in migration.iterdir()) == ['SHA256SUMS', 'app.db']
assert run(['sqlite3', str(migration / 'app.db'), 'SELECT v FROM marker;']).stdout.strip() == 'daily'
# Missing-copy and corrupt-check failures must stop before Compose start.
assert documented('Migrate the daily database', fake / 'release', RUN / 'missing-backup', RUN / 'missing.db').returncode != 0
bad = RUN / 'bad.db'
bad.write_text('not sqlite')
assert documented('Migrate the daily database', fake / 'release', RUN / 'corrupt-backup', bad).returncode != 0
# Exit-zero/non-ok SQLite is insufficient; inject it without touching real tools.
bin_dir = RUN / 'fake-bin'
bin_dir.mkdir()
(bin_dir / 'sqlite3').write_text('#!/bin/sh\necho "*** integrity error ***"\nexit 0\n')
(bin_dir / 'sqlite3').chmod(0o700)
real_path = env['PATH']
env['PATH'] = str(bin_dir) + ':' + real_path
assert documented('Migrate the daily database', fake / 'release', RUN / 'non-ok-backup', fake / 'app.db').returncode != 0
env['PATH'] = real_path
# Applicable WAL/SHM files: terminate the synthetic writer without checkpointing.
run(['python3', '-c', "import sqlite3,os; c=sqlite3.connect('" + str(fake / 'app.db') + "'); c.execute('PRAGMA journal_mode=WAL'); c.execute(\"INSERT INTO marker VALUES('wal')\"); c.commit(); os._exit(0)"])
wal_backup = RUN / 'wal-backup'
assert (fake / 'app.db-wal').exists() and (fake / 'app.db-shm').exists()
assert documented('Migrate the daily database', fake / 'release', wal_backup, fake / 'app.db').returncode == 0
assert sorted(p.name for p in wal_backup.iterdir()) == ['SHA256SUMS', 'app.db', 'app.db-shm', 'app.db-wal']
assert run(['sqlite3', '-readonly', str(wal_backup / 'app.db'), 'SELECT v FROM marker ORDER BY v;']).stdout.strip().splitlines() == ['daily', 'wal']
# Restore checksum, copy, and non-ok failures leave the active directory untouched.
for failure in ('checksum', 'copy', 'non-ok'):
    fixture = RUN / ('restore-' + failure)
    fixture.mkdir(mode=0o700)
    (fixture / 'preserved').write_text('old')
    bad_backup = RUN / ('backup-' + failure)
    shutil.copytree(migration, bad_backup)
    if failure == 'checksum':
        (bad_backup / 'app.db').write_text('tampered')
    elif failure == 'copy':
        (bad_backup / 'app.db').unlink()
        (bad_backup / 'SHA256SUMS').write_text('')
        # A stub checksum success isolates the subsequent copy failure.
        (bin_dir / 'sha256sum').write_text('#!/bin/sh\nexit 0\n')
        (bin_dir / 'sha256sum').chmod(0o700)
    env['PATH'] = str(bin_dir) + ':' + real_path if failure != 'checksum' else real_path
    assert documented('Restore', fixture, bad_backup).returncode != 0
    assert (fixture / 'preserved').read_text() == 'old'
    assert not list(RUN.glob(fixture.name + '.before-restore-*'))
    (bin_dir / 'sha256sum').unlink(missing_ok=True)
env['PATH'] = real_path
print('WAL/SHM migration and restore checksum/copy/non-ok failure checks PASS', flush=True)
print('Daily file-only migration and copy/corrupt/non-ok failure checks PASS', flush=True)

# Controlled build-only failure injection: all preceding checks stubbed; real make recipe.
(bin_dir / 'gofmt').write_text('#!/bin/sh\nexit 0\n')
(bin_dir / 'npm').write_text('#!/bin/sh\necho npm >> "$CALL_LOG"\nexit 0\n')
(bin_dir / 'go').write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
if [ "$1" = build ]; then
  mkdir -p "$(dirname "$3")"
  touch "$3"
  case "$*" in *"$FAIL_TARGET"*) exit 71;; esac
fi
exit 0
''')
for p in bin_dir.iterdir():
    p.chmod(0o700)
for target in ('./cmd/server', './cmd/capture'):
    tmp = RUN / ('tmp-' + target.rsplit('/', 1)[1])
    tmp.mkdir()
    calls = RUN / (tmp.name + '.calls')
    result = run(['make', 'verify'], check=False, extra={
        'PATH': str(bin_dir) + ':' + real_path, 'TMPDIR': str(tmp),
        'FAIL_TARGET': target, 'CALL_LOG': str(calls)})
    assert result.returncode != 0 and not list(tmp.iterdir())
    assert 'npm' not in calls.read_text()
    if target.endswith('server'):
        assert './cmd/capture' not in calls.read_text()
print('Both executable failure paths and temporary cleanup PASS', flush=True)
if '--files-only' in __import__('sys').argv:
    print('File-only checks complete at', RUN, flush=True)
    raise SystemExit(0)
run(['npm', 'ci'], cwd=SRC / 'web')
run(['make', 'verify'])
print('Real make verify PASS', flush=True)

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    env['FLH_HOST_PORT'] = str(sock.getsockname()[1])
project = RUN.name
image = 'french-learning-hub:' + project
override = RUN / 'override.yaml'
override.write_text(f'services:\n  app:\n    image: {image}\n')
compose = ['docker', 'compose', '--env-file', '/dev/null', '-p', project,
           '-f', str(SRC / 'compose.yaml'), '-f', str(override)]
active = SRC / 'data/release'
# Remove synthetic canary only, before Docker starts.
(active / 'unrelated.db').unlink()
active.chmod(0o700)
base = 'http://127.0.0.1:' + env['FLH_HOST_PORT']
def ready():
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + '/readyz', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError('not ready')
def add(value):
    req = urllib.request.Request(base + '/entries', data=json.dumps({
        'original_input': value, 'original_context': 'FLH-016 synthetic'}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        assert response.status == 201

def values():
    with urllib.request.urlopen(base + '/entries') as response:
        data = json.load(response)
    if isinstance(data, dict):
        data = data['entries']
    return sorted(item['original_input'] for item in data)

try:
    run(compose + ['up', '-d', '--build'])
    ready()
    add('A')
    backup = RUN / 'release-backup'
    import shlex
    command = ' '.join(shlex.quote(x) for x in compose)
    assert documented('Backup', active, backup, compose=command).returncode == 0
    ready()
    add('B')
    run(compose + ['stop'])
    transient = RUN / 'transient'
    shutil.copytree(backup, transient)
    run(compose + ['up', '-d'], extra={'FLH_DATA_DIR': str(transient)})
    ready()
    assert values() == ['A']
    add('C')
    assert values() == ['A', 'C']
    run(compose + ['up', '-d'])
    ready()
    assert values() == ['A', 'B']
    print('BR1 reproduced: transient A/C reverted to A/B on plain up', flush=True)
    assert documented('Restore', active, backup, compose=command).returncode == 0
    ready()
    assert values() == ['A']
    add('C')
    prior = list(active.parent.glob('release.before-restore-*'))
    assert len(prior) == 1
    assert run(['sqlite3', str(prior[0] / 'app.db'), 'SELECT original_input FROM learning_entries ORDER BY original_input;']).stdout.strip().splitlines() == ['A', 'B']
    for args in (['down'], ['up', '-d'], ['up', '-d', '--build', '--force-recreate']):
        run(compose + args)
        if args[0] == 'up':
            ready()
            assert values() == ['A', 'C']
            container = run(compose + ['ps', '-q', 'app']).stdout.strip()
            mounts = json.loads(run(['docker', 'inspect', '--format', '{{json .Mounts}}', container]).stdout)
            assert any(m['Source'] == str(active) and m['Destination'] == '/data' for m in mounts)
    print('Durable restore A/C survives down/up and up --build recreation; old A/B preserved PASS', flush=True)
finally:
    run(compose + ['down'], check=False)
print('All FLH-016 checks PASS; logs/source/databases retained at', RUN, flush=True)
