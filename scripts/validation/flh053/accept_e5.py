#!/usr/bin/env python3
"""FLH-056: independent, stdlib-only E5 contract acceptance. Default offline.
Live mode is one-shot: reserve budget BEFORE POSTs, never retry a run.
"""
import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / 'tools/embedding/e5'
sys.path.insert(0, str(SERVICE))
from flh_e5 import contract, manifest
from flh_e5.service import EmbeddingService, EmbeddingHTTPServer, Limits, ApiError
from tests.fakes import FakeEncoder, fake_vector

DEPLOYMENT = 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/dd0889c6f1869f7f'


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(base, name, out):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(base.removesuffix('/v1') + '/' + name, timeout=5) as r:
        raw = r.read((1 << 20) + 1)
        assert r.status == 200 and len(raw) <= 1 << 20
    (out / (name + '.json')).write_bytes(raw)
    return json.loads(raw)


def identity(m):
    v = m['vector_defining']
    # Independently reproduce manifest's ASCII canonicalization and code hash.
    sha = hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
    h = hashlib.sha256()
    for name in v['adapter']['code_files']:
        assert name in ('contract.py', 'encoder.py', 'manifest.py')
        raw = (SERVICE / 'flh_e5' / name).read_bytes().replace(b'\r\n', b'\n')
        h.update(name.encode() + b'\0' + str(len(raw)).encode() + b'\0' + raw)
    assert sha == m['manifest_sha256']
    assert h.hexdigest() == v['adapter']['code_sha256']
    assert m['deployment_id'] == DEPLOYMENT
    assert v['model']['revision'] == manifest.REVISION
    assert set(v['model']['files']) == set(manifest.PINNED_FILES)
    for name, (size, kind, digest) in manifest.PINNED_FILES.items():
        actual = v['model']['files'][name]
        assert actual['size'] == size and actual[kind] == digest
    assert v['inference']['dtype'] == 'float16' and v['inference']['dimensions'] == 768
    assert v['adapter']['prefixes'] == {'query': 'query: ', 'passage': 'passage: '}
    return {'manifest_sha256': sha, 'local_vector_code_sha256': h.hexdigest()}


