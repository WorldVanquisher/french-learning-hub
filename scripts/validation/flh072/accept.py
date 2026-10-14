#!/usr/bin/env python3
"""FLH-072 real production server/CLI + real cached Qdrant, fake embeddings.
Mechanical acceptance only; no relevance/quality or browser DOM claim.
"""
import argparse
import contextlib
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts/demo/flh060'))
spec=importlib.util.spec_from_file_location('flh072_demo',ROOT/'scripts/demo/flh060/demo.py')
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
# Cache/environment plumbing only. No demo/production file or provider/ranking changes.
original_env=demo.child_env
def child_env(cfg,work,extra=None):
    return dict(original_env(cfg,work,extra),GOCACHE='/tmp/flh049-go-cache',GOPROXY='off',GOSUMDB='off')
demo.child_env=child_env
os.environ.update(GOCACHE='/tmp/flh049-go-cache',GOPROXY='off',GOSUMDB='off')
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')


def http(url,method='GET',body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={'Content-Type':'application/json'})
    try:r=OPENER.open(req,timeout=40)
    except urllib.error.HTTPError as e:r=e
    with r:
        raw=r.read(16<<20);status=r.code
    try:decoded=json.loads(raw)
    except ValueError:decoded={'raw':raw.decode(errors='replace')}
    return status,decoded,raw


