#!/usr/bin/env python3
"""Bounded follow-up: valid live configurations and an authority-field fingerprint probe."""
import argparse
import hashlib
import http.client
import json
import pathlib
import shutil
import socket
import sqlite3
import subprocess
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--evidence', required=True, type=pathlib.Path)
    ap.add_argument('--output', required=True, type=pathlib.Path)
    ap.add_argument('--port', default=19876, type=int)
    a = ap.parse_args()
    root = a.evidence.resolve()
    out = a.output.resolve()
    repo = pathlib.Path(__file__).resolve().parents[3]
    if out.exists() or out.is_relative_to(repo):
        ap.error('output must be new and outside repository')
    out.mkdir(parents=True)
    checks = []

    def record(name, actual, expected):
        checks.append(dict(name=name, actual=actual, expected=expected, passed=actual == expected))
        (out / 'checks.json').write_text(json.dumps(checks, indent=2))

    def run(name, args, config=None):
        env = dict(PATH='/usr/bin:/bin', LISTEN_HOST='127.0.0.1', PORT=str(a.port),
                   DB_PATH=str(out / 'must-not-open.db'))
        env.update(config or {})
        p = subprocess.run([str(x) for x in args], cwd=out, env=env, capture_output=True, timeout=8)
        (out / (name + '.json')).write_text(json.dumps(dict(argv=[str(x) for x in args], env=env,
            exit=p.returncode, stdout=p.stdout.decode(), stderr=p.stderr.decode()), indent=2))
        return p

    embedding = dict(EMBEDDING_PROVIDER='http', EMBEDDING_BASE_URL='http://127.0.0.1:9/v1',
                     EMBEDDING_MODEL='synthetic', EMBEDDING_MODEL_ID='synthetic', EMBEDDING_DIMENSIONS='64')
    openai = dict(OPENAI_API_KEY='synthetic-not-a-secret', OPENAI_MODEL='synthetic',
                  OPENAI_BASE_URL='http://127.0.0.1:9/v1')
    configs = [dict(openai, AI_PROVIDER='openai'), dict(openai, EXTRACTOR_PROVIDER='openai'), embedding,
               dict(embedding, SEMANTIC_SEARCH='qdrant', QDRANT_URL='http://127.0.0.1:9')]
    for n, cfg in enumerate(configs):
        p = run('valid-live-config-' + str(n), [root / 'server', '-public-demo-artifact', root / 'artifact',
                                               '-public-demo-allow-mechanical'], cfg)
        record('valid provider configuration refused before wiring ' + str(n),
               [p.returncode, 'public demo refuses live providers' in p.stderr.decode()], [1, True])
    record('DB_PATH untouched', (out / 'must-not-open.db').exists(), False)
    # Database-wide file checksum is updated, but the declared domain fingerprint stays frozen.
    # Recommendations drive effective admission and thus public support counts/state.
    changed = out / 'changed-admission'
    shutil.copytree(root / 'artifact', changed)
    with sqlite3.connect(changed / 'demo.db') as db:
        old = db.execute('SELECT unit_id,state FROM knowledge_admission_recommendations ORDER BY unit_id').fetchall()
        db.execute("UPDATE knowledge_admission_recommendations SET state='suppressed'")
        new = db.execute('SELECT unit_id,state FROM knowledge_admission_recommendations ORDER BY unit_id').fetchall()
    (out / 'admission-rows.json').write_text(json.dumps(dict(before=old, after=new), indent=2))
    manifest_path = changed / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['demo.db'] = hashlib.sha256((changed / 'demo.db').read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    p = run('changed-admission-validate', [root / 'prepare', 'validate', '-artifact', changed])
    record('changed admission invalidates unchanged domain fingerprint', p.returncode, 1)
    # Observe the actual production response from each artifact using fresh processes.
    for label, artifact in [('original', root / 'artifact'), ('changed', changed)]:
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', a.port)) == 0:
                raise RuntimeError('port occupied')
        log = (out / (label + '-server.log')).open('wb')
        child = subprocess.Popen([str(root / 'server'), '-public-demo-artifact', str(artifact),
                                  '-public-demo-allow-mechanical'], cwd=out,
                                 env=dict(PATH='/usr/bin:/bin', LISTEN_HOST='127.0.0.1', PORT=str(a.port)),
                                 stdout=log, stderr=subprocess.STDOUT)
        log.close()
        try:
            for _ in range(40):
                if child.poll() is not None:
                    (out / (label + '-startup-exit.txt')).write_text(str(child.returncode))
                    break
                try:
                    c = http.client.HTTPConnection('127.0.0.1', a.port, timeout=2)
                    c.request('GET', '/knowledge-library/concepts')
                    response = c.getresponse()
                    body = response.read()
                    c.close()
                    (out / (label + '-library.json')).write_bytes(body)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('startup timed out')
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=7)
    original = json.loads((out / 'original-library.json').read_text())
    changed_body = out / 'changed-library.json'
    if changed_body.exists():
        modified = json.loads(changed_body.read_text())
        diff = []
        for x, y in zip(original['results'], modified['results']):
            if x != y:
                diff.append(dict(id=x['concept']['id'], before=x, after=y))
        (out / 'changed-public-results.json').write_text(json.dumps(diff, indent=2))
    with socket.socket() as s:
        record('owned listener closed', s.connect_ex(('127.0.0.1', a.port)) != 0, True)
    print(json.dumps(dict(pass_count=sum(x['passed'] for x in checks), fail_count=sum(not x['passed'] for x in checks))))
    return int(any(not x['passed'] for x in checks))


if __name__ == '__main__':
    raise SystemExit(main())