def invoke(binary, base, model, payload, out, cg=False):
    reqs, positions = (5, 11) if payload == 'rendered' else (1, 1)
    cmd = [str(binary), '-allow-real-endpoint', '-base-url', base, '-model', model,
           '-dimensions', '768', '-payload', payload, '-max-requests', str(reqs),
           '-max-inputs', str(positions), '-max-input-bytes', '2048',
           '-request-timeout', '5s', '-timeout', '30s', '-atol', '0.00001',
           '-rtol', '0.0001', '-require-unit-norm', '-norm-tolerance', '0.001', '-out', str(out)]
    if cg:
        cmd.append('-allow-tailscale-cgnat')
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    save(out.parent / (out.name + '-command.json'), {'command': cmd, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
    return p.returncode, json.loads((out / 'report.json').read_text())


def check_positive(code, report):
    assert code == 0 and report['state'] == 'passed', 'positive vector contract failed; see retained report'
    assert len(report['wire_calls']) == 5 and report['submitted_input_positions'] == 11
    for w in report['wire_calls']:
        assert w['http_status'] == 200 and w['path'] == '/v1/embeddings'
        assert w['response_model_matches']
        assert w['response_indices'] == list(range(len(w['input_sha256'])))
    # Independent norm/repeat reconstruction (does not accept subprocess exit alone).
    seen, roles = {}, {'query': 0, 'passage': 0}
    max_diff = 0.0
    for b, result in zip(report['synthetic_inputs'], report['batches'], strict=True):
        assert result['state'] == 'passed'
        for text, vector in zip(b['inputs'], result['ordered_vectors'], strict=True):
            assert len(vector) == 768 and all(math.isfinite(x) for x in vector)
            norm = math.sqrt(math.fsum(x*x for x in vector))
            assert abs(norm-1) <= 0.001 and norm > 0
            role = 'passage' if json.loads(text)['type'] == 'concept' else 'query'
            roles[role] += 1
            if text in seen:
                for a, z in zip(seen[text], vector, strict=True):
                    max_diff = max(max_diff, abs(a-z))
                    assert abs(a-z) <= 1e-5 + 1e-4*max(abs(a),abs(z))
            seen[text] = vector
    assert roles == {'query': 4, 'passage': 7}
    return {'accepted_positions': 11, 'roles': roles, 'max_repeat_coordinate_difference': max_diff}


def offline(binary, out):
    golden = json.loads((SERVICE / 'tests/golden_inputs.json').read_text())
    evidence = {'golden_accepted': [], 'golden_rejected': [], 'malformed_vectors': []}
    for item in golden['accepted']:
        adapted = contract.adapt(item['input'])
        assert adapted.role == item['role'] and adapted.model_text == item['model_text']
        evidence['golden_accepted'].append(item['name'])
    for item in golden['rejected']:
        try:
            contract.adapt(item['input'])
        except contract.InputRejected:
            evidence['golden_rejected'].append(item['name'])
        else:
            raise AssertionError(item['name'])
    encoder = FakeEncoder()
    svc = EmbeddingService(lambda: encoder, lambda e: {'deployment_id': 'fake-e5-plumbing-only'}, Limits())
    svc.load()
    server = EmbeddingHTTPServer(('127.0.0.1', 0), svc)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}/v1'
        code, report = invoke(binary, base, svc.deployment_id, 'rendered', out/'positive')
        evidence['positive'] = check_positive(code, report)
        for b, result in zip(report['synthetic_inputs'], report['batches'], strict=True):
            for text, vector in zip(b['inputs'], result['ordered_vectors'], strict=True):
                role = 'passage' if json.loads(text)['type'] == 'concept' else 'query'
                expected = fake_vector(role + ': ' + text)
                assert vector == expected, 'prefix or response ordering mismatch'
        for name, model, status, kind in [('raw', svc.deployment_id, 422, 'invalid_input'), ('unknown', 'unknown-deployment', 400, 'unknown_model')]:
            code, r = invoke(binary, base, model, 'raw-negative', out/name)
            assert code == 1 and r['state'] == 'failed' and len(r['wire_calls']) == 1
            assert r['wire_calls'][0]['http_status'] == status and r['wire_calls'][0]['contract_error_type'] == kind
            evidence[name] = {'exit': code, 'status': status, 'type': kind}
        assert svc.counters.snapshot()['inputs_by_role'] == {'query': 4, 'passage': 7}
        evidence['counters'] = svc.counters.snapshot()
        assert len(encoder.batches) == 6  # warmup + 5; negative requests never encoded
        for failure in ('oom', 'error', 'nan', 'unnormalized', 'short', 'count'):
            encoder.fail = failure
            before = len(encoder.batches)
            try:
                svc.embed(json.dumps({'model': svc.deployment_id, 'input': [golden['accepted'][0]['input']]}).encode())
            except ApiError as e:
                assert e.status == (503 if failure == 'oom' else 500)
                assert len(encoder.batches) == before + 1
                evidence['malformed_vectors'].append({'failure': failure, 'actual_status': e.status, 'type': e.kind, 'attempts': 1})
            else:
                raise AssertionError(failure)
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        svc.close()
    evidence['cleanup'] = {'server_thread_stopped': not thread.is_alive(), 'fake_encoder_closed': encoder.closed}
    assert not thread.is_alive() and encoder.closed
    save(out/'independent.json', evidence)


def live(binary, out, base, manifest_snapshot):
    ledger = Path('/tmp/flh056-live-post-reservation.json')
    if ledger.exists():
        raise ValueError('live budget already reserved; do not repeat requests')
    u = urllib.parse.urlsplit(base)
    assert u.scheme == 'http' and not u.username and not u.password and not u.query and not u.fragment
    assert ipaddress.ip_address(u.hostname) in ipaddress.ip_network('100.64.0.0/10')
    assert base == 'http://100.118.109.6:8765/v1', 'only the supplied endpoint is authorized'
    evidence = {'requests_budget': 8, 'positions_budget': 24, 'reserved_requests': 7, 'reserved_positions': 13}
    ready = get(base, 'readyz', out)
    if manifest_snapshot:
        raw = manifest_snapshot.read_bytes()
        (out/'manifest.json').write_bytes(raw)
        m = json.loads(raw)
    else:
        m = get(base, 'manifest', out)
    evidence['identity'] = identity(m)
    assert ready['ready'] and ready['deployment_id'] == DEPLOYMENT
    before_dir = out/'before'
    before_dir.mkdir()
    before_metrics = get(base, 'metrics', before_dir)
    assert before_metrics['deployment_id'] == DEPLOYMENT and before_metrics['state'] == 'ready'
    before = before_metrics['counters']
    # Permanent task-local one-shot guard: even failed attempts may have reached the server.
    save(ledger, evidence)
    reports = []
    code, positive = invoke(binary, base, DEPLOYMENT, 'rendered', out/'positive', True)
    reports.append(positive)
    try:
        evidence['positive'] = check_positive(code, positive)
    except AssertionError as e:
        evidence['positive_failure'] = str(e)
    # Each deliberate negative is one request, even after a positive consistency failure.
    for name, model, status, kind in [('unknown', DEPLOYMENT+'-unknown', 400, 'unknown_model'), ('raw', DEPLOYMENT, 422, 'invalid_input')]:
        code, r = invoke(binary, base, model, 'raw-negative', out/name, True)
        reports.append(r)
        actual = r['wire_calls'][0]
        evidence[name] = {'expected_exit': 1, 'actual_exit': code, 'expected_status': status, 'actual_status': actual['http_status'], 'expected_type': kind, 'actual_type': actual.get('contract_error_type')}
    after_dir = out/'after'
    after_dir.mkdir()
    after_metrics = get(base, 'metrics', after_dir)
    assert after_metrics['deployment_id'] == DEPLOYMENT and after_metrics['state'] == 'ready'
    after = after_metrics['counters']
    expected = {'requests_total': sum(len(r['wire_calls']) for r in reports), 'requests_ok': sum(w['http_status']==200 for r in reports for w in r['wire_calls']), 'input_positions': 0, 'computations': 0, 'truncations': 0, 'overlength_inputs': 0, 'inputs_by_role': {'query': 0, 'passage': 0}, 'rejected': {'unknown_model': 1, 'invalid_input': 1}}
    for b, w in zip(positive['synthetic_inputs'], positive['wire_calls']):
        if w['http_status'] == 200:
            expected['computations'] += 1
            expected['input_positions'] += len(b['inputs'])
            for text in b['inputs']:
                role = 'passage' if json.loads(text)['type'] == 'concept' else 'query'
                expected['inputs_by_role'][role] += 1
    actual = {}
    for k, v in expected.items():
        if isinstance(v, dict):
            keys = set(before[k]) | set(after[k]) | set(v)
            actual[k] = {key: after[k].get(key,0)-before[k].get(key,0) for key in keys}
            expected[k] = {key: v.get(key,0) for key in keys}
        else:
            actual[k] = after[k]-before[k]
    evidence['submitted_requests'] = sum(len(r['wire_calls']) for r in reports)
    evidence['submitted_positions'] = sum(r['submitted_input_positions'] for r in reports)
    evidence['counter_delta'] = {'expected': expected, 'actual': actual, 'matches': actual == expected}
    evidence['accepted'] = ('positive_failure' not in evidence and actual == expected and all(evidence[n]['actual_exit']==1 and evidence[n]['actual_status']==evidence[n]['expected_status'] and evidence[n]['actual_type']==evidence[n]['expected_type'] for n in ('unknown','raw')))
    save(out/'independent.json', evidence)
    print(json.dumps(evidence, indent=2))
    return 0 if evidence['accepted'] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--allow-live', action='store_true')
    ap.add_argument('--base', default='')
    ap.add_argument('--manifest-snapshot', type=Path, help='reuse an already retained public manifest; fresh ready/metrics must still match')
    args = ap.parse_args()
    assert args.out.is_absolute() and str(args.out).startswith('/tmp/flh053-')
    assert args.out.parent.resolve() == args.out.parent and not args.out.exists()
    assert args.allow_live or not args.base
    args.out.mkdir(mode=0o700)
    try:
        if args.allow_live:
            return live(args.binary, args.out, args.base, args.manifest_snapshot)
        offline(args.binary, args.out)
        print('offline independent contract checks passed; no model/GPU/quality acceptance')
        return 0
    except Exception as error:
        save(args.out/'failure.json', {'state': 'failed_or_blocked', 'exception_type': type(error).__name__, 'retry': False})
        raise
    finally:
        save(args.out/'artifact-sha256.json', {str(p.relative_to(args.out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.rglob('*')) if p.is_file()})


if __name__ == '__main__':
    sys.exit(main())