class Acceptance:
    def __init__(self,out,work,port):
        self.out,self.work,self.port=out,work,port;self.seq=0;self.checks=[];self.oracle_cases=[]
        self.base=f'http://127.0.0.1:{port}'
        self.gw=f'http://127.0.0.1:{port+1}'
        self.qdrant=f'http://127.0.0.1:{port+3}'
        self.db=work/'flh034/demo.db'
        self.proxy=None;self.proxy_thread=None
    def record(self,name,expected,actual):
        self.checks.append({'name':name,'expected':expected,'actual':actual,'pass':expected==actual})
    def command(self,*args):
        self.seq+=1;stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):code=demo.main(list(map(str,args)))
        save(self.out/f'command-{self.seq:03d}.json',{'command':['python3','-B','scripts/demo/flh060/demo.py',*map(str,args)],'exit':code,'stdout':stdout.getvalue(),'stderr':stderr.getvalue(),'cache_env':'GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off'})
        assert code==0,(args,stdout.getvalue(),stderr.getvalue())
        return code
    def request(self,name,path,expected=200,method='GET',body=None):
        self.seq+=1;status,data,raw=http(self.base+path,method,body)
        (self.out/f'http-{self.seq:03d}-{name}.body').write_bytes(raw)
        save(self.out/f'http-{self.seq:03d}-{name}.json',{'path':path,'method':method,'status':status,'body':data})
        self.record(name+' status',expected,status)
        return data
    def state(self):return http(self.gw+'/gateway/state')[1]
    def snapshot(self):
        with sqlite3.connect(self.db) as c:return hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
    def publication(self):
        with sqlite3.connect(self.db) as c:return c.execute('SELECT published_collection FROM semantic_index_spaces').fetchone()[0]
    def index(self,op):
        _,cfg=demo.open_work(self.work)
        result=demo.do_index(self.work,cfg,op)
        self.seq+=1;save(self.out/f'index-{self.seq:03d}-{op}.json',result)
        assert result['exit']==0,result
        return result
    def compare(self,text,depth=15,limit=5,state='all'):
        before=self.snapshot();counts=self.state();pub=self.publication()
        params=urllib.parse.urlencode({'q':text,'state':state,'limit':depth})
        kw=self.request('keyword','/knowledge-library/concepts?'+params)
        sem=self.request('semantic','/knowledge-library/semantic-search?'+params)
        h=self.request('hybrid','/knowledge-library/hybrid-search?'+urllib.parse.urlencode({'q':text,'state':state,'limit':limit,'depth':depth}))
        krows,srows=kw['results'],sem['results']
        km={};sm={};dupes=0
        for rank,row in enumerate(krows,1):
            cid=row['concept']['id']
            if cid in km:dupes+=1
            else:km[cid]=(rank,row)
        for rank,row in enumerate(srows,1):
            cid=row['concept']['id']
            if cid in sm:dupes+=1
            else:sm[cid]=(rank,row)
        scores={cid:(1/(60+km[cid][0]) if cid in km else 0)+(1/(60+sm[cid][0]) if cid in sm else 0) for cid in km.keys()|sm.keys()}
        ordered=sorted(scores,key=lambda cid:(-scores[cid],cid))
        actual=[r['concept']['id'] for r in h['results']]
        assert actual==ordered[:limit],(text,state,actual,ordered)
        assert h['total_candidates']==len(ordered) and h['truncated']==(len(ordered)>limit)
        assert h['components']['keyword']['returned']==len(krows) and h['components']['semantic']['returned']==len(srows)
        assert h['dropped_after_fusion']['duplicate_component_ids']==dupes
        assert h['policy']=={'version':'concept_hybrid_rrf_v1','rrf_k':60,'weights':{'keyword':1,'semantic':1},'tie_break':'concept_id_ascending'}
        for row in h['results']:
            cid=row['concept']['id'];assert math.isclose(row['fused_score'],scores[cid],rel_tol=0,abs_tol=1e-14)
            assert row['sources']==(['keyword'] if cid in km else [])+(['semantic'] if cid in sm else [])
            if cid in km:
                rank,evidence=km[cid];assert row['keyword']=={'rank':rank,'match_tier':evidence['match_tier'],'matched_fields':evidence['matched_fields']}
            else:assert row['keyword'] is None
            if cid in sm:
                rank,evidence=sm[cid];assert row['semantic']=={'rank':rank,'similarity':evidence['similarity']}
            else:assert row['semantic'] is None
            if state!='all':assert row['concept']['state']==state
        after=self.state()
        assert self.snapshot()==before and self.publication()==pub
        assert after['posts_forwarded']-counts['posts_forwarded']==2
        assert after['positions_by_kind']['search_query']-counts['positions_by_kind']['search_query']==2
        assert after['positions_by_kind']['concept_document']==counts['positions_by_kind']['concept_document']
        ties=sum(scores[a]==scores[b] for a,b in zip(ordered,ordered[1:]))
        self.oracle_cases.append({'query':text,'state':state,'depth':depth,'limit':limit,'expected_ids':ordered[:limit],'actual_ids':actual,'scores':scores,'ties':ties,'duplicates':dupes,'read_only':True})
        return h,sem
    def launch_server(self,extra):
        _,cfg=demo.open_work(self.work);demo.stop_role(self.work,cfg,'server')
        env=demo.app_env(cfg,self.work);env.update(extra)
        demo.launch(self.work,cfg,'server',[str(self.work/'flh034/server'),'-web-dir',cfg['web_dist']],demo.child_env(cfg,self.work,env),self.port)
        demo.wait_ready(self.base+'/readyz','FLH072 server',20)
    def start_proxy(self):
        parent=self;self.replace_count=0;self.proxy_calls=[]
        class Proxy(BaseHTTPRequestHandler):
            def do_GET(self):self.forward()
            def do_POST(self):self.forward()
            def do_PUT(self):self.forward()
            def do_DELETE(self):self.forward()
            def log_message(self,*args):pass
            def forward(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                if self.command=='POST' and self.path.endswith('/points/query') and parent.replace_count:
                    parent.replace_count-=1
                    result=parent.index('rebuild')
                    assert result['report']['embedded_texts']==0
                request=urllib.request.Request(parent.qdrant+self.path,data=body if body else None,method=self.command,headers={'Content-Type':'application/json'})
                try:r=OPENER.open(request,timeout=30)
                except urllib.error.HTTPError as e:r=e
                with r:raw=r.read(16<<20);status=r.code
                parent.proxy_calls.append({'method':self.command,'path':self.path,'status':status})
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.proxy=ThreadingHTTPServer(('127.0.0.1',self.port+10),Proxy)
        self.proxy_thread=threading.Thread(target=self.proxy.serve_forever);self.proxy_thread.start()
        self.launch_server({'QDRANT_URL':f'http://127.0.0.1:{self.port+10}'})
    def run(self):
        self.command('setup',self.work,'--mode','fake','--web-dist',self.out/'web-dist','--port-base',self.port)
        self.request('root','/');self.request('ready','/readyz')
        _,_,html=http(self.base+'/')
        assets=re.findall(r'(?:src|href)="(/assets/[^\"]+)"',html.decode());assert assets
        for path in assets:self.request('asset',path)
        before=self.state()
        self.request('unbuilt-hybrid','/knowledge-library/hybrid-search?q=depuis',409)
        self.request('unbuilt-semantic','/knowledge-library/semantic-search?q=depuis',409)
        self.request('unbuilt-keyword','/knowledge-library/concepts?q=depuis')
        self.record('unbuilt makes zero provider calls',before['posts_forwarded'],self.state()['posts_forwarded'])
        built=self.index('build');self.record('index documents',15,built['report']['embedded_texts'])
        self.record('index query positions',0,self.state()['positions_by_kind']['search_query'])
        # Root and /api must use the same real production services.
        root=self.request('root-hybrid','/knowledge-library/hybrid-search?q=depuis&limit=5&depth=15')
        api=self.request('api-hybrid','/api/knowledge-library/hybrid-search?q=depuis&limit=5&depth=15')
        self.record('root/api response parity',root,api)
        for text in ['subjunctive','depuis','past','quantity','question','zzunmatched']:
            self.compare(text)
            self.compare(text,depth=1,limit=1)
        for state in ['active','orphaned','retired']:
            self.compare('depuis',depth=50,limit=50,state=state)
        c=self.state()
        for query in ['q=','q=%C3%A0','q=depuis&depth=0','q=depuis&depth=51','q=depuis&limit=51','q=depuis&limit=5&depth=4','q=depuis&state=bad']:
            self.request('invalid','/knowledge-library/hybrid-search?'+query,400)
        self.request('method','/knowledge-library/hybrid-search?q=depuis',405,method='POST',body={})
        self.record('validation no provider calls',c['posts_forwarded'],self.state()['posts_forwarded'])
        self.command('offline',self.work,'on')
        self.request('provider-down-hybrid','/knowledge-library/hybrid-search?q=depuis',502)
        self.request('provider-down-semantic','/knowledge-library/semantic-search?q=depuis',502)
        self.request('provider-down-keyword','/knowledge-library/concepts?q=depuis')
        self.command('offline',self.work,'off')
        _,cfg=demo.open_work(self.work);demo.stop_qdrant(self.work,cfg)
        self.request('qdrant-down-hybrid','/knowledge-library/hybrid-search?q=depuis',502)
        self.request('qdrant-down-semantic','/knowledge-library/semantic-search?q=depuis',502)
        self.request('qdrant-down-keyword','/knowledge-library/concepts?q=depuis')
        demo.start_qdrant(self.work,cfg)
        # Stale identity and retirement, mutated only in this synthetic fixture.
        h,sem=self.compare('depuis',limit=15);victim=sem['results'][0]['concept']['id']
        with sqlite3.connect(self.db) as conn:
            target,lifecycle=conn.execute('SELECT target,lifecycle_state FROM knowledge_concepts WHERE id=?',(victim,)).fetchone()
            conn.execute('UPDATE knowledge_concepts SET target=? WHERE id=?',(target+' flh072stale',victim))
        _,stale=self.compare('depuis',limit=15)
        self.record('stale hit counted',True,stale['skipped']['stale']>=1)
        kw=self.request('stale-keyword','/knowledge-library/concepts?q=flh072stale')
        self.record('stale identity keyword discoverable',True,any(r['concept']['id']==victim for r in kw['results']))
        with sqlite3.connect(self.db) as conn:conn.execute('UPDATE knowledge_concepts SET target=?,lifecycle_state=? WHERE id=?',(target,'retired',victim))
        self.compare('depuis',depth=50,limit=50,state='retired');self.compare('depuis',depth=50,limit=50,state='active')
        with sqlite3.connect(self.db) as conn:conn.execute('UPDATE knowledge_concepts SET lifecycle_state=? WHERE id=?',(lifecycle,victim))
        # Actual duplicated Qdrant point payload proves component deduplication.
        pub=self.publication();points=http(self.qdrant+'/collections/'+pub+'/points/scroll','POST',{'limit':100,'with_vector':True,'with_payload':True})[1]['result']['points']
        point=next(p for p in points if p['payload'].get('concept_id')==victim);clone=copy.deepcopy(point);clone['id']='00000000-0000-4000-8000-000000000072'
        assert http(self.qdrant+'/collections/'+pub+'/points?wait=true','PUT',{'points':[clone]})[0]==200
        dup,_=self.compare('depuis',depth=50,limit=50)
        self.record('foreign point removed before fusion',0,dup['dropped_after_fusion']['duplicate_component_ids'])
        self.record('foreign point counted incompatible',True,dup['components']['semantic']['skipped']['incompatible']>=1)
        repaired=self.index('sync');self.record('sync repairs from cache zero embeddings',0,repaired['report']['embedded_texts'])
        unchanged=self.index('sync');self.record('unchanged sync verified',True,unchanged['report']['verified_unchanged'])
        # Publication survives restart; cache survives unchanged sync/rebuild.
        pub=self.publication();counts=self.state();self.command('stop',self.work);self.command('start',self.work)
        self.record('restart publication persisted',pub,self.publication())
        self.record('restart counters persisted',counts['posts_forwarded'],self.state()['posts_forwarded'])
        self.compare('depuis');rebuilt=self.index('rebuild');self.record('rebuild zero embeddings',0,rebuilt['report']['embedded_texts'])
        # Actual incompatible Qdrant collection, then cache-only repair.
        pub=self.publication();assert http(self.qdrant+'/collections/'+pub,'DELETE')[0]==200
        assert http(self.qdrant+'/collections/'+pub,'PUT',{'vectors':{'size':4,'distance':'Cosine'}})[0]==200
        self.request('incompatible-hybrid','/knowledge-library/hybrid-search?q=depuis',409)
        self.request('incompatible-semantic','/knowledge-library/semantic-search?q=depuis',409)
        self.request('incompatible-keyword','/knowledge-library/concepts?q=depuis')
        repaired=self.index('sync');self.record('incompatible sync zero embeddings',0,repaired['report']['embedded_texts'])
        # Rebuild the real publication inside a forwarding barrier; actual old query gets 404.
        self.start_proxy()
        for times,status in [(1,200),(2,500)]:
            self.replace_count=times;before=self.state();old=self.publication();self.proxy_calls=[]
            result=self.request('publication-replaced-'+str(times),'/knowledge-library/hybrid-search?q=depuis&depth=15&limit=5',status)
            after=self.state();self.record('replacement '+str(times)+' one query embedding',1,after['posts_forwarded']-before['posts_forwarded'])
            self.record('replacement '+str(times)+' no document embedding',before['positions_by_kind']['concept_document'],after['positions_by_kind']['concept_document'])
            self.record('replacement '+str(times)+' hook consumed',0,self.replace_count)
            if status==200:self.record('replacement uses latest collection',self.publication(),result['components']['semantic']['index']['collection'])
            else:self.record('second replacement no fallback',False,'results' in result)
            save(self.out/('publication-'+str(times)+'.json'),{'old':old,'new':self.publication(),'proxy_calls':self.proxy_calls,'response':result})
        self.request('keyword-after-publication-failure','/knowledge-library/concepts?q=depuis')
        self.record('ties observed',True,any(c['ties'] for c in self.oracle_cases))
        self.record('all oracle cases read-only',True,all(c['read_only'] for c in self.oracle_cases))
        save(self.out/'final-provider-state.json',self.state())
        save(self.out/'fake-service-metrics.json',http(f'http://127.0.0.1:{self.port+2}/metrics')[1])

    def followup(self):
        self.command('start',self.work)
        # Corrected foreign-point check: ID/payload mismatch is rejected upstream of fusion.
        _,sem=self.compare('depuis',depth=50,limit=50)
        victim=sem['results'][0]['concept']['id'];pub=self.publication()
        points=http(self.qdrant+'/collections/'+pub+'/points/scroll','POST',{'limit':100,'with_vector':True,'with_payload':True})[1]['result']['points']
        clone=copy.deepcopy(next(p for p in points if p['payload']['concept_id']==victim))
        clone['id']='00000000-0000-4000-8000-000000000072'
        assert http(self.qdrant+'/collections/'+pub+'/points?wait=true','PUT',{'points':[clone]})[0]==200
        hybrid,_=self.compare('depuis',depth=50,limit=50)
        self.record('foreign point counted incompatible',True,hybrid['components']['semantic']['skipped']['incompatible']>=1)
        self.record('foreign point never double-counts Concept',0,hybrid['dropped_after_fusion']['duplicate_component_ids'])
        self.record('foreign point results deduplicated',len(hybrid['results']),len({r['concept']['id'] for r in hybrid['results']}))
        result=self.index('sync');self.record('foreign point repair zero embeddings',0,result['report']['embedded_texts'])
        self.start_proxy();self.replace_count=2;before=self.state();old=self.publication();self.proxy_calls=[]
        result=self.request('publication-replaced-twice','/knowledge-library/hybrid-search?q=depuis&depth=15&limit=5',500)
        after=self.state()
        self.record('double replacement exactly one query embedding',1,after['posts_forwarded']-before['posts_forwarded'])
        self.record('double replacement zero document embeddings',before['positions_by_kind']['concept_document'],after['positions_by_kind']['concept_document'])
        self.record('double replacement no fallback',False,'results' in result)
        self.record('two replacement hooks consumed',0,self.replace_count)
        save(self.out/'publication-double.json',{'old':old,'new':self.publication(),'proxy_calls':self.proxy_calls,'response':result})
        self.request('keyword-after-failure','/knowledge-library/concepts?q=depuis')
        self.request('semantic-after-replacement','/knowledge-library/semantic-search?q=depuis')
        self.request('hybrid-after-replacement','/knowledge-library/hybrid-search?q=depuis')
        save(self.out/'final-provider-state.json',self.state())
        save(self.out/'fake-service-metrics.json',http(f'http://127.0.0.1:{self.port+2}/metrics')[1])


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--port-base',type=int,default=19720);ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    assert a.out.is_absolute() and a.work.is_absolute() and a.out.parent==Path('/tmp') and a.work.parent==Path('/tmp')
    assert ((a.out/'web-dist/index.html').is_file() and not a.work.exists()) or (a.resume and (a.work/'demo.json').is_file())
    runner=Acceptance(a.out,a.work,a.port_base)
    try:
        if a.resume:runner.followup()
        else:runner.run()
    finally:
        if (a.work/'demo.json').exists():
            with contextlib.redirect_stdout(io.StringIO()):code=demo.main(['stop',str(a.work)])
            save(a.out/'cleanup.json',{'stop_exit':code,'remaining_owned_processes':demo.scan(a.work,demo.open_work(a.work)[1]),'retained_work':str(a.work)})
        if runner.proxy:
            runner.proxy.shutdown();runner.proxy_thread.join(10);runner.proxy.server_close()
        save(a.out/'checks.json',runner.checks);save(a.out/'rrf-oracle.json',runner.oracle_cases)
    print(json.dumps({'checks':len(runner.checks),'failed':[c for c in runner.checks if not c['pass']],'oracle_cases':len(runner.oracle_cases)},indent=2))
    return 1 if any(not c['pass'] for c in runner.checks) else 0


if __name__=='__main__':sys.exit(main())
