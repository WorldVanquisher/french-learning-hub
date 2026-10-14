#!/usr/bin/env python3
"""Independent FLH-074 mechanical acceptance. No downloads or external endpoints."""
import argparse
import collections
import hashlib
import http.client
import json
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('server', 'prepare', 'artifact', 'web', 'output'):
        ap.add_argument('--' + key, required=True, type=pathlib.Path)
    ap.add_argument('--port', type=int, default=19874)
    a = ap.parse_args()
    repo = pathlib.Path(__file__).resolve().parents[3]
    for key in ('server', 'prepare', 'artifact', 'web', 'output'):
        setattr(a, key, getattr(a, key).resolve())
    if a.output.is_relative_to(repo) or a.output.exists():
        ap.error('output must be a new directory outside the repository')
    a.output.mkdir(parents=True)
    checks, requests, commands, processes = [], [], [], []

    def check(name, actual, expected=True):
        passed = actual == expected
        def safe(x):
            if isinstance(x, bytes):
                return x.decode('utf-8', errors='replace')
            if isinstance(x, set):
                return sorted(x)
            return x
        checks.append(dict(name=name, actual=safe(actual), expected=safe(expected), passed=passed))
        save(a.output / 'checks.json', checks)

    def env(port):
        return dict(PATH='/usr/bin:/bin', LISTEN_HOST='127.0.0.1', PORT=str(port),
                    DB_PATH=str(a.output / 'normal.db'))

    def command(name, args, extra=None):
        e = env(a.port)
        e.update(extra or {})
        p = subprocess.run([str(x) for x in args], cwd=a.output, env=e,
                           capture_output=True, timeout=10)
        (a.output / (name + '.stdout')).write_bytes(p.stdout)
        (a.output / (name + '.stderr')).write_bytes(p.stderr)
        commands.append(dict(name=name, argv=[str(x) for x in args], env=e, exit=p.returncode))
        save(a.output / 'commands.json', commands)
        return p.returncode

    def req(path, expected=None, method='GET', headers=None, port=None, body=None):
        c = http.client.HTTPConnection('127.0.0.1', port or a.port, timeout=3)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        record = dict(method=method, path=path, headers=headers or {}, status=r.status,
                      response_headers=dict(r.getheaders()), body=body.decode('utf-8', errors='replace'))
        requests.append(record)
        with (a.output / 'http.jsonl').open('a') as f:
            f.write(json.dumps(record) + '\n')
        c.close()
        if expected is not None:
            check(f'{method} {path} {headers or {}}', r.status, expected)
        return r.status, body

    def info():
        return json.loads(req('/knowledge-library/demo', 200)[1])

    def snapshot():
        with sqlite3.connect('file:' + str(a.artifact / 'demo.db') + '?mode=ro&immutable=1', uri=True) as db:
            dump = '\n'.join(db.iterdump())
        return dict(files={p.name: digest(p) for p in sorted(a.artifact.iterdir()) if p.is_file()},
                    domain_dump_sha256=hashlib.sha256(dump.encode()).hexdigest(),
                    wal=(a.artifact / 'demo.db-wal').exists(), shm=(a.artifact / 'demo.db-shm').exists())

    def start(name, normal=False):
        port = a.port + int(normal)
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('occupied port: ' + str(port))
        args = [str(a.server), '-web-dir', str(a.web)]
        if not normal:
            args += ['-public-demo-artifact', str(a.artifact), '-public-demo-allow-mechanical']
        log = (a.output / (name + '.log')).open('wb')
        p = subprocess.Popen(args, cwd=a.output, env=env(port), stdout=log, stderr=subprocess.STDOUT)
        log.close()
        processes.append(p)
        for _ in range(50):
            if p.poll() is not None:
                raise RuntimeError(name + ' exited early')
            try:
                if req('/readyz', port=port)[0] == 200:
                    return p
            except OSError:
                pass
            time.sleep(.1)
        raise RuntimeError(name + ' readiness timed out')

    def stop(p):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=7)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2)
                check('graceful shutdown', False)

    try:
        base_args = [a.server, '-public-demo-artifact', a.artifact]
        check('mechanical startup requires opt-in', command('no-mechanical-flag', base_args) != 0)
        configurations = [dict(AI_PROVIDER='openai'), dict(EXTRACTOR_PROVIDER='openai'),
                          dict(EMBEDDING_PROVIDER='http', EMBEDDING_BASE_URL='http://127.0.0.1:9/v1',
                               EMBEDDING_MODEL='synthetic', EMBEDDING_MODEL_ID='synthetic', EMBEDDING_DIMENSIONS='64'),
                          dict(SEMANTIC_SEARCH='qdrant')]
        for i, cfg in enumerate(configurations):
            check('live config startup refused ' + str(i),
                  command('provider-' + str(i), base_args + ['-public-demo-allow-mechanical'], cfg) != 0)
        check('flag alone refused', command('flag-alone', [a.server, '-public-demo-allow-mechanical']) != 0)
        check('valid artifact', command('valid', [a.prepare, 'validate', '-artifact', a.artifact]), 0)
        check('mechanical release blocked', command('release', [a.prepare, 'validate', '-artifact', a.artifact, '-release']), 3)
        before = snapshot()
        save(a.output / 'before.json', before)
        p = start('demo')
        i0 = info()
        check('mechanical synthetic API label', (i0['data'], i0['artifact']['vector_source'], i0['artifact']['real_model']),
              ('synthetic', 'mechanical-test', False))
        routes = re.findall(r'mux.HandleFunc\("(\w+) ([^" ]+)"', (repo / 'internal/transport/http/handler.go').read_text())
        save(a.output / 'enumerated-routes.json', routes)
        allowed = {'/healthz', '/readyz', '/knowledge-library/concepts',
                   '/knowledge-library/concepts/{id}', '/knowledge-library/units/{id}/source'}
        for prefix in ('', '/api'):
            for method, path in routes:
                path = re.sub(r'\{[^}]+\}', '1', path)
                original = next((r for m, r in routes if re.sub(r'\{[^}]+\}', '1', r) == path and m == method), '')
                expected = 405 if method != 'GET' else 200 if original in allowed else 404
                req(prefix + path, expected, method)
            # Every method and every registered path: routing cannot reach nil write services.
            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'):
                for path in sorted({re.sub(r'\{[^}]+\}', '1', r) for _, r in routes}):
                    req(prefix + path, 405, method)
            for path in ('/knowledge-library/demo/semantic-search', '/knowledge-library/demo/hybrid-search'):
                for query, status in [('q=arbitrary', 400), ('preset=miss-someone&q=x', 400),
                                      ('preset=miss-someone&preset=subjunctive', 400),
                                      ('preset=miss-someone&unknown=1', 400), ('preset=unknown', 404),
                                      ('preset=miss-someone&limit=1&limit=2', 400),
                                      ('preset=miss-someone&state=all&state=active', 400),
                                      ('preset=miss-someone&limit=0', 400), ('preset=miss-someone&bad=%zz', 400),
                                      ('preset=miss-someone;bad=1', 400)]:
                    req(prefix + path + '?' + query, status)
            for path in ('//knowledge-library/demo', '/knowledge-library/../knowledge-library/demo',
                         '/knowledge-library/demo/', '/knowledge-library%2fdemo', '/%61pi/knowledge-library/demo',
                         '/knowledge-library/demo%00', '/api', '/assets/', '/demo.db', '/manifest.json',
                         '/vectors.json', '/fixtures.json', '/.env', '/assets/../demo.db',
                         '/assets/%2e%2e/demo.db', '/assets/%252e%252e/demo.db', '/api/assets/index.js'):
                req(prefix + path, 404)
        check('denied requests made zero vector calls', info()['counters'], i0['counters'])
        check('denied requests preserved all DB state', snapshot(), before)
        req('/knowledge-library/demo', 403, headers={'Host': 'foreign.invalid'})
        req('/entries', 403, 'POST', {'Origin': 'https://foreign.invalid', 'Content-Type': 'application/json'})
        req('/entries', 405, 'OPTIONS', {'Origin': 'https://foreign.invalid'})
        req('/knowledge-library/demo', 403, headers={'Host': 'foreign.invalid', 'X-Forwarded-Host': 'localhost'})
        # Existing keyword parsing is intentionally unchanged: unknown/duplicate parameters use first value.
        keyword = req('/knowledge-library/concepts?q=subj', 200)[1]
        check('keyword duplicate/unknown parameter compatibility',
              req('/knowledge-library/concepts?q=subj&q=other&unknown=x', 200)[1], keyword)
        html = req('/', 200)[1].decode()
        assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', html)
        check('JS and CSS built assets present', {pathlib.Path(x).suffix for x in assets}, {'.js', '.css'})
        for path in assets:
            status, body = req(path, 200)
            check('static bytes ' + path, hashlib.sha256(body).hexdigest(), digest(a.web / path.lstrip('/')))
        # A bounded deployment-layout test: no credentials or real unrelated file is read.
        sentinel = a.output / 'unrelated-synthetic.txt'
        sentinel.write_text('FLH074 unrelated synthetic sentinel\n')
        link = a.web / 'assets' / 'flh074-outside.txt'
        link.symlink_to(sentinel)
        try:
            status, body = req('/assets/flh074-outside.txt')
            check('static symlink cannot expose outside web root', status in (403, 404))
        finally:
            link.unlink()
        results = {}
        for preset in i0['presets']:
            for mode in ('semantic', 'hybrid'):
                path = '/knowledge-library/demo/' + mode + '-search?preset=' + preset['id']
                status, body = req(path, 200)
                check('exact preset text ' + path, json.loads(body)['query'], preset['text'])
                results[path] = body.decode()
                check('root/api parity ' + path, req('/api' + path, 200)[1], body)
        req('/knowledge-library/demo', 200, 'HEAD')
        for path in ('/knowledge-library/concepts/1', '/knowledge-library/units/1/source'):
            req(path, 200)
            req('/api' + path, 200)
        end = info()
        check('32 accepted searches = 32 cached lookups, zero refusals', end['counters'],
              dict(preset_vector_lookups=32, refused_vector_lookups=0))
        save(a.output / 'demo-info.json', end)
        check('DB_PATH never opened in demo', not (a.output / 'normal.db').exists())
        check('all reads preserve artifact and domain state', snapshot(), before)
        stop(p)
        p = start('demo-restart')
        check('restart identity unchanged', info()['artifact'], i0['artifact'])
        for path, body in results.items():
            check('restart result ' + path, req(path, 200)[1].decode(), body)
        save(a.output / 'restart-info.json', info())
        stop(p)
        normal = start('normal', True)
        req('/entries', 200, port=a.port + 1)
        req('/entries', 201, 'POST', {'Content-Type': 'application/json'}, port=a.port + 1,
            body=json.dumps(dict(original_input='FLH074 synthetic normal mode check', original_context='Synthetic acceptance only')))
        for prefix in ('', '/api'):
            req(prefix + '/knowledge-library/demo', 404, port=a.port + 1)
            req(prefix + '/knowledge-library/semantic-search?q=test', 503, port=a.port + 1)
            req(prefix + '/knowledge-library/concepts', 200, port=a.port + 1)
        check('normal mode creates its separate DB', (a.output / 'normal.db').exists())
        stop(normal)
        # Independent deeper mutations rehash changed files to reach structural checks.
        mutation_names = ['missing-manifest', 'missing-db', 'missing-vectors', 'missing-fixtures',
                          'corrupt-manifest', 'corrupt-vectors', 'db-bytes', 'model-id', 'query-repr', 'doc-repr',
                          'wrong-dim', 'zero-vector', 'nonfinite-vector', 'overflow-vector', 'missing-concept',
                          'foreign-concept', 'duplicate-concept', 'document-hash', 'preset-text', 'preset-hash',
                          'duplicate-preset', 'too-many-presets', 'empty-presets', 'fingerprint', 'db-domain', 'db-ledger']
        for name in mutation_names:
            dest = a.output / 'mutations' / name
            shutil.copytree(a.artifact, dest)
            m = json.loads((dest / 'manifest.json').read_text())
            v = json.loads((dest / 'vectors.json').read_text())
            if name.startswith('missing-') and name not in ('missing-concept',):
                (dest / {'missing-manifest': 'manifest.json', 'missing-db': 'demo.db',
                         'missing-vectors': 'vectors.json', 'missing-fixtures': 'fixtures.json'}[name]).unlink()
            elif name == 'corrupt-manifest': (dest / 'manifest.json').write_text('{')
            elif name == 'db-bytes':
                with (dest / 'demo.db').open('ab') as f: f.write(b'changed')
            else:
                if name == 'model-id': m['vectors']['model_id'] += '-changed'
                if name == 'query-repr': m['vectors']['query_representation'] = 'concept_search_query_v1'
                if name == 'doc-repr': m['vectors']['document_representation'] = 'wrong'
                if name == 'wrong-dim': v['presets'][0]['vector'].pop()
                if name == 'zero-vector': v['documents'][0]['vector'] = [0] * 64
                if name == 'nonfinite-vector': v['documents'][0]['vector'][0] = float('nan')
                if name == 'overflow-vector': v['documents'][0]['vector'][0] = 1e300
                if name == 'missing-concept': v['documents'].pop()
                if name == 'foreign-concept': v['documents'][0]['concept_id'] = 9999
                if name == 'duplicate-concept': v['documents'].append(v['documents'][0])
                if name == 'document-hash': v['documents'][0]['content_hash'] = '0' * 64
                if name == 'preset-text': v['presets'][0]['text'] = 'different text'
                if name == 'preset-hash': v['presets'][0]['envelope_sha256'] = '0' * 64
                if name == 'duplicate-preset': v['presets'].append(v['presets'][0])
                if name == 'too-many-presets': v['presets'] *= 2
                if name == 'empty-presets': v['presets'] = []
                if name == 'fingerprint': m['domain_fingerprint']['sha256'] = '0' * 64
                if name in ('db-domain', 'db-ledger'):
                    with sqlite3.connect(dest / 'demo.db') as db:
                        db.execute("UPDATE learning_entries SET original_input='synthetic altered' WHERE id=1" if name == 'db-domain'
                                   else 'DELETE FROM schema_migrations WHERE name=(SELECT min(name) FROM schema_migrations)')
                    m['files']['demo.db'] = digest(dest / 'demo.db')
                (dest / 'vectors.json').write_text('{' if name == 'corrupt-vectors' else json.dumps(v))
                m['files']['vectors.json'] = digest(dest / 'vectors.json')
                save(dest / 'manifest.json', m)
            check('artifact rejected ' + name, command('mutation-' + name,
                  [a.prepare, 'validate', '-artifact', dest]), 1)
        check('original artifact still validates', command('valid-after', [a.prepare, 'validate', '-artifact', a.artifact]), 0)
        check('original artifact preserved after mutations', snapshot(), before)
    finally:
        for p in processes:
            stop(p)
        cleanup = dict(children=[dict(pid=p.pid, exit=p.poll()) for p in processes])
        for port in (a.port, a.port + 1):
            with socket.socket() as s:
                cleanup[str(port)] = 'closed' if s.connect_ex(('127.0.0.1', port)) != 0 else 'LISTENING'
        save(a.output / 'cleanup.json', cleanup)
        counts = collections.Counter('pass' if x['passed'] else 'fail' for x in checks)
        save(a.output / 'summary.json', dict(counts=counts, requests=len(requests), commands=len(commands),
                                          failures=[x for x in checks if not x['passed']]))
        print(json.dumps(dict(counts=counts, requests=len(requests), output=str(a.output))))
    return int(any(not x['passed'] for x in checks))


if __name__ == '__main__':
    raise SystemExit(main())
