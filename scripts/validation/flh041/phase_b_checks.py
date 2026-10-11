#!/usr/bin/env python3
"""FLH-043 active FLH-042 acceptance: actual pinned local Qdrant, no pulls.

Historical FLH-041 reports/fixtures remain unchanged. Output is a new external
folder. A nonzero exit reflects failed assertions or unavailable coverage.
"""
import argparse
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'flh026'))
from run import clean_env, owns_listener
from fake_embeddings import FakeEmbeddings, Fault, deterministic_vector, text_digest
from oracles import assert_embedding_delta, assert_bounded_provider, assert_read_only, assert_cache, CacheKey

QIMAGE = 'qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10'


def request(base, path, method='GET', data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=payload, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def snapshot(path):
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        def values(row):
            return [v.hex() if isinstance(v, bytes) else v for v in row]
        return {'schema': db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall(),
                'tables': {t: sorted([values(r) for r in db.execute('SELECT * FROM "'+t+'"')], key=repr) for t in tables}}


def write_probe(path):
    started = time.monotonic()
    with sqlite3.connect(path, timeout=0.05) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('ROLLBACK')
    return time.monotonic() - started


def vector_records(inventory):
    # Qdrant optimizer/segment statistics may change autonomously. Preserve raw
    # metadata in evidence, but assert record/shape equality, not telemetry.
    return {space: {'collection': value['collection'], 'points': value['points'],
                    'shape': value['info'].get('result', {}).get('config', {}).get('params', {}).get('vectors')}
            for space, value in inventory.items()}


class Proxy:
    """Owned fault gate forwarding to the actual Qdrant; never a fake index."""
    def __init__(self, upstream):
        self.upstream = upstream
        self.rule = None
        self.events = []
        self.reached, self.release = threading.Event(), threading.Event()

    def arm(self, method, suffix, kind, nth=1):
        self.rule = [method, suffix, kind, nth]
        self.reached.clear(); self.release.clear()

    def __enter__(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def action(self):
                length = int(self.headers.get('Content-Length', '0'))
                data = json.loads(self.rfile.read(length)) if length else None
                rule = owner.rule
                fault = None
                if rule and self.command == rule[0] and self.path.endswith(rule[1]):
                    rule[3] -= 1
                    if rule[3] == 0:
                        fault = rule[2]; owner.rule = None
                event = {'method': self.command, 'path': self.path, 'body': data, 'fault': fault}
                owner.events.append(event)
                if fault == 'hold-before':
                    owner.reached.set()
                    if not owner.release.wait(15): raise TimeoutError('owned proxy gate')
                if fault in ('fail', 'fail-held'):
                    code, body = 503, {'status': 'injected-owned-failure', 'result': None}
                else:
                    code, body = request(owner.upstream, self.path, self.command, data)
                event.update(status=code, response=body)
                if fault in ('lost-ack', 'hold-after', 'fail-held'):
                    owner.reached.set()
                    if not owner.release.wait(15): raise TimeoutError('owned proxy acknowledgement gate')
                if fault == 'lost-ack':
                    self.close_connection = True
                    return
                raw = json.dumps(body).encode()
                try:
                    self.send_response(code); self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError): pass
            do_GET = do_POST = do_PUT = do_DELETE = action
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        return self

    def __exit__(self,*_):
        self.release.set(); self.server.shutdown(); self.server.server_close(); self.thread.join(3)
        assert not self.thread.is_alive()


class Runner:
    def __init__(self, output):
        self.out = output; self.out.mkdir()
        self.work = Path(tempfile.mkdtemp(prefix='flh043-work-'))
        self.home = self.work/'home'; self.home.mkdir()
        self.env = clean_env(self.home)
        self.env.update(AI_PROVIDER='rule-based',EXTRACTOR_PROVIDER='disabled',OPENAI_API_KEY='',
                        EMBEDDING_PROVIDER='http',EMBEDDING_MODEL='fixture',EMBEDDING_MODEL_ID='fixture/model@a',
                        EMBEDDING_DIMENSIONS='8',SEMANTIC_SEARCH='qdrant',SEMANTIC_BATCH_SIZE='2',
                        HTTP_ALLOWED_HOSTS='',TMPDIR=str(self.work),GOCACHE=str(self.work/'gocache'),DOCKER_BUILDKIT='0')
        self.env['GOMODCACHE'] = subprocess.check_output(['go','env','GOMODCACHE'],env={'PATH':self.env['PATH'],'HOME':str(Path.home()),'GOENV':'off','GOTOOLCHAIN':'local'},text=True).strip()
        self.source=self.work/'source'; self.source.mkdir()
        self.id='flh043-'+uuid.uuid4().hex[:12]; self.children=[]; self.containers=[]
        self.report={'task':'FLH-043','pwd':str(ROOT),'cases':[],'commands':[],'cleanup':[], 'limits':[]}
        self.counter=0; self.tag=None; self.compose=None; self.used_ports=[]

    def command(self, argv, env=None, timeout=240, check=True):
        p=subprocess.run(list(map(str,argv)),cwd=self.source,env=env or self.env,stdin=subprocess.DEVNULL,
                         text=True,capture_output=True,timeout=timeout)
        r={'argv':list(map(str,argv)),'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        self.report['commands'].append(r)
        print('COMMAND',argv[0:3],p.returncode,flush=True)
        if check and p.returncode: raise AssertionError(r)
        return r

    def child(self, argv, env):
        self.counter+=1
        log=self.out/f'process-{self.counter}.log'
        handle=log.open('w')
        p=subprocess.Popen(list(map(str,argv)),cwd=self.source,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT)
        identity=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        cmdline=Path(f'/proc/{p.pid}/cmdline').read_bytes().hex()
        self.children.append((p,handle,identity,cmdline))
        self.report.setdefault('processes',[]).append({'pid':p.pid,'start_time':identity,'cmdline_hex':cmdline,'argv':list(map(str,argv)),'log':str(log),'port':env.get('PORT'),'database':env.get('DB_PATH')})
        if Path(argv[0]).name=='server':self.used_ports.append(int(env['PORT']))
        return p,log

    def case(self, name, expected, fn):
        result={'name':name,'expected':expected}
        try: result['actual']=fn(); result['result']='PASS'
        except Exception as exc: result.update(result='FAIL',actual=str(exc))
        self.report['cases'].append(result)
        self.save('checkpoint', self.report)
        print('CASE',name,result['result'],flush=True)
        return result

    def save(self, name, value):
        (self.out/(name+'.json')).write_text(json.dumps(value,indent=2,default=str))
        return name+'.json'

    def probe(self, mode, db, env=None):
        return json.loads(self.command([self.work/'probe',mode,db],env)['stdout'])

    def cli(self, operation, env=None, expected=0):
        r=self.command([self.work/'semantic-index','-json','-batch','2',operation],env,check=False)
        assert r['exit']==expected,r
        return json.loads(r['stdout']) if r['stdout'].strip() else r

    def inventory(self, env=None):
        env=env or self.env
        with sqlite3.connect(env['DB_PATH']) as db:
            rows=db.execute('SELECT space,published_collection FROM semantic_index_spaces ORDER BY space').fetchall()
        result={}
        for space,col in rows:
            if not col: continue
            code, info=request(self.qurl,'/collections/'+col)
            points=[]; offset=None
            if code==200:
                while True:
                    body={'limit':2,'with_vector':True,'with_payload':True}
                    if offset is not None: body['offset']=offset
                    code,page=request(self.qurl,'/collections/'+col+'/points/scroll','POST',body)
                    assert code==200,page
                    points.extend(page['result']['points']); offset=page['result']['next_page_offset']
                    if offset is None: break
            result[space]={'collection':col,'info':info,'points':sorted(points,key=lambda p:p['id'])}
        return result

    def verify(self, env=None, provider=None):
        env=env or self.env
        docs=self.probe('documents',env['DB_PATH'],env)
        current={d['ConceptID']:d for d in docs}
        inv=self.inventory(env); space=self.cli('status',env)['state']['space']; records=inv[space]
        with sqlite3.connect(env['DB_PATH']) as db:
            cache=db.execute('SELECT content_hash,representation,model_id,dimensions,vector FROM semantic_embedding_cache').fetchall()
            manifest=dict(db.execute('SELECT concept_id,content_hash FROM semantic_index_manifest WHERE collection=?',(records['collection'],)))
        assert manifest=={i:d['ContentHash'] for i,d in current.items()}
        selected={(h,rep,model,dim):struct.unpack('<'+'f'*dim,blob) for h,rep,model,dim,blob in cache if model==env['EMBEDDING_MODEL_ID'] and dim==int(env['EMBEDDING_DIMENSIONS'])}
        assert set(p['id'] for p in records['points'])==set(current)
        for p in records['points']:
            d=current[p['id']]; payload=p['payload']
            expected={'concept_id':p['id'],'content_hash':d['ContentHash'],'representation':'concept_embedding_text_v1','model_id':env['EMBEDDING_MODEL_ID'],'dimensions':int(env['EMBEDDING_DIMENSIONS'])}
            assert payload==expected,(payload,expected)
            v=selected[(d['ContentHash'],'concept_embedding_text_v1',env['EMBEDDING_MODEL_ID'],int(env['EMBEDDING_DIMENSIONS']))]
            norm=math.sqrt(sum(x*x for x in v)); actual=p['vector']
            assert len(actual)==len(v) and all(abs(a-b/norm)<1e-5 for a,b in zip(actual,v))
        expected_cache={CacheKey(d['ContentHash'],'concept_embedding_text_v1',env['EMBEDDING_MODEL_ID'],int(env['EMBEDDING_DIMENSIONS'])):deterministic_vector(d['Text'],'fixture',int(env['EMBEDDING_DIMENSIONS'])) for d in docs}
        observed_cache={CacheKey(*key):list(v) for key,v in selected.items()}
        # Historical content keys may remain. Compare exact current keys separately,
        # retaining the complete cache inventory in evidence.
        assert_cache({k:observed_cache[k] for k in expected_cache},expected_cache)
        self.counter+=1
        evidence=self.save(f'inventory-{self.counter}',{'documents':docs,'sqlite':snapshot(env['DB_PATH']),'qdrant':inv,'cache':[[*key,list(v)] for key,v in selected.items()]})
        assert self.cli('status',env)['verified_healthy']
        return evidence

    def setup(self):
        for directory in ['cmd','internal','migrations']:
            shutil.copytree(ROOT/directory,self.source/directory)
        for file in ['go.mod','go.sum','Dockerfile','.dockerignore','compose.yaml']:
            shutil.copy2(ROOT/file,self.source/file)
        shutil.copytree(HERE/'ownership_probe',self.source/'scripts/validation/flh041/ownership_probe')
        shutil.copytree(ROOT/'web/src',self.source/'web/src')
        for file in ['package.json','package-lock.json','index.html','vite.config.ts','tsconfig.json','tsconfig.app.json','tsconfig.node.json']:
            shutil.copy2(ROOT/'web'/file,self.source/'web'/file)
        baseline_paths=[ROOT/name for name in ['AGENTS.md','docs/SEMANTIC_SEARCH.md','docs/ARCHITECTURE.md',
                         'docs/plans/FLH-042-index-run-consistency.md','docs/validation/FLH-042-index-run-consistency.md',
                         'docs/validation/FLH-041-vector-search-acceptance.md','Dockerfile','compose.yaml','.dockerignore','go.mod','go.sum','README.zh-CN.md']]
        for folder in ['cmd','internal','migrations','scripts/validation/flh041']:
            baseline_paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.go','.sql','.py','.json','.md'])
        self.report['baseline']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(baseline_paths))}
        self.report['source_copy_hashes']={str(p.relative_to(self.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
        for args in [['go','version'],['python3','--version'],['docker','version'],['docker','compose','version'],['docker','image','inspect',QIMAGE]]:
            self.command(args)
        for target,name in [('./cmd/server','server'),('./cmd/semantic-index','semantic-index'),('./scripts/validation/flh041/ownership_probe','probe')]:
            self.command(['go','build','-o',self.work/name,target])
            self.command(['go','version','-m',self.work/name])
        self.report['binary_hashes']={name:hashlib.sha256((self.work/name).read_bytes()).hexdigest() for name in ['server','semantic-index','probe']}
        qdata=self.work/'qdata';qdata.mkdir();qp=port()
        self.used_ports.append(qp)
        self.qname=self.id+'-qdrant';self.containers.append(self.qname)
        self.command(['docker','run','-d','--pull=never','--name',self.qname,'-p',f'127.0.0.1:{qp}:6333',
                      '--mount',f'type=bind,source={qdata},target=/qdrant/storage','--env','QDRANT__TELEMETRY_DISABLED=true',
                      '--env','QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/storage/snapshots',QIMAGE])
        self.report['qdrant_container']=json.loads(self.command(['docker','inspect',self.qname])['stdout'])
        self.qurl=f'http://127.0.0.1:{qp}'
        for _ in range(60):
            try:
                code,version=request(self.qurl,'/');
                if code==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise AssertionError('owned Qdrant did not become ready')
        self.report['qdrant_version']=version
        self.env.update(DB_PATH=str(self.work/'app.db'),QDRANT_URL=self.qurl,QDRANT_COLLECTION_PREFIX=self.id.replace('-','_'))
        self.docs=self.probe('seed',self.env['DB_PATH'])
        (self.out/'documents.json').write_text(json.dumps(self.docs))
        self.report['browser']={'executables':{n:shutil.which(n,path=self.env['PATH']) for n in ['chromium','chromium-browser','google-chrome','firefox']},'interaction':'NOT RUN'}

    def scenarios(self, provider, proxy):
        self.env['EMBEDDING_BASE_URL']=provider.base_url
        for d in self.docs:provider.register(d['Text'],'document')
        provider.register('flh043 query','query')
        def measured(operation, env=None, expected_documents=(), expected=0):
            before=provider.snapshot();result=self.cli(operation,env,expected)
            assert provider.wait_idle();after=provider.snapshot()
            self.counter+=1;self.save(f'counters-{self.counter}',{'before':before,'after':after,'operation':operation,'report':result})
            assert_embedding_delta(before,after,expected_documents=expected_documents)
            return result
        unique=list(dict.fromkeys(d['Text'] for d in self.docs))
        self.case('lease-repository','busy/expiry/takeover and all nine superseded mutations refused',lambda:self.probe('repository',self.work/'repository.db'))
        def build():
            r=measured('build',expected_documents=[text_digest(t) for t in unique]);assert r['published'] and r['embedded_texts']==3
            return {'report':r,'inventory':self.verify()}
        self.case('build-dedup','three document attempts for four concepts; full cache/manifest/points agree',build)
        def reuse():
            results=[]
            for op in ['status','sync','rebuild','sync']:
                r=measured(op);results.append(r)
                if op=='sync':assert r['verified_unchanged']
            # Each CLI is a fresh process, then the server is restarted separately.
            return {'operations':results,'inventory':self.verify()}
        self.case('restart-sync-rebuild-reuse','zero document calls; new rebuild publication; exact inventories',reuse)
        for gate in ['upsert','record-manifest','publish','publish-noop']:
            self.case('takeover-'+gate,'old ownership lost; every newer point/vector/payload and active record unchanged',lambda gate=gate:self.probe(gate,self.env['DB_PATH']))
        for gate in ['search-query-race','search-info-race']:
            def search_race(gate=gate):
                before=provider.snapshot();r=self.probe(gate,self.env['DB_PATH']);assert provider.wait_idle()
                # A CollectionInfo race occurs before query embedding; a Query
                # race occurs afterwards and must reuse that one query vector.
                assert_embedding_delta(before,provider.snapshot(),expected_queries=[] if gate=='search-info-race' else [text_digest('flh043 query')])
                assert r['pass'],r
                return r
            self.case(gate,'retry once on replacement, using one query embedding',search_race)
        def damage(kind):
            current=self.inventory();points=next(iter(current.values()))['points'];col=next(iter(current.values()))['collection']
            path='/collections/'+col
            if kind=='missing':code,_=request(self.qurl,path+'/points/delete?wait=true','POST',{'points':[2]})
            elif kind in ['same-count','foreign','stale','extra']:
                p=json.loads(json.dumps(points[1]));
                if kind=='same-count':p['vector']=points[0]['vector']
                elif kind=='foreign':p['payload']['model_id']='foreign/model'
                elif kind=='stale':p['payload']['content_hash']='foreign-hash'
                else:p['id']=999;p['payload']['concept_id']=999
                code,_=request(self.qurl,path+'/points?wait=true','PUT',{'points':[p]})
            else:
                request(self.qurl,path,'DELETE');size=9 if kind=='dimension' else 8;distance='Dot' if kind=='distance' else 'Cosine'
                code,_=request(self.qurl,path,'PUT',{'vectors':{'size':size,'distance':distance}})
            assert code==200
            before=provider.snapshot();st=self.cli('status');assert not st['verified_healthy'];assert provider.wait_idle()
            assert_embedding_delta(before,provider.snapshot())
            h=st['health'];field={'missing':'missing','same-count':'vector_mismatch','foreign':'foreign_payload','stale':'stale','extra':'extra'}.get(kind)
            if field:assert h[field]==([999] if kind=='extra' else [2]),h
            else:assert not h['shape_ok']
            r=measured('sync');assert r['published'] and r['embedded_texts']==0
            return {'unhealthy':st,'repair':r,'inventory':self.verify()}
        for kind in ['missing','same-count','foreign','stale','extra','dimension','distance']:
            self.case('repair-'+kind,'full verification detects exact damage; sync repairs without embeddings',lambda kind=kind:damage(kind))
        def model():
            new=dict(self.env,EMBEDDING_MODEL_ID='fixture/model@b')
            r=measured('build',new,[text_digest(t) for t in unique]);assert r['embedded_texts']==3
            return {'report':r,'inventory':self.verify(new)}
        self.case('model-isolation','same wire model with new identity embeds separately and preserves old space',model)
        def invalid():
            observed=[]
            for kind in ['wrong-dimension','zero','nonfinite','short','duplicate-index','malformed']:
                new=dict(self.env,EMBEDDING_MODEL_ID='fixture/invalid@'+kind)
                provider.arm(provider.snapshot()['requests']+1,Fault(kind=kind))
                r=measured('build',new,[text_digest(t) for t in unique[:2]],expected=1)
                with sqlite3.connect(new['DB_PATH']) as db:
                    assert db.execute('SELECT count(*) FROM semantic_embedding_cache WHERE model_id=?',(new['EMBEDDING_MODEL_ID'],)).fetchone()[0]==0
                assert not r['published'] and r['outcome']=='failed';observed.append(r)
            return observed
        self.case('invalid-output-refusal','invalid first batch creates no cache or publication',invalid)
        def partial():
            new=dict(self.env,EMBEDDING_MODEL_ID='fixture/partial')
            provider.arm(provider.snapshot()['requests']+2,Fault(kind='status'))
            r=measured('build',new,[text_digest(t) for t in unique],expected=1)
            with sqlite3.connect(new['DB_PATH']) as db:count=db.execute('SELECT count(*) FROM semantic_embedding_cache WHERE model_id=?',(new['EMBEDDING_MODEL_ID'],)).fetchone()[0]
            assert count==2 and not r['published']
            retry=measured('sync',new,[text_digest(unique[2])]);assert retry['embedded_texts']==1
            return {'failed':r,'recovered':retry,'inventory':self.verify(new)}
        self.case('partial-embedding','two valid cached inputs survive second-batch failure; retry embeds only remaining key',partial)
        self.network_cases(provider,proxy,measured)
        self.cleanup_case(provider,proxy,measured)
        self.search_cases(provider)
        # Save exact production-rendered changed inputs before classifying their calls.
        changed=json.loads(json.dumps(self.docs));changed[1]['Text']=changed[1]['Text'].replace('flh043 beta','flh043 delta')
        provider.register(changed[1]['Text'],'document')
        def source():
            before=provider.snapshot();r=self.probe('source-change',self.env['DB_PATH']);assert provider.wait_idle()
            delta=r['documents'][1]['Text'];assert delta==changed[1]['Text']
            assert_embedding_delta(before,provider.snapshot(),expected_documents=[text_digest(delta)])
            return {'probe':r,'inventory':self.verify()}
        self.case('source-catchup','one changed source absorbed before publication; only changed text embeds',source)
        self.save('provider-complete-ledger',provider.snapshot())
        assert_bounded_provider(provider.snapshot(),max_batch=2,max_concurrency=1)
        self.report['remaining_inventory']=self.inventory()

    def network_cases(self, provider, proxy, measured):
        routed=dict(self.env,QDRANT_URL=proxy.base)
        def held(kind, sig=None):
            prior=self.cli('status')['state']['published_collection']
            before=provider.snapshot()
            proxy.arm('PUT','/points?wait=true',kind,nth=2)
            p,log=self.child([self.work/'semantic-index','-json','-batch','2','rebuild'],routed)
            assert proxy.reached.wait(8)
            elapsed=write_probe(self.env['DB_PATH'])
            event=next(e for e in reversed(proxy.events) if e['fault']==kind)
            col=event['path'].split('/')[2]
            _, page=request(self.qurl,'/collections/'+col+'/points/scroll','POST',{'limit':20,'with_vector':True,'with_payload':True})
            with sqlite3.connect(self.env['DB_PATH']) as db:
                manifest=db.execute('SELECT concept_id,content_hash FROM semantic_index_manifest WHERE collection=?',(col,)).fetchall()
                state=db.execute('SELECT published_collection,lease_run_id FROM semantic_index_spaces WHERE space=?',(self.cli('status')['state']['space'],)).fetchone()
            assert state[0]==prior and len(page['result']['points'])==4 and len(manifest)==2
            evidence=self.save('held-'+(sig.name if sig else kind),{'points':page,'manifest':manifest,'state':state,'write_acquisition_seconds':elapsed})
            if sig is not None:
                assert p.poll() is None
                p.send_signal(sig)
            proxy.release.set()
            exitcode=p.wait(8)
            assert exitcode==(-sig if sig==signal.SIGKILL else 1),(exitcode,log.read_text())
            assert provider.wait_idle();assert_embedding_delta(before,provider.snapshot())
            assert self.cli('status')['state']['published_collection']==prior
            if sig==signal.SIGKILL:
                busy=self.command([self.work/'semantic-index','-json','sync'],check=False)
                assert busy['exit']==4
                # Holder verified dead by wait(); explicit takeover is authorized here.
                resume=self.command([self.work/'semantic-index','-json','-takeover','rebuild'])
                assert json.loads(resume['stdout'])['published']
            else:
                st=self.cli('status');assert st['state']['last_run_outcome']==('interrupted' if sig else 'failed')
                measured('rebuild')
            return {'held_inventory':evidence,'process_exit':exitcode,'recovered_inventory':self.verify()}
        self.case('lost-acknowledgement','real Qdrant applies second batch before absent manifest; failure preserves publication and cache',lambda:held('lost-ack'))
        for sig in [signal.SIGINT,signal.SIGTERM,signal.SIGKILL]:
            self.case('process-'+sig.name,'owned CLI interrupted at applied-but-unacknowledged upsert; prior pointer preserved; recovery reuses cache',lambda sig=sig:held('hold-after',sig))
        def provider_hold():
            new=dict(self.env,EMBEDDING_MODEL_ID='fixture/held-provider')
            gate=threading.Event();before=provider.snapshot();ordinal=before['requests']+1
            provider.arm(ordinal,Fault(kind='none',gate=gate))
            p,log=self.child([self.work/'semantic-index','-json','build'],new)
            assert provider.wait_received(ordinal,8)
            elapsed=write_probe(new['DB_PATH'])
            p.send_signal(signal.SIGTERM);gate.set();assert p.wait(8)==1
            assert provider.wait_idle()
            assert_embedding_delta(before,provider.snapshot(),expected_documents=[text_digest(t) for t in list(dict.fromkeys(d['Text'] for d in self.docs))[:2]])
            # Positive control: an independently held writer must make the same probe fail.
            with sqlite3.connect(new['DB_PATH']) as db:
                db.execute('BEGIN IMMEDIATE')
                try: write_probe(new['DB_PATH'])
                except sqlite3.OperationalError: blocked=True
                else: blocked=False
                db.rollback()
            assert blocked
            return {'write_acquisition_seconds':elapsed,'positive_control_blocked':blocked,'log':str(log)}
        self.case('no-write-lock-provider','independent BEGIN IMMEDIATE succeeds during held HTTP provider call; positive control fails',provider_hold)
        self.save('qdrant-proxy-complete-ledger',proxy.events)

    def cleanup_case(self, provider, proxy, measured):
        routed=dict(self.env,QDRANT_URL=proxy.base)
        old=self.cli('status')['state']['published_collection']
        proxy.arm('DELETE','/collections/'+old,'fail')
        r=measured('rebuild',routed)
        assert r['published']
        st=self.cli('status')
        assert any(c['collection']==old and c['status']=='retired' for c in st['collections'])
        self.case('failed-retired-deletion','successful publication leaves failed deletion recorded for recovery',lambda:{'report':r,'status':st})
        def next_sync():
            noop=measured('sync');assert noop['verified_unchanged']
            remaining=self.cli('status')['collections']
            assert all(c['collection']!=old for c in remaining),{'actual_retired_records':remaining,'no_op':noop}
            return noop
        self.case('cleanup-next-healthy-sync','next run removes recorded retired collections even when publication is healthy',next_sync)
        self.case('cleanup-rebuild','rebuild removes retained recorded collections without re-embedding',lambda:{'report':measured('rebuild'),'inventory':self.verify()})
        self.save('qdrant-proxy-complete-ledger',proxy.events)

    def search_cases(self, provider):
        appenv=dict(self.env,PORT=str(port()),LISTEN_HOST='127.0.0.1')
        def start():
            p,log=self.child([self.work/'server'],appenv)
            for _ in range(60):
                if p.poll() is not None:raise AssertionError(log.read_text())
                if owns_listener(p.pid,int(appenv['PORT'])):break
                time.sleep(.05)
            else:raise AssertionError('owned server listener missing')
            base='http://127.0.0.1:'+appenv['PORT']
            assert request(base,'/readyz')[0]==200
            return p,base
        p,base=start()
        query='/knowledge-library/semantic-search?q=flh043%20query&limit=50'
        def reads():
            before_sql=snapshot(self.env['DB_PATH']);before_vec=self.inventory();before=provider.snapshot()
            code,response=request(base,query);assert code==200,response
            assert response['schema_version']=='knowledge_library_semantic_search_v2'
            assert response['index']['health_verified'] is False and 'complete' not in response['index']
            assert provider.wait_idle()
            after_sql=snapshot(self.env['DB_PATH']);after_vec=self.inventory();after=provider.snapshot()
            self.counter+=1;self.save(f'search-read-only-{self.counter}',{'sqlite_before':before_sql,'sqlite_after':after_sql,'vectors_before':before_vec,'vectors_after':after_vec,'provider_before':before,'provider_after':after,'response':response})
            assert_read_only(before_sql,after_sql,vector_records(before_vec),vector_records(after_vec),before,after,expected_queries=[text_digest('flh043 query')])
            return response
        self.case('search-v2-read-only','one query-only attempt; unchanged full SQLite schema/rows and all published points; history not health',reads)
        p.send_signal(signal.SIGTERM);assert p.wait(5)==0
        p,base=start()
        self.case('server-restart','same publication/query behavior survives server restart with no document calls',reads)
        def current_authority():
            points=next(v for k,v in self.inventory().items() if k==self.cli('status')['state']['space'])['points']
            col=self.cli('status')['state']['published_collection'];path='/collections/'+col
            vector=deterministic_vector('flh043 query','fixture',8)
            replacements=[]
            for id,kind in [(1,'stale'),(2,'foreign'),(999,'missing')]:
                item={'id':id,'vector':vector,'payload':dict(points[0]['payload'],concept_id=id)}
                if kind=='stale':item['payload']['content_hash']='stale-fixture'
                if kind=='foreign':item['payload']['model_id']='foreign/model'
                replacements.append(item)
            assert request(self.qurl,path+'/points?wait=true','PUT',{'points':replacements})[0]==200
            before=snapshot(self.env['DB_PATH']);vec=self.inventory();ledger=provider.snapshot()
            code,response=request(base,query);assert code==200,response
            assert response['skipped']['missing']==1 and response['skipped']['stale']==1 and response['skipped']['incompatible']==1,response
            assert all(r['concept']['id'] not in [1,2,999] for r in response['results'])
            assert provider.wait_idle()
            after_sql=snapshot(self.env['DB_PATH']);after_vec=self.inventory();after=provider.snapshot()
            self.save('search-authority-read-only',{'sqlite_before':before,'sqlite_after':after_sql,'vectors_before':vec,'vectors_after':after_vec,'provider_before':ledger,'provider_after':after,'response':response})
            assert_read_only(before,after_sql,vector_records(vec),vector_records(after_vec),ledger,after,expected_queries=[text_digest('flh043 query')])
            self.cli('sync');self.verify()
            return response
        self.case('search-current-authority','positive stale/foreign/missing hits excluded, no substitution or annotation writes',current_authority)
        p.send_signal(signal.SIGTERM);assert p.wait(5)==0


    def extra(self, provider, proxy):
        self.env['EMBEDDING_BASE_URL']=provider.base_url
        for d in self.docs:provider.register(d['Text'],'document')
        provider.register('flh043 query','query')
        before=provider.snapshot();self.cli('build');assert provider.wait_idle()
        unique=list(dict.fromkeys(d['Text'] for d in self.docs))
        assert_embedding_delta(before,provider.snapshot(),expected_documents=[text_digest(t) for t in unique])
        self.verify()
        def dims():
            with FakeEmbeddings(dimensions=9) as nine:
                for d in self.docs:nine.register(d['Text'],'document')
                new=dict(self.env,EMBEDDING_DIMENSIONS='9',EMBEDDING_BASE_URL=nine.base_url)
                before=nine.snapshot();r=self.cli('build',new);assert nine.wait_idle()
                assert_embedding_delta(before,nine.snapshot(),expected_documents=[text_digest(t) for t in unique])
                assert r['embedded_texts']==3 and r['published']
                self.save('dimension-nine-provider-ledger',nine.snapshot())
                return {'report':r,'inventory':self.verify(new)}
        self.case('dimension-space-isolation','same model identity at nine dimensions embeds into a separate space/cache/collection',dims)
        def failed_upsert():
            prior=self.cli('status')['state']['published_collection']
            before=provider.snapshot();proxy.arm('PUT','/points?wait=true','fail-held',nth=2)
            routed=dict(self.env,QDRANT_URL=proxy.base)
            child,log=self.child([self.work/'semantic-index','-json','-batch','2','rebuild'],routed)
            assert proxy.reached.wait(8)
            e=next(x for x in reversed(proxy.events) if x['fault']=='fail-held');col=e['path'].split('/')[2]
            _,actual=request(self.qurl,'/collections/'+col+'/points/scroll','POST',{'limit':20,'with_vector':True,'with_payload':True})
            with sqlite3.connect(self.env['DB_PATH']) as db:
                manifest=db.execute('SELECT concept_id,content_hash FROM semantic_index_manifest WHERE collection=?',(col,)).fetchall()
            assert len(actual['result']['points'])==2 and len(manifest)==2
            elapsed=write_probe(self.env['DB_PATH'])
            self.save('partial-upsert-held',{'actual_points':actual,'manifest':manifest,'proxy_event':e,'write_probe_seconds':elapsed})
            proxy.release.set();assert child.wait(8)==1
            assert self.cli('status')['state']['published_collection']==prior
            assert provider.wait_idle();assert_embedding_delta(before,provider.snapshot())
            self.cli('rebuild')
            return {'prior_publication_preserved':True,'inventory':self.verify()}
        self.case('partial-upsert-failure','later actual upsert refused; prior publication retained, matching partial manifest and recovery',failed_upsert)
        def expiration():
            space=self.cli('status')['state']['space']
            with sqlite3.connect(self.env['DB_PATH']) as db:
                db.execute("UPDATE semantic_index_spaces SET lease_run_id='fixture-dead-holder',lease_operation='rebuild',lease_started_at='2000-01-01T00:00:00.000000000Z',lease_expires_at='2000-01-01T00:00:01.000000000Z' WHERE space=?",(space,))
            before=provider.snapshot();r=self.cli('sync');assert r['verified_unchanged']
            assert provider.wait_idle();assert_embedding_delta(before,provider.snapshot())
            return {'expired_fixture_clock_record':True,'new_run':r,'status':self.cli('status')}
        self.case('expired-lease-cli','real CLI takes a synthetic expired lease without takeover or waiting 120 seconds',expiration)
        def unrecorded():
            space=self.cli('status')['state']['space'];name=space+'_runrecorded_owned'
            assert request(self.qurl,'/collections/'+name,'PUT',{'vectors':{'size':8,'distance':'Cosine'}})[0]==200
            st=self.cli('status');assert name in st['unrecorded_collections']
            before=provider.snapshot();r=self.cli('rebuild');assert provider.wait_idle();assert_embedding_delta(before,provider.snapshot())
            assert request(self.qurl,'/collections/'+name)[0]==404
            return {'unrecorded_status':st,'rebuild':r,'inventory':self.verify()}
        self.case('unrecorded-collection-cleanup','rebuild deletes only owned unrecorded collection of the same space',unrecorded)
        appenv=dict(self.env,PORT=str(port()),LISTEN_HOST='127.0.0.1')
        child,log=self.child([self.work/'server'],appenv)
        for _ in range(60):
            if owns_listener(child.pid,int(appenv['PORT'])):break
            time.sleep(.05)
        else:raise AssertionError('extra server listener missing')
        base='http://127.0.0.1:'+appenv['PORT'];query='/knowledge-library/semantic-search?q=flh043%20query'
        def filters():
            before=snapshot(self.env['DB_PATH']);vectors=self.inventory();counter=provider.snapshot()
            replies=[]
            for state in ['all','orphaned','retired','active']:
                code,r=request(base,query+'&state='+state+'&limit=50');assert code==200,r
                allowed={1,2,3,4} if state=='all' else ({1,2,3} if state=='orphaned' else ({4} if state=='retired' else set()))
                # Independent deterministic-vector cosine determines positive hits;
                # no tie ordering or semantic relevance expectation is imposed.
                q=deterministic_vector('flh043 query','fixture',8)
                expected={d['ConceptID'] for d in self.docs if d['ConceptID'] in allowed and sum(a*b for a,b in zip(q,deterministic_vector(d['Text'],'fixture',8)))>0}
                assert {item['concept']['id'] for item in r['results']}==expected,r
                assert all(item['current_member_count']==item['supporting_unit_count']==0 for item in r['results'])
                replies.append(r)
            assert provider.wait_idle()
            assert_read_only(before,snapshot(self.env['DB_PATH']),vector_records(vectors),vector_records(self.inventory()),counter,provider.snapshot(),expected_queries=[text_digest('flh043 query')]*4)
            self.save('state-filter-reads',{'sqlite':before,'vectors':vectors,'counter_before':counter,'counter_after':provider.snapshot(),'responses':replies})
            return replies
        self.case('sqlite-state-filters','actual SQLite orphaned/retired facts filter positive hits; no invented support or annotations',filters)
        def missing_collection():
            col=self.cli('status')['state']['published_collection'];assert request(self.qurl,'/collections/'+col,'DELETE')[0]==200
            before=provider.snapshot();st=self.cli('status');assert not st['verified_healthy'] and not st['health']['exists']
            code,r=request(base,query);assert code==409,r
            assert provider.wait_idle();assert_embedding_delta(before,provider.snapshot())
            repaired=self.cli('sync');assert repaired['embedded_texts']==0 and repaired['published']
            return {'status':st,'search_status':code,'repair':repaired,'inventory':self.verify()}
        self.case('whole-collection-loss','honest missing status/search 409 before provider call; sync republish uses cache',missing_collection)
        child.send_signal(signal.SIGTERM);assert child.wait(5)==0
        self.save('provider-complete-ledger',provider.snapshot());self.save('qdrant-proxy-complete-ledger',proxy.events)
        assert_bounded_provider(provider.snapshot(),2,1)
        self.report['remaining_inventory']=self.inventory()

    def compose_checks(self):
        # All image identities are resolved locally; missing prerequisites are errors,
        # never invitations to pull. Nothing replaces the user's app image tag.
        for line in (self.source/'Dockerfile').read_text().splitlines():
            if line.startswith('FROM '):self.command(['docker','image','inspect',line.split()[1]])
        self.tag=self.id+':acceptance'
        self.command(['docker','build','--pull=false','--network','none','--tag',self.tag,self.source],timeout=110)
        image=json.loads(self.command(['docker','image','inspect',self.tag])['stdout'])[0]
        self.report['application_image']=image
        python=json.loads(self.command(['docker','image','inspect','python:3.12-slim'])['stdout'])[0]['Id']
        data=self.work/'compose-app';data.mkdir();qdata=self.work/'compose-qdrant';qdata.mkdir()
        # Native setup uses actual migrated repository rendering; no guessed seed API.
        docs=self.probe('seed',data/'app.db');(self.out/'documents.json').write_text(json.dumps(docs))
        env=dict(self.env,FLH_DATA_DIR=str(data),FLH_QDRANT_DIR=str(qdata),FLH_UID=str(os.getuid()),FLH_GID=str(os.getgid()),
                 FLH_HOST_PORT=str(port()),FLH_QDRANT_PORT=str(port()),EMBEDDING_BASE_URL='http://embeddings:9000',
                 QDRANT_URL='http://qdrant:6333',QDRANT_COLLECTION_PREFIX='flh043_compose',EMBEDDING_MODEL_ID='fixture/compose',DB_PATH='/data/app.db')
        self.used_ports.extend([int(env['FLH_HOST_PORT']),int(env['FLH_QDRANT_PORT'])])
        empty=self.work/'compose.env';empty.touch()
        override=self.work/'compose.override.yaml'
        # JSON is valid YAML; argument arrays preserve file paths without shell interpolation.
        override.write_text(json.dumps({'services':{'app':{'image':self.tag},'embeddings':{
            'image':python,'user':f'{os.getuid()}:{os.getgid()}',
            'entrypoint':['python','-B','/fixture/compose_embeddings.py'],
            'environment':{'PYTHONPATH':'/fixture'},
            'volumes':[f'{HERE}:/fixture:ro',f'{self.out}:/inputs:ro',f'{self.out}:/output']}}}))
        self.compose=['docker','compose','--env-file',str(empty),'--project-name',self.id,'-f',str(self.source/'compose.yaml'),'-f',str(override),'--profile','semantic']
        self.compose_env=env
        self.command(self.compose+['config','--format','json'],env)
        self.command(self.compose+['up','--no-build','--pull','never','-d'],env)
        self.report['compose_containers']=json.loads(self.command(['docker','inspect',self.id+'-app-1',self.id+'-qdrant-1',self.id+'-embeddings-1'])['stdout'])
        for _ in range(80):
            if (self.out/'compose-provider.json').exists():break
            time.sleep(.1)
        for _ in range(40):
            r=self.command(self.compose+['exec','-T','app','wget','-q','-O','-','http://127.0.0.1:8080/readyz'],env,check=False)
            if r['exit']==0:break
            time.sleep(.1)
        else:raise AssertionError('Compose app not ready')
        def ledger():
            for _ in range(20):
                try:r=json.loads((self.out/'compose-provider.json').read_text())
                except (OSError,ValueError):time.sleep(.05);continue
                if r['active']==0:return r
                time.sleep(.05)
            raise AssertionError('Compose provider not idle')
        before=ledger()
        build=json.loads(self.command(self.compose+['exec','-T','app','/app/semantic-index','-json','-batch','2','build'],env)['stdout'])
        time.sleep(.15);after=ledger()
        assert_embedding_delta(before,after,expected_documents=[text_digest(t) for t in dict.fromkeys(d['Text'] for d in docs)])
        self.save('compose-build-counters',{'before':before,'after':after,'report':build})
        st=json.loads(self.command(self.compose+['exec','-T','app','/app/semantic-index','-json','status'],env)['stdout']);assert st['verified_healthy']
        # Independent inventory reader uses the actual host-published Qdrant.
        native=dict(self.env,DB_PATH=str(data/'app.db'),QDRANT_URL='http://127.0.0.1:'+env['FLH_QDRANT_PORT'],QDRANT_COLLECTION_PREFIX='flh043_compose',EMBEDDING_MODEL_ID='fixture/compose')
        original=self.qurl;self.qurl=native['QDRANT_URL']
        try:inventory=self.verify(native)
        finally:self.qurl=original
        before_db=snapshot(data/'app.db');before=ledger()
        response=json.loads(self.command(self.compose+['exec','-T','app','wget','-q','-O','-','http://127.0.0.1:8080/knowledge-library/semantic-search?q=flh043%20query'],env)['stdout'])
        time.sleep(.15);after=ledger();assert_embedding_delta(before,after,expected_queries=[text_digest('flh043 query')]);assert response['index']['health_verified'] is False
        assert before_db==snapshot(data/'app.db')
        self.command(self.compose+['stop','qdrant'],env)
        outage=self.command(self.compose+['exec','-T','app','wget','-S','-O','-','http://127.0.0.1:8080/knowledge-library/semantic-search?q=flh043%20query'],env,check=False)
        assert outage['exit']!=0 and '502 Bad Gateway' in outage['stderr'],outage
        status=json.loads(self.command(self.compose+['exec','-T','app','/app/semantic-index','-json','status'],env)['stdout'])
        assert not status['verified_healthy'] and status['health_error']=='vector index unavailable'
        keyword=self.command(self.compose+['exec','-T','app','wget','-q','-O','-','http://127.0.0.1:8080/knowledge-library/concepts'],env)
        assert len(json.loads(keyword['stdout'])['results'])==4
        self.command(self.compose+['start','qdrant'],env)
        for _ in range(50):
            try:
                if request(native['QDRANT_URL'],'/')[0]==200:break
            except OSError:pass
            time.sleep(.1)
        before=ledger()
        resumed=json.loads(self.command(self.compose+['exec','-T','app','/app/semantic-index','-json','sync'],env)['stdout'])
        time.sleep(.15);assert_embedding_delta(before,ledger());assert resumed['verified_unchanged']
        self.save('compose-provider-complete-ledger',ledger())
        self.report['compose_storage']={'app_db':{'uid':(data/'app.db').stat().st_uid,'gid':(data/'app.db').stat().st_gid,'mode':oct((data/'app.db').stat().st_mode&0o777)},'qdrant_storage':self.command(['docker','exec',self.id+'-qdrant-1','sh','-c','id; ls -ld /qdrant/storage /qdrant/storage/collections'])['stdout']}
        return {'build':build,'status':st,'inventory':inventory,'search':response,'outage':outage,'resume':resumed,'storage':self.report['compose_storage']}

    def cleanup(self):
        if hasattr(self,'qurl'):
            code, names=request(self.qurl,'/collections')
            assert code==200,names
            complete={}
            for collection in names['result']['collections']:
                name=collection['name'];offset=None;points=[]
                while True:
                    body={'limit':2,'with_vector':True,'with_payload':True}
                    if offset is not None:body['offset']=offset
                    code,page=request(self.qurl,'/collections/'+name+'/points/scroll','POST',body)
                    assert code==200,page
                    points.extend(page['result']['points']);offset=page['result']['next_page_offset']
                    if offset is None:break
                complete[name]=points
            self.save('final-all-qdrant-points',complete)
            self.save('final-all-sqlite-rows',snapshot(self.env['DB_PATH']))
        for p,handle,identity,cmdline in self.children:
            if p.poll() is None:
                current=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
                assert current==identity,'child PID identity changed'
                p.terminate()
                try:p.wait(12)
                except subprocess.TimeoutExpired:p.kill();p.wait(3)
            handle.close()
            self.report['cleanup'].append({'pid':p.pid,'exit':p.returncode,'reaped':p.poll() is not None})
        if self.compose:
            self.command(self.compose+['down','--remove-orphans','--timeout','10'],self.compose_env)
            for args in [['docker','ps','-a','--filter','label=com.docker.compose.project='+self.id,'--format','{{.ID}}'],['docker','network','ls','--filter','label=com.docker.compose.project='+self.id,'--format','{{.ID}}']]:
                r=self.command(args);assert not r['stdout'].strip()
            self.report['cleanup'].append({'compose_project':self.id,'containers_and_networks_absent':True})
        for name in self.containers:
            self.command(['docker','rm','--force',name])
            r=self.command(['docker','ps','-a','--filter','name=^/'+name+'$','--format','{{.ID}}']);assert not r['stdout'].strip()
            self.report['cleanup'].append({'container':name,'absent':True})
        if self.tag:self.command(['docker','image','rm',self.tag])
        # Qdrant uses UID 0 in the pinned image; remove root-owned nested data
        # only inside this task's exact bind mount, using an already cached base.
        alpine=json.loads(self.command(['docker','image','inspect','alpine:3.22.2'])['stdout'])[0]['Id']
        for directory in [self.work/'qdata',self.work/'compose-qdrant']:
            if directory.exists():self.command(['docker','run','--rm','--pull=never','--network','none','--mount',f'type=bind,source={directory},target=/owned','--entrypoint','/bin/sh',alpine,'-c','rm -rf /owned/* /owned/.[!.]* /owned/..?*'])
        shutil.rmtree(self.work)
        for number in sorted(set(self.used_ports)):
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                sock.bind(('127.0.0.1',number))
        self.report['cleanup'].append({'freed_loopback_ports':sorted(set(self.used_ports))})
        self.report['cleanup'].append({'temporary_root_removed':not self.work.exists(),'shared_build_cache_retained':True})
        (self.out/'report.json').write_text(json.dumps(self.report,indent=2,default=str))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--extra-only',action='store_true');args=parser.parse_args()
    destination=args.output.resolve()
    if destination.exists() or ROOT in destination.parents:raise ValueError('new external output directory required')
    r=Runner(destination)
    try:
        r.setup()
        with FakeEmbeddings(dimensions=8,gate_timeout=12) as provider, Proxy(r.qurl) as proxy:
            r.used_ports.extend([urllib.parse.urlparse(provider.base_url).port,urllib.parse.urlparse(proxy.base).port])
            if args.extra_only:r.extra(provider,proxy)
            else:r.scenarios(provider,proxy)
        if not args.extra_only:
            tests=r.command(['go','test','-json','./internal/application','./internal/storage/sqlite','./internal/vectorindex','./internal/embedding','./internal/transport/http','./internal/config','./cmd/semantic-index','-run','Test.*(Semantic|Qdrant|HTTPProvider|Embedding)','-count=1'],dict(r.env,FLH_QDRANT_URL=r.qurl))
            r.save('integrated-go-tests',tests)
            r.case('actual-compose-semantic-profile','populated publication/search, writable storage, packaged CLI, Qdrant outage with keyword service and cached recovery',r.compose_checks)
    except Exception as exc:
        r.report['fatal']=repr(exc);print('FATAL',repr(exc),flush=True)
    finally:
        try:r.cleanup()
        except Exception as exc:
            r.report['cleanup_error']=repr(exc);(destination/'report.json').write_text(json.dumps(r.report,indent=2,default=str));raise
    failures=[c for c in r.report['cases'] if c['result']=='FAIL']
    return 1 if failures or r.report.get('fatal') else 0

if __name__=='__main__':raise SystemExit(main())
