#!/usr/bin/env python3
"""Independent FLH-067 acceptance: fresh processes, synthetic state, fake AWS only.
Exit 1 means an acceptance expectation failed; inspect results, not exit alone.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
AWS = ROOT/'tools/cloud/aws'
sys.path.insert(0,str(AWS))
from flh_aws import cli, fakes, s3store
from flh_aws.ledger import Ledger


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n')


def read(path):
    return json.loads(path.read_text())


def worker(mode,argv):
    # Refuse even accidental network access in all independent worker cases.
    def audit(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.bind','socket.getaddrinfo'):
            raise RuntimeError('FLH067 forbids network access')
    sys.addaudithook(audit)
    state=Path(argv[argv.index('--state')+1])
    if mode.startswith('auth-'):
        outcome=mode.removeprefix('auth-')
        calls=[]
        class Session:
            def __init__(self,**kw):
                if outcome=='profile':
                    raise type('ProfileNotFound',(Exception,),{})('SYNTHETIC_PROVIDER_OUTPUT_MUST_NOT_ESCAPE')
            def get_credentials(self):
                if outcome=='dependency':
                    raise type('MissingDependencyException',(Exception,),{})('SYNTHETIC_PROVIDER_OUTPUT_MUST_NOT_ESCAPE')
                if outcome=='missing': return None
                class Credentials:
                    method='synthetic-login'
                    def get_frozen_credentials(self):
                        raise type('LoginRefreshRequired',(Exception,),{})('SYNTHETIC_SECRET_VALUE_MUST_NOT_ESCAPE')
                return Credentials()
            def client(self,*a,**kw):
                calls.append(a[0]);raise AssertionError('client construction before credential resolution')
        boto=types.ModuleType('boto3');boto.Session=Session
        config=types.ModuleType('botocore.config');config.Config=lambda **kw:kw
        sys.modules.update({'boto3':boto,'botocore':types.ModuleType('botocore'),'botocore.config':config})
    if mode=='crash-create':
        original=s3store.save_resources
        def save(st,res):
            if res.get('stack',{}).get('id'): os._exit(86)
            original(st,res)
        s3store.save_resources=save
    if mode=='crash-invoke':
        original=fakes.FakeBedrockRuntime.invoke_model
        def invoke(self,*a,**kw):
            original(self,*a,**kw);os._exit(87)
        fakes.FakeBedrockRuntime.invoke_model=invoke
    # Keep deterministic delayed-deletion tests bounded; no real sleep/wait.
    s3store.STACK_POLL_SECONDS=0
    s3store.STACK_TIMEOUT_SECONDS=0 if mode=='delete-timeout' else 1
    if mode=='create-foreign-answer':
        original=fakes.FakeCloudFormation.create_stack
        def create(self,*a,**kw):
            result=original(self,*a,**kw)
            result['StackId']=result['StackId'].replace(':000000000000:',':111122223333:')
            return result
        fakes.FakeCloudFormation.create_stack=create
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err): code=cli.main(argv)
    print(json.dumps({'cli_exit':code,'stdout':out.getvalue(),'stderr':err.getvalue(),
        'data':json.loads(out.getvalue()) if out.getvalue().strip() else None,
        'client_constructions':calls if mode.startswith('auth-') else None}))
    return 0


class Harness:
    def __init__(self,out):
        self.out=out;self.results=[];self.seq=0
        self.empty=out/'synthetic-auth';self.empty.mkdir()
        (self.empty/'config').write_text('[profile flh067-synthetic]\nregion=ca-central-1\nlogin_session=arn:aws:iam::000000000000:user/synthetic\n')
        (self.empty/'credentials').write_text('')
        (self.empty/'cache').mkdir()
        self.env={'PATH':os.environ.get('PATH',''),'PYTHONNOUSERSITE':'1','AWS_CONFIG_FILE':str(self.empty/'config'),
            'AWS_SHARED_CREDENTIALS_FILE':str(self.empty/'credentials'),'AWS_LOGIN_CACHE_DIRECTORY':str(self.empty/'cache'),
            'AWS_EC2_METADATA_DISABLED':'true','AWS_DEFAULT_REGION':'ca-central-1'}
    def invoke(self,state,*argv,mode='normal',process_exit=0):
        self.seq+=1
        command=[sys.executable,'-B',str(Path(__file__).resolve()),'worker','--mode',mode,'--',argv[0],'--state',str(state),*map(str,argv[1:])]
        p=subprocess.run(command,env=self.env,cwd=ROOT,capture_output=True,text=True,timeout=15)
        record={'argv':command,'process_expected_exit':process_exit,'process_actual_exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        write(self.out/'commands'/f'{self.seq:03d}.json',record)
        assert p.returncode==process_exit,record
        return json.loads(p.stdout) if p.stdout else {'process_exit':p.returncode}
    def state(self,name,backend='fake'):
        state=self.out/name;assert self.invoke(state,'init','--backend',backend)['cli_exit']==0
        return state
    def faults(self,state,values): write(state/'fake-aws/faults.json',values)
    def counts(self,state): return fakes.counters(state/'fake-aws')
    def resource(self,state): return read(state/'resources.json')
    def criterion(self,area,name,expected,actual):
        self.results.append({'area':area,'scenario':name,'expected':expected,'actual':actual,'status':'PASS' if actual==expected else 'FAIL'})
    def deploy(self,state,**kwargs): return self.invoke(state,'deploy','--region','ca-central-1',**kwargs)
    def smoke(self,state,*extra,**kwargs):
        return self.invoke(state,'titan-smoke','--region','ca-central-1','--dimensions','256',*extra,**kwargs)
    def auth(self):
        for scenario,category in [('dependency','missing_dependency'),('missing','no_credentials'),('expired','expired_credentials'),('profile','profile_not_found')]:
            state=self.state('auth-'+scenario,'aws')
            result=self.invoke(state,'deploy','--profile','flh067-synthetic','--region','ca-central-1','--allow-live',mode='auth-'+scenario)
            expected={'exit':2,'category':True,'constructed':0,'resources':False,'calls':0,'leak':False}
            actual={'exit':result['cli_exit'],'category':category in result['stderr'],'constructed':len(result['client_constructions']),
                'resources':(state/'resources.json').exists(),'calls':len(Ledger(state).read()['calls']),
                'leak':'MUST_NOT_ESCAPE' in result['stderr']+result['stdout']}
            self.criterion('authentication',scenario,expected,actual)
        state=self.state('auth-no-profile','aws')
        result=self.invoke(state,'deploy','--region','ca-central-1','--allow-live')
        self.criterion('authentication','missing explicit profile',{'exit':2,'resources':False,'calls':0},
            {'exit':result['cli_exit'],'resources':(state/'resources.json').exists(),'calls':len(Ledger(state).read()['calls'])})
    def receipts(self):
        for name,mode,fault,exitcode in [('success','normal',{},0),('lost','normal',{'create_stack':'lost'},4),('crash','crash-create',{},86),('foreign-answer','create-foreign-answer',{},1),('unreachable','normal',{'create_stack':'unreachable'},4)]:
            state=self.state('receipt-'+name);self.faults(state,fault)
            result=self.deploy(state,mode=mode,process_exit=86 if name=='crash' else 0)
            actualexit=result.get('cli_exit',result.get('process_exit'))
            initial=self.resource(state);write(state/'initial-receipt-copy.json',initial)
            again=self.deploy(state)
            self.faults(state,{})
            recover=self.invoke(state,'recover')
            final=self.resource(state)
            expected={'first_exit':exitcode,'replacement_exit':2,'creates':1,'full_id':name!='unreachable'}
            actual={'first_exit':actualexit,'replacement_exit':again['cli_exit'],'creates':self.counts(state).get('cfn.CreateStack',0),
                'full_id':bool(final['stack'].get('id'))}
            self.criterion('receipts',name,expected,actual)
            if name=='crash':
                self.criterion('durability','crash receipt',{'status':'CREATE_REQUESTING','id':False},
                    {'status':initial['stack']['status'],'id':bool(initial['stack'].get('id'))})
            if name=='unreachable':
                self.criterion('cleanup','missing-by-name + absent bucket',{'exit':4,'state':'verification_unavailable','delete_calls':0},
                    {'exit':recover['cli_exit'],'state':recover['data']['stack']['state'],'delete_calls':self.counts(state).get('cfn.DeleteStack',0)})
            else:
                cleaned=self.invoke(state,'cleanup')
                self.criterion('cleanup','receipt '+name+' cleanup',{'exit':0,'state':'deletion_confirmed'},
                    {'exit':cleaned['cli_exit'],'state':cleaned['data']['cleanup_state']})
        state=self.state('foreign-name-tags');self.deploy(state)
        res=self.resource(state);record=state/'fake-aws/cfn'/f"{res['stack']['name']}.json"
        cloud=read(record);cloud['Tags']=[{'Key':'flh:task','Value':'foreign'},{'Key':'flh:state-id','Value':'foreign'}];write(record,cloud)
        res['stack'].pop('id');write(state/'resources.json',res)
        recovered=self.invoke(state,'recover')
        self.criterion('receipts','foreign tags by name',{'exit':1,'adopted':False,'deletes':0},
            {'exit':recovered['cli_exit'],'adopted':bool(self.resource(state)['stack'].get('id')),'deletes':self.counts(state).get('cfn.DeleteStack',0)})
    def cleanup(self):
        for name,fault,expected in [('denied-read',{'describe_stacks':'AccessDenied'},(4,'verification_unavailable')),
                ('denied-delete',{'delete_stack':'AccessDenied'},(1,'resources_present')),
                ('delete-response-lost',{'delete_stack':'lost'},(4,'deletion_requested')),
                ('delete-delayed',{'delete_in_progress_polls':2},(0,'deletion_confirmed')),
                ('delete-timeout',{'delete_in_progress_polls':1000},(4,'deletion_requested'))]:
            state=self.state(name);self.deploy(state);self.faults(state,fault)
            result=self.invoke(state,'cleanup',mode='delete-timeout' if name=='delete-timeout' else 'normal')
            self.criterion('cleanup',name,list(expected),[result['cli_exit'],result['data']['cleanup_state']])
            self.faults(state,{})
            result=self.invoke(state,'cleanup')
            self.criterion('durability',name+' subsequent process', [0,'deletion_confirmed'],[result['cli_exit'],result['data']['cleanup_state']])
            counters=self.counts(state)
            repeat=self.invoke(state,'cleanup')
            self.criterion('cleanup',name+' repeated confirmation',{'exit':0,'no_calls':True},
                {'exit':repeat['cli_exit'],'no_calls':self.counts(state)==counters})
        state=self.state('legacy-deleted');self.deploy(state);self.invoke(state,'cleanup')
        original=self.resource(state);sid=original['stack']['id'];legacy=dict(original);legacy.pop('schema');legacy['stack']={'name':original['stack']['name'],'status':'DELETED'}
        write(state/'legacy-original.json',legacy);originalbytes=(state/'legacy-original.json').read_bytes();write(state/'resources.json',legacy)
        c=self.invoke(state,'cleanup')
        self.criterion('cleanup','old DELETED no StackId absent bucket',[4,'verification_unavailable'],[c['cli_exit'],c['data']['cleanup_state']])
        wrong=self.invoke(state,'recover','--stack-id',sid.replace(':000000000000:',':111122223333:'))
        self.criterion('receipts','foreign operator StackId',{'exit':1,'id':False}, {'exit':wrong['cli_exit'],'id':bool(self.resource(state)['stack'].get('id'))})
        c=self.invoke(state,'recover','--stack-id',sid)
        self.criterion('durability','old-state synthetic copy recovery',{'exit':0,'state':'deletion_confirmed','original_preserved':True},
            {'exit':c['cli_exit'],'state':c['data']['stack']['state'],'original_preserved':(state/'legacy-original.json').read_bytes()==originalbytes})
        state=self.state('unknown-object');self.deploy(state);res=self.resource(state)
        clients=fakes.fake_clients(state/'fake-aws','ca-central-1');clients.s3.put_object(Bucket=res['bucket'],Key='unrelated.txt',Body=b'synthetic',IfNoneMatch='*',ServerSideEncryption='AES256',ExpectedBucketOwner=res['account'])
        c=self.invoke(state,'cleanup')
        self.criterion('cleanup','unknown object untouched',{'exit':1,'state':'resources_present','stack_deletes':0,'object_exists':True},
            {'exit':c['cli_exit'],'state':c['data']['cleanup_state'],'stack_deletes':self.counts(state).get('cfn.DeleteStack',0),
             'object_exists':bool(clients.s3.head_object(Bucket=res['bucket'],Key='unrelated.txt',ExpectedBucketOwner=res['account']))})
    def foreign_id(self):
        a=self.state('foreign-id-owned');b=self.state('foreign-id-unrelated');self.deploy(a);self.deploy(b)
        owned=self.resource(a);foreign=self.resource(b)
        # Both stacks share a fake AWS account/world, like two stacks in one account.
        target=a/'fake-aws/cfn'/f"{foreign['stack']['name']}.json"
        write(target,read(b/'fake-aws/cfn'/f"{foreign['stack']['name']}.json"))
        import shutil
        shutil.copytree(b/'fake-aws/s3'/foreign['bucket'],a/'fake-aws/s3'/foreign['bucket'])
        owned['stack']['id']=foreign['stack']['id'];write(a/'resources.json',owned)
        result=self.invoke(a,'cleanup')
        self.criterion('ownership','persisted foreign StackId must refuse before write',{'delete_calls':0,'foreign_status':'CREATE_COMPLETE'},
            {'delete_calls':self.counts(a).get('cfn.DeleteStack',0),'foreign_status':read(target)['StackStatus']})
        write(a/'observed-cleanup.json',result)
    def foreign_tag(self):
        state=self.state('foreign-recorded-tags');self.deploy(state)
        res=self.resource(state);record=state/'fake-aws/cfn'/f"{res['stack']['name']}.json"
        cloud=read(record)
        cloud['Tags']=[{'Key':'flh:task','Value':'unrelated'},{'Key':'flh:state-id','Value':'another-state'}]
        write(record,cloud)
        result=self.invoke(state,'cleanup')
        self.criterion('ownership','recorded StackId with foreign observed tags must refuse before write',
            {'delete_calls':0,'stack_status':'CREATE_COMPLETE'},
            {'delete_calls':self.counts(state).get('cfn.DeleteStack',0),'stack_status':read(record)['StackStatus']})
        write(state/'observed-cleanup.json',result)
    def stale_receipt(self):
        state=self.state('malformed-confirmed-receipt');self.deploy(state)
        res=self.resource(state);res['stack'].update({'id':'NOT-A-STACK-ARN','status':'DELETE_COMPLETE','observed_by':'describe_stacks_by_id'})
        res['bucket_probe']={'result':'absent'};write(state/'resources.json',res)
        before=self.counts(state);result=self.invoke(state,'cleanup')
        self.criterion('cleanup','malformed persisted confirmation must not succeed',{'claims_confirmed':False,'bucket_present':True},
            {'claims_confirmed':result['cli_exit']==0 and result['data']['cleanup_state']=='deletion_confirmed',
             'bucket_present':(state/'fake-aws/s3'/res['bucket']).exists()})
        write(state/'observed-cleanup.json',{'cli':result,'no_requests':self.counts(state)==before})
    def malformed_json(self):
        state=self.state('invalid-json-receipt');self.deploy(state)
        (state/'resources.json').write_text('{invalid synthetic JSON')
        before=self.counts(state)
        result=self.invoke(state,'cleanup')
        self.criterion('receipts','syntactically invalid receipt refuses without requests',
            {'exit':1,'no_calls':True,'claims_confirmed':False},
            {'exit':result['cli_exit'],'no_calls':self.counts(state)==before,
             'claims_confirmed':'deletion_confirmed' in result['stdout']})
    def titan(self):
        for name,spec,category in [('partial',{'after':2,'code':'ThrottlingException'},'throttling'),
                ('verification',{'after':0,'code':'AccessDeniedException','message':'Your account is currently being verified.','status':403},'account_verification_pending'),
                ('ambiguous',{'after':0,'transport':'lost'},'transport')]:
            state=self.state('titan-'+name);self.faults(state,{'invoke_fail':spec})
            failed=self.smoke(state);before=Ledger(state).read();attempts=spec['after']+1
            last=before['calls'][-1]
            self.criterion('ledger',name+' attempts charged',{'exit':1,'used':attempts,'category':category,'failed':True},
                {'exit':failed['cli_exit'],'used':before['used']['bedrock_invocations'],'category':last['result']['error_category'],'failed':last['outcome']=='failed'})
            self.faults(state,{})
            continued=self.smoke(state,'--only-missing');after=Ledger(state).read();expectedtotal=7
            self.criterion('continuation',name+' targeted fresh process',{'exit':0,'planned':6-spec['after'],'total':expectedtotal,'creates':0,'old_calls_preserved':True},
                {'exit':continued['cli_exit'],'planned':continued['data']['planned_calls'],'total':after['used']['bedrock_invocations'],
                 'creates':self.counts(state).get('cfn.CreateStack',0),'old_calls_preserved':after['calls'][:len(before['calls'])]==before['calls']})
            calls=self.counts(state).get('bedrock.InvokeModel',0)
            repeat=self.smoke(state,'--only-missing')
            self.criterion('continuation',name+' completed repeat',{'exit':0,'planned':0,'extra_calls':0},
                {'exit':repeat['cli_exit'],'planned':repeat['data']['planned_calls'],'extra_calls':self.counts(state).get('bedrock.InvokeModel',0)-calls})
        state=self.state('titan-crash')
        inputs=state/'input.json';write(inputs,{'data_classification':'synthetic','inputs':[{'id':'restart','text':'synthetic bonjour'}]})
        self.smoke(state,'--inputs',inputs,mode='crash-invoke',process_exit=87)
        led=Ledger(state).read()
        self.criterion('durability','crash after invocation before outcome',{'used':1,'outcome':'attempted'},
            {'used':led['used']['bedrock_invocations'],'outcome':led['calls'][0]['outcome']})
        result=self.smoke(state,'--inputs',inputs,'--only-missing')
        self.criterion('ledger','unfinished attempt remains charged after continuation',{'exit':0,'used':2,'unfinished':1},
            {'exit':result['cli_exit'],'used':Ledger(state).read()['used']['bedrock_invocations'],
             'unfinished':sum(c['outcome']=='attempted' for c in Ledger(state).read()['calls'])})
        state=self.state('titan-exhausted');self.faults(state,{'invoke_fail':{'after':0,'transport':'lost'}})
        inputs=state/'input.json';write(inputs,{'data_classification':'synthetic','inputs':[{'id':'cap','text':'synthetic cap'}]})
        for _ in range(10):self.smoke(state,'--inputs',inputs,'--only-missing')
        calls=self.counts(state).get('bedrock.InvokeModel',0);result=self.smoke(state,'--inputs',inputs,'--only-missing')
        self.criterion('ledger','exhaustion refuses without resetting',{'exit':2,'used':10,'extra':0},
            {'exit':result['cli_exit'],'used':Ledger(state).read()['used']['bedrock_invocations'],'extra':self.counts(state).get('bedrock.InvokeModel',0)-calls})
    def changed(self,kind):
        state=self.state('changed-'+kind);inputs=state/'inputs.json'
        write(inputs,{'data_classification':'synthetic','inputs':[{'id':'same-id','text':'Bonjour, texte synthétique.'}]})
        first=self.smoke(state,'--inputs',inputs);before=Ledger(state).read();count=self.counts(state).get('bedrock.InvokeModel',0)
        extra=[]
        if kind=='text':write(inputs,{'data_classification':'synthetic','inputs':[{'id':'same-id','text':'Completely changed synthetic text.'}]})
        elif kind=='region':extra=['--region','us-east-1']
        elif kind=='model':
            data=Ledger(state).read();data['calls'][0]['detail']['model']='unrelated-previous-model';write(state/'ledger.json',data)
        elif kind=='dimensions':extra=['--dimensions','512']
        result=self.smoke(state,'--inputs',inputs,'--only-missing',*extra)
        if kind=='dimensions':
            self.criterion('continuation','changed dimensions are not skipped',{'calls':1,'used':2},
                {'calls':self.counts(state).get('bedrock.InvokeModel',0)-count,'used':Ledger(state).read()['used']['bedrock_invocations']})
        else:
            self.criterion('evidence binding','changed '+kind+' must not reuse success',False,
                result['cli_exit']==0 and result['data']['planned_calls']==0 and result['data']['skipped_already_ok']==['same-id'])
        write(state/'continuation-result.json',result)


def main():
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        sep=sys.argv.index('--');mode=sys.argv[sys.argv.index('--mode')+1]
        return worker(mode,sys.argv[sep+1:])
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--case',choices=('all','auth','receipts','cleanup','foreign-id','foreign-tag','stale-receipt','invalid-json','titan','changed-text','changed-region','changed-model','changed-dimensions'),default='all')
    args=ap.parse_args();out=args.out
    assert out.is_absolute() and out.parent==Path('/tmp') and out.name.startswith('flh067-') and not out.exists()
    out.mkdir(mode=0o700);h=Harness(out)
    source={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(AWS.rglob('*')) if p.is_file() and '__pycache__' not in str(p)}
    write(out/'source-before.json',source)
    actions={'auth':h.auth,'receipts':h.receipts,'cleanup':h.cleanup,'foreign-id':h.foreign_id,'foreign-tag':h.foreign_tag,'stale-receipt':h.stale_receipt,'invalid-json':h.malformed_json,'titan':h.titan}
    actions.update({f'changed-{k}':lambda k=k:h.changed(k) for k in ('text','region','model','dimensions')})
    try:
        for name,action in actions.items():
            if args.case in ('all',name):action()
    finally:
        write(out/'results.json',h.results)
        write(out/'artifact-sha256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()})
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in source.items())
    failed=[r for r in h.results if r['status']=='FAIL']
    print(json.dumps({'observations':len(h.results),'passes':len(h.results)-len(failed),'failures':failed},indent=2))
    return 1 if failed else 0


if __name__=='__main__':sys.exit(main())
