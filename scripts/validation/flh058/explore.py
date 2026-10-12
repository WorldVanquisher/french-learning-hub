#!/usr/bin/env python3
"""FLH-058: prepare offline, then ONE explicitly authorized synthetic E5 run.
Results are exploratory author-proposed unreviewed synthetic judgments,
NOT production policy or independent human ground truth. Small correlated
and author-visible holdout; no tuning/generalization or SAME claim.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
BASE = 'http://100.118.109.6:8765/v1'
MODEL = 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/dd0889c6f1869f7f'
FROZEN = '92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a'
MANIFEST_HASH = 'dd0889c6f1869f7fe3bcaf85e40713b99cd21812342155be9eac55222313bb56'
CODE_HASH = '96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0'
LEDGER = Path('/tmp/flh058-budget-reservation.json')
SCOPE = ['exploratory comparison against author-proposed unreviewed synthetic judgments',
         'NOT production evaluation policy', 'NOT independently collected human ground truth',
         'small correlated author-visible holdout, no tuning/generalization claim',
         'Measured embedding scores do not prove SAME or useful free-text relevance.']
ENV = dict(os.environ, GOCACHE='/tmp/flh049-go-cache', GOPROXY='off', GOSUMDB='off')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def command(out, name, argv, expected=0, extra=None, timeout=90):
    env = dict(ENV, **(extra or {}))
    start = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=timeout)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        code, stdout, stderr = -999, e.stdout or b'', e.stderr or b''
    (out/(name+'-stdout.txt')).write_bytes(stdout)
    (out/(name+'-stderr.txt')).write_bytes(stderr)
    record = {'scope': SCOPE, 'argv': argv, 'expected_exit': expected, 'actual_exit': code,
              'elapsed_seconds': time.monotonic()-start, 'subprocess_deadline_seconds': timeout,
              'go_environment': {k: ENV[k] for k in ('GOCACHE','GOPROXY','GOSUMDB')}}
    save(out/(name+'-command.json'), record)
    return code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def read_endpoint(out):
    result = {}
    for name in ('readyz','manifest','metrics'):
        with opener().open(BASE.removesuffix('/v1')+'/'+name, timeout=5) as response:
            raw = response.read((1<<20)+1)
            assert response.status == 200 and len(raw) <= 1<<20
        (out/(name+'.json')).write_bytes(raw)
        result[name] = json.loads(raw)
    assert result['readyz']['ready'] and result['readyz']['deployment_id'] == MODEL
    assert result['metrics']['state'] == 'ready' and result['metrics']['deployment_id'] == MODEL
    m = result['manifest']; v = m['vector_defining']
    assert m['deployment_id'] == MODEL
    actual = digest(json.dumps(v, sort_keys=True, separators=(',',':'), ensure_ascii=True).encode('ascii'))
    assert actual == m['manifest_sha256'] == MANIFEST_HASH
    assert v['model']['repository'] == 'intfloat/multilingual-e5-base'
    assert v['model']['revision'] == 'd128750597153bb5987e10b1c3493a34e5a4502a'
    assert v['inference']['dimensions'] == 768 and v['inference']['dtype'] == 'float16'
    assert v['inference']['microbatch'] == 8
    assert v['adapter']['convention'] == 'flh_e5_role_prefix_v1'
    assert v['adapter']['prefixes'] == {'query':'query: ', 'passage':'passage: '}
    assert v['adapter']['accepted'] == ['concept_embedding_text_v1/concept->passage','concept_embedding_text_v1/query->query','concept_search_query_v2/query->query']
    h = hashlib.sha256()
    assert v['adapter']['code_files'] == ['contract.py','encoder.py','manifest.py']
    for name in v['adapter']['code_files']:
        raw = (ROOT/'tools/embedding/e5/flh_e5'/name).read_bytes().replace(b'\r\n',b'\n')
        h.update(name.encode()+b'\0'+str(len(raw)).encode()+b'\0'+raw)
    assert h.hexdigest() == v['adapter']['code_sha256'] == CODE_HASH
    return result


def source_snapshot():
    names = ['AGENTS.md', 'go.mod', 'go.sum', 'docs/validation/FLH-055-runner-contract-acceptance.md',
             'docs/validation/FLH-056-live-e5-acceptance.md']
    for directory in ('scripts/validation/flh045','scripts/validation/flh048','tools/embedding/e5/flh_e5'):
        names.extend(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file())
    names.extend(['internal/application/'+n+'.go' for n in ('concept_retrieval','concept_weighted_lexical_retrieval',
        'concept_bm25_retrieval','concept_embedding_retrieval','concept_retrieval_evaluation_service')])
    names.extend(['internal/domain/concept.go','internal/domain/knowledge.go','internal/embedding/http.go',
                  'scripts/validation/flh051/independent_test.go.txt','scripts/validation/flh051/production_bridge.go.txt'])
    return {name: digest((ROOT/name).read_bytes()) for name in sorted(set(names))}


def artifacts(out):
    target = out/'artifact-sha256.json'
    if target.exists():
        raise ValueError('artifact manifest already exists; never overwrite')
    save(target, {str(p.relative_to(out)): digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file()})


def prepare(out):
    assert digest((ROOT/'scripts/validation/flh045/fixture.json').read_bytes()) == FROZEN
    save(out/'source-before.json', source_snapshot())
    assert command(out,'build',['go','build','-o',str(out/'runner'),'./scripts/validation/flh048']) == 0
    assert command(out,'runner-tests',['go','test','-json','-count=1','./scripts/validation/flh048']) == 0
    overlay = {'Replace': {
        str(ROOT/'internal/application/flh058_production_bridge.go'): str(ROOT/'scripts/validation/flh051/production_bridge.go.txt'),
        str(ROOT/'scripts/validation/flh048/flh058_independent_test.go'): str(ROOT/'scripts/validation/flh051/independent_test.go.txt')}}
    save(out/'overlay.json', overlay)
    assert command(out,'parity-label-separation',['go','test','-overlay',str(out/'overlay.json'),'-json','-count=1',
        '-run','^TestFLH051ProductionParityAndEvidence$','./scripts/validation/flh048'], extra={
        'FLH051_FIXTURE':str(ROOT/'scripts/validation/flh045/fixture.json'),'FLH051_GO_EVIDENCE':str(out/'rendered-inputs.json')}) == 0
    inputs = json.loads((out/'rendered-inputs.json').read_text())
    assert inputs['metadata_invariant'] and inputs['production_parity']
    assert len(inputs['provider_batches']) == 56 and all(len(b)==25 for b in inputs['provider_batches'])
    assert command(out,'offline',[str(out/'runner'),'-out',str(out/'offline'),'-timeout','120s',
        '-expect-fixture-sha256',FROZEN]) == 0
    offline = json.loads((out/'offline/report.json').read_text())
    assert offline['report_schema'] == 'flh048_exploratory_retrieval_comparison_v2'
    assert offline['inputs']['fixture_matches_frozen']
    assert source_snapshot() == json.loads((out/'source-before.json').read_text())
    config = {'scope': SCOPE,'endpoint':BASE,'model':MODEL,'dimensions':768,'request_limit':56,'position_limit':1400,
        'overall_timeout':'120s','runner_request_timeout':'10s','forwarder_upstream_timeout_seconds':8,
        'process_timeout_seconds':150,'limit_k':5,'parameters':'unchanged existing Go implementations; no tuning',
        'fixture_sha256':FROZEN,'rendered_capture_sha256':digest((out/'rendered-inputs.json').read_bytes()),
        'rendered_input_stream_sha256':stream_hash(inputs['provider_batches']),
        'runner_inputs':offline['inputs'],'runner_binary_sha256':digest((out/'runner').read_bytes())}
    save(out/'configuration.json',config)
    print('Prepared offline; 56 batches/1400 positions captured, actual production parity and evaluator-label separation verified.')


def stream_hash(batches):
    h = hashlib.sha256()
    for batch in batches:
        for text in batch:
            raw = text.encode('utf-8')
            h.update(len(raw).to_bytes(8,'big')+raw)
    return h.hexdigest()


class Recorder:
    def __init__(self, out, batches):
        self.out,self.batches,self.calls,self.positions = out,batches,[],0
        (out/'wire').mkdir()
        self.abort = False

    def handle(self, handler):
        started = time.monotonic()
        status, raw = 502, b'{"error":{"type":"flh058_forwarding_failure"}}'
        record = {'scope': SCOPE,'attempt':len(self.calls)+1,'upstream_attempts':0}
        try:
            assert not self.abort and handler.path == '/v1/embeddings'
            size = int(handler.headers['Content-Length'])
            assert 0 < size <= 262144 and handler.headers.get('Authorization') is None
            body = handler.rfile.read(size)
            req = json.loads(body)
            assert set(req)=={'model','input'} and req['model']==MODEL
            assert len(self.calls)<56 and self.positions+len(req['input'])<=1400
            assert req['input'] == self.batches[len(self.calls)], 'rendered input mismatch; refuses before upstream'
            for i,text in enumerate(req['input']):
                data = json.loads(text)
                assert len(text.encode())<=4096 and data['representation']=='concept_embedding_text_v1'
                assert data['type']==('query' if i==0 else 'concept')
            record['submitted_positions']=len(req['input'])
            record['input_sha256']=[digest(t.encode()) for t in req['input']]
            record['request_body_sha256']=digest(body)
            self.positions += len(req['input'])
            self.calls.append(record)
            folder = self.out/'wire'/f'{len(self.calls):03d}'
            folder.mkdir()
            (folder/'request.json').write_bytes(body)
            # Exact original body, one upstream POST; no redirects, proxy or retries.
            upstream = urllib.request.Request(BASE+'/embeddings',data=body,headers={'Content-Type':'application/json'},method='POST')
            record['upstream_attempts']=1
            try:
                response = opener().open(upstream,timeout=8)
            except urllib.error.HTTPError as e:
                response = e
            with response:
                status = response.code
                raw = response.read((16<<20)+1)
                assert len(raw)<=16<<20
            (folder/'response.json').write_bytes(raw)
            if status != 200:
                self.abort=True
            record['http_status']=status
            record['response_sha256']=digest(raw)
            record['elapsed_seconds']=time.monotonic()-started
            save(folder/'observation.json',record)
        except Exception as error:
            self.abort=True
            record['exception_type']=type(error).__name__
            record['elapsed_seconds']=time.monotonic()-started
            # Retain failure even if it occurred before a batch was submitted.
            save(self.out/'forwarder-failure.json',record)
        handler.send_response(status)
        handler.send_header('Content-Type','application/json')
        handler.send_header('Content-Length',str(len(raw)))
        handler.end_headers()
        try:
            handler.wfile.write(raw)
        except OSError:
            pass


def run_once(out):
    assert not LEDGER.exists(), 'FLH-058 budget already reserved; no repeat model run authorized'
    assert not (out/'live').exists()
    assert source_snapshot() == json.loads((out/'source-before.json').read_text()), 'source drift since preparation'
    inputs = json.loads((out/'rendered-inputs.json').read_text())
    assert digest((out/'rendered-inputs.json').read_bytes()) == json.loads((out/'configuration.json').read_text())['rendered_capture_sha256']
    before_dir=out/'before'; before_dir.mkdir()
    try:
        before = read_endpoint(before_dir)
    except Exception as error:
        save(out/'blocked-checkpoint.json', {'scope':SCOPE,'state':'BLOCKED','embedding_posts':0,'reason_type':type(error).__name__})
        print('BLOCKED before POSTs; offline preparation retained; no reservation or model request.')
        return 2
    save(LEDGER,{'task':'FLH-058','scope':SCOPE,'requests_reserved':56,'positions_reserved':1400,
        'out':str(out),'model':MODEL,'configuration_sha256':digest((out/'configuration.json').read_bytes()),
        'policy':'one attempt; reservation survives all failures; never remove to retry'})
    save(out/'budget-reservation.json',json.loads(LEDGER.read_text()))
    recorder = Recorder(out, inputs['provider_batches'])
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            recorder.handle(self)
        def log_message(self,*args):
            pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    server.timeout=1
    thread=threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        # Disable ambient proxies for the unmodified runner's loopback hop.
        extra={k:'' for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')}
        extra.update({'NO_PROXY':'*','no_proxy':'*'})
        argv=[str(out/'runner'),'-out',str(out/'live'),'-timeout','120s','-expect-fixture-sha256',FROZEN,
            '-embedding','http','-embedding-base-url',f'http://127.0.0.1:{server.server_port}/v1',
            '-embedding-model',MODEL,'-embedding-max-inputs','1400','-embedding-dimensions','768','-embedding-timeout','10s']
        code=command(out,'live',argv,extra=extra,timeout=150)
    finally:
        server.shutdown();thread.join(10);server.server_close()
        save(out/'client-observations.json',{'scope':SCOPE,'calls':recorder.calls,'submitted_positions':recorder.positions,
            'upstream_attempts':sum(c['upstream_attempts'] for c in recorder.calls),'abort':recorder.abort,
            'owned_forwarder_stopped':not thread.is_alive()})
        save(out/'source-after.json',source_snapshot())
    after_dir=out/'after';after_dir.mkdir()
    try:
        after=read_endpoint(after_dir)
        save(out/'counter-delta.json',counter_delta(before['metrics']['counters'],after['metrics']['counters'],recorder))
    except Exception as error:
        save(out/'after-read-failure.json',{'scope':SCOPE,'exception_type':type(error).__name__,'retry':False})
    assert source_snapshot() == json.loads((out/'source-before.json').read_text())
    print(f'One model-run attempt finished with exit {code}; upstream attempts={len(recorder.calls)}, positions={recorder.positions}. Never rerun.')
    return code


def counter_delta(before,after,recorder):
    expected={'requests_total':len(recorder.calls),'requests_ok':sum(c.get('http_status')==200 for c in recorder.calls),
              'input_positions':sum(c.get('submitted_positions',0) for c in recorder.calls if c.get('http_status')==200),
              'computations':4*sum(c.get('http_status')==200 for c in recorder.calls),'truncations':0,'overlength_inputs':0}
    actual={key:after[key]-before[key] for key in expected}
    roles={key:after['inputs_by_role'][key]-before['inputs_by_role'][key] for key in ('query','passage')}
    expected_roles={'query':expected['requests_ok'],'passage':24*expected['requests_ok']}
    rejected={key:after['rejected'].get(key,0)-before['rejected'].get(key,0) for key in set(before['rejected'])|set(after['rejected'])}
    return {'scope':SCOPE,'expected':expected,'actual':actual,'roles_expected':expected_roles,'roles_actual':roles,
            'rejected_delta':rejected,'distinct_hash_delta':after['distinct_input_hashes']-before['distinct_input_hashes'],
            'encode_seconds_delta':after['encode_seconds']-before['encode_seconds'],
            'matches':actual==expected and roles==expected_roles and not any(rejected.values())}


def metric(rows):
    ranks=[r['rank'] for r in rows];n=len(ranks)
    hits=[sum(r is not None and r<=k for r in ranks) for k in (1,3,5)]
    return {'n':n,**{f'hits_at_{k}':v for k,v in zip((1,3,5),hits)},
        **{f'recall_at_{k}':v/n if n else None for k,v in zip((1,3,5),hits)},
        'mrr_at_5':math.fsum(1/r for r in ranks if r is not None and r<=5)/n if n else None}


def compare_metric(actual,expected):
    assert set(actual)==set(expected)
    for key,value in expected.items():
        if value is None:
            assert actual[key] is None
        elif isinstance(value,float):
            assert math.isclose(actual[key],value,rel_tol=1e-12,abs_tol=1e-12),(key,actual[key],value)
        else:
            assert actual[key]==value


def analyze(out):
    fixture=json.loads((ROOT/'scripts/validation/flh045/fixture.json').read_text())
    judgments={j['query_id']:j for j in fixture['judgments']}
    meta={q['id']:q for q in fixture['queries']}
    path=out/'live/report.json'
    if not path.exists():
        save(out/'analysis.json',{'scope':SCOPE,'state':'BLOCKED_OR_FAILED','reason':'no live report; partial wire evidence retained; no quality metrics'})
        return 1
    report=json.loads(path.read_text())
    assert report['inputs']==json.loads((out/'offline/report.json').read_text())['inputs']
    names=[r['fixture_id'] for r in report['concept_id_mapping']]
    assert names==sorted(c['id'] for c in fixture['concepts'])
    result={'scope':SCOPE,'state':'completed','metrics':{},'cases':{},'unscored':{},'disagreements':{}}
    for rr in report['offline_baselines']+[report['embedding']]:
        assert [r['query_id'] for r in rr['queries']]==sorted(meta)
        evaluation=rr['evaluation'];rows=[];unscored=[]
        for q in rr['queries']:
            hits=q['hits'];seen=set();previous=math.inf
            assert len(hits)<=5
            for rank,h in enumerate(hits,1):
                assert h['rank']==rank and h['concept_fixture_id'] not in seen
                assert names[h['concept_id']-1]==h['concept_fixture_id'] and math.isfinite(h['score'])
                assert h['score']<=previous
                previous=h['score'];seen.add(h['concept_fixture_id'])
            m=meta[q['query_id']];j=judgments[q['query_id']]
            if m['bucket']=='single_target':
                target=j['proposed_relevant_concept_ids'][0]
                rank=next((h['rank'] for h in hits if h['concept_fixture_id']==target),None)
                rows.append({'query_id':q['query_id'],'rank':rank,'target':target,'top':hits[0]['concept_fixture_id'] if hits else None,
                    'split':m['split'],'language':m['language'],'group':m['group_id']})
            else:
                unscored.append({'query_id':q['query_id'],'bucket':m['bucket'],'returned':len(hits),
                    'alternatives':{alt:next((h['rank'] for h in hits if h['concept_fixture_id']==alt),None) for alt in j['possible_concept_ids']}})
        if rr['state']!='completed':
            result['state']='failed'
            assert evaluation['overall'] is None and evaluation['by_split'] is None and evaluation['by_language'] is None
            result['metrics'][rr['name']]=None
        else:
            assert len(rows)==48 and all(q['status']=='ok' for q in rr['queries'])
            computed={'overall':metric(rows)}
            compare_metric(evaluation['overall'],computed['overall'])
            for field,keys in [('by_split',('split',)),('by_language',('language',)),('by_split_language',('split','language')),('by_group',('group',))]:
                slices={}
                for row in rows:
                    key='/'.join(row[k] for k in keys)
                    slices.setdefault(key,[]).append(row)
                computed[field]={key:metric(subset) for key,subset in sorted(slices.items())}
                assert set(evaluation[field])==set(slices)
                for key,expected in computed[field].items():
                    compare_metric(evaluation[field][key],expected)
                assert sum(v['n'] for v in computed[field].values())==48
                for k in (1,3,5):
                    assert sum(v[f'hits_at_{k}'] for v in computed[field].values())==computed['overall'][f'hits_at_{k}']
                assert math.isclose(sum(v['n']*v['mrr_at_5'] for v in computed[field].values()),48*computed['overall']['mrr_at_5'],abs_tol=1e-12)
            for row,case in zip(rows,evaluation['single_target_cases'],strict=True):
                assert row['query_id']==case['query_id'] and row['rank']==case['target_rank'] and row['target']==case['proposed_target']
            for bucket,field in [('ambiguous','ambiguous_cases'),('no_match','no_match_cases')]:
                observations=[o for o in unscored if o['bucket']==bucket]
                assert len(observations)==len(evaluation[field])==4
                for actual,expected in zip(evaluation[field],observations,strict=True):
                    assert actual['query_id']==expected['query_id'] and actual['returned']==expected['returned']
                    if bucket=='ambiguous':
                        assert actual['alternative_ranks']==expected['alternatives']
            result['metrics'][rr['name']]=computed
        result['cases'][rr['name']]=rows
        result['unscored'][rr['name']]=unscored
    emb=result['cases']['embedding_retriever_v1']
    if report['embedding']['state']=='completed':
        for other in ('weighted_lexical_retriever_v1','bm25_retriever_v1'):
            pairs=list(zip(emb,result['cases'][other],strict=True))
            result['disagreements'][other]={}
            for k in (1,5):
                success=lambda row:row['rank'] is not None and row['rank']<=k
                result['disagreements'][other][f'embedding_fixes_at_{k}']=[a['query_id'] for a,b in pairs if success(a) and not success(b)]
                result['disagreements'][other][f'embedding_misses_at_{k}']=[a['query_id'] for a,b in pairs if not success(a) and success(b)]
    # Offline baseline rankings must agree with those preceding the live path.
    offline=json.loads((out/'offline/report.json').read_text())
    assert [rr['ranking_digest'] for rr in report['offline_baselines']]==[rr['ranking_digest'] for rr in offline['offline_baselines']]
    result['counter_delta']=json.loads((out/'counter-delta.json').read_text()) if (out/'counter-delta.json').exists() else None
    if result['counter_delta'] is None or not result['counter_delta']['matches']:
        result['state']='accounting_unresolved'
    counters=report['embedding'].get('provider_counters',{})
    calls=json.loads((out/'client-observations.json').read_text())
    assert counters.get('requests')==len(calls['calls']) and counters.get('input_positions')==calls['submitted_positions']
    inputs=json.loads((out/'rendered-inputs.json').read_text())['provider_batches']
    unique=len({digest(t.encode()) for b in inputs[:len(calls['calls'])] for t in b})
    assert counters['unique_input_hashes']==unique
    result['client_counts']=counters
    # Independently reconstruct the embedding top five from retained response vectors.
    # This is offline arithmetic over the ONE run, never another embedding call.
    vector_evidence = {'responses_checked': 0, 'vectors_checked': 0,
        'norm_min': math.inf, 'norm_max': 0.0, 'max_score_difference': 0.0,
        'max_repeated_text_coordinate_difference': 0.0,
        'score_comparison_absolute_tolerance': 1e-12, 'norm_absolute_tolerance': 0.001}
    seen_vectors = {}
    for index, call in enumerate(calls['calls'], 1):
        if call.get('http_status') != 200:
            continue
        wire = out/'wire'/f'{index:03d}'
        request = json.loads((wire/'request.json').read_text())
        response = json.loads((wire/'response.json').read_text())
        assert request['input'] == inputs[index-1]
        assert response['model'] == MODEL and len(response['data']) == 25
        assert [item['index'] for item in response['data']] == list(range(25))
        vectors = [item['embedding'] for item in response['data']]
        for text, vector in zip(request['input'], vectors, strict=True):
            assert len(vector) == 768 and all(math.isfinite(v) for v in vector)
            n = math.sqrt(math.fsum(v*v for v in vector))
            assert n > 0 and abs(n-1) <= 0.001
            vector_evidence['norm_min'] = min(vector_evidence['norm_min'], n)
            vector_evidence['norm_max'] = max(vector_evidence['norm_max'], n)
            vector_evidence['vectors_checked'] += 1
            if text in seen_vectors:
                diff = max(abs(a-b) for a,b in zip(vector,seen_vectors[text],strict=True))
                vector_evidence['max_repeated_text_coordinate_difference'] = max(
                    vector_evidence['max_repeated_text_coordinate_difference'], diff)
            else:
                seen_vectors[text] = vector
        query = vectors[0]
        qnorm = math.sqrt(math.fsum(x*x for x in query))
        scores = []
        for i, vector in enumerate(vectors[1:]):
            score = math.fsum(x*y for x,y in zip(query,vector,strict=True))/(qnorm*math.sqrt(math.fsum(x*x for x in vector)))
            if score > 0:
                scores.append((min(1.0,max(-1.0,score)), i+1))
        scores.sort(key=lambda item: (-item[0], item[1]))
        hits = report['embedding']['queries'][index-1]['hits']
        if report['embedding']['queries'][index-1]['status'] == 'ok':
            assert [i for score,i in scores[:5]] == [h['concept_id'] for h in hits]
            for (score,i), hit in zip(scores[:5],hits,strict=True):
                difference = abs(score-hit['score'])
                assert difference <= 1e-12
                assert hit['evidence']['representation'] == 'concept_embedding_text_v1'
                assert hit['evidence']['provider'] == 'http:'+MODEL
                assert hit['evidence']['dimensions'] == 768
                vector_evidence['max_score_difference'] = max(vector_evidence['max_score_difference'],difference)
        vector_evidence['responses_checked'] += 1
    result['vector_reconstruction'] = vector_evidence
    assert source_snapshot()==json.loads((out/'source-before.json').read_text())
    save(out/'analysis.json',result)
    print(json.dumps({'scope':SCOPE,'state':result['state'],'overall_metrics':{k:v['overall'] if v else None for k,v in result['metrics'].items()},'disagreements':result['disagreements']},indent=2))
    return 0 if result['state']=='completed' else 1


def repeat_consistency(out):
    """Offline check against the PREVIOUSLY declared FLH-056 tolerance.
    Never alters the runner's metrics or requests another vector.
    """
    batches=json.loads((out/'rendered-inputs.json').read_text())['provider_batches']
    seen={};differences=[];maximum=0.0;worst=None
    for i,batch in enumerate(batches,1):
        path=out/'wire'/f'{i:03d}'/'response.json'
        if not path.exists():
            break
        response=json.loads(path.read_text())
        if 'data' not in response:
            break
        for pos,(text,row) in enumerate(zip(batch,response['data'],strict=True)):
            vector=row['embedding']
            if text in seen:
                old=seen[text]
                delta=max(abs(a-b) for a,b in zip(old,vector,strict=True))
                bad=sum(abs(a-b)>1e-5+1e-4*max(abs(a),abs(b)) for a,b in zip(old,vector,strict=True))
                if bad:
                    differences.append({'query_id':f'Q{i:03d}','concept_id':f'C{pos:03d}',
                        'violating_coordinates':bad,'max_absolute_difference':delta})
                if delta>maximum:
                    maximum=delta;worst={'query_id':f'Q{i:03d}','concept_id':f'C{pos:03d}'}
            else:
                seen[text]=vector
    result={'scope':SCOPE,'reference':'first retained vector for the same rendered text; offline analysis only',
        'absolute_tolerance':1e-5,'relative_tolerance':1e-4,
        'state':'FAILED_prior_FLH056_coordinate_consistency_tolerance' if differences else 'passed',
        'max_absolute_difference':maximum,'worst_pair':worst,
        'affected_document_ids':sorted({d['concept_id'] for d in differences}),
        'violating_repeat_vectors':len(differences),'details':differences,'rerun':False,'tolerance_loosened':False}
    save(out/'repeat-consistency.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='details'},indent=2))
    return 1 if differences else 0


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=('prepare','run','analyze','repeats'))
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--allow-one-model-run',action='store_true')
    args=ap.parse_args()
    out=args.out
    assert out.is_absolute() and out.parent==Path('/tmp') and out.name.startswith('flh058-')
    assert out.parent.resolve()==out.parent and not out.is_symlink()
    if args.action=='prepare':
        assert not args.allow_one_model_run
        out.mkdir(mode=0o700)
        prepare(out)
        return 0
    assert out.is_dir()
    if args.action=='run':
        assert args.allow_one_model_run,'real model run requires explicit opt-in'
        return run_once(out)
    assert not args.allow_one_model_run
    if args.action=='repeats':
        return repeat_consistency(out)
    code=analyze(out)
    artifacts(out)
    return code


if __name__=='__main__':
    sys.exit(main())
