"""Independent public-user audit. No upload, study, learning or publication calls."""
import argparse,hashlib,json,os,platform,shutil,subprocess,sys,tempfile,time,venv
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

VERSION='0.8.0a1'
REPO='hibou04-ops/antemortem-structural-lab'
SOURCE='3ece4df3bd01abe6aae58ef8a01bf4b01515f689'
NAMES={f'antemortem_structural_lab-{VERSION}-py3-none-any.whl',f'antemortem_structural_lab-{VERSION}.tar.gz'}

def digest(data):return hashlib.sha256(data).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def get(url):
    host=urlsplit(url).hostname
    if host not in ('api.github.com','pypi.org','github.com','files.pythonhosted.org'):
        raise ValueError('unapproved public artifact host')
    headers={'User-Agent':'tomolab-independent-public-audit'}
    if host=='api.github.com':
        headers['Accept']='application/vnd.github+json'
        if os.environ.get('GH_TOKEN'):headers['Authorization']='Bearer '+os.environ['GH_TOKEN']
    with urlopen(Request(url,headers=headers),timeout=40) as response:data=response.read(8_000_001)
    if len(data)>8_000_000:raise ValueError('public file exceeds audit limit')
    return data

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.source=a.source.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    report=dict(schema='tomolab-independent-public-user-audit-v1',version=VERSION,source=SOURCE,
        python=sys.version,os=platform.platform(),checks=[],commands=[],uploads=0,research_runs=0,learning_calls=0)
    environment=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','GH_TOKEN','GITHUB_TOKEN'):environment.pop(key,None)
    def check(name,fn):
        started=time.perf_counter()
        try:
            value=fn();report['checks'].append(dict(name=name,status='PASS',seconds=time.perf_counter()-started,details=value))
            return value
        except Exception as error:
            report['checks'].append(dict(name=name,status='FAIL',seconds=time.perf_counter()-started,error_type=type(error).__name__,error=str(error)[:3000]))
            return None
    def command(name,python,args,cwd,expected=0):
        result=subprocess.run([str(python),*map(str,args)],cwd=cwd,env=environment,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=240)
        report['commands'].append(dict(name=name,returncode=result.returncode,expected=expected,stdout=result.stdout[-4000:],stderr=result.stderr[-4000:]))
        assert result.returncode==expected,f'{name}: expected {expected}, got {result.returncode}: {result.stderr[-1500:]}'
        return result.stdout
    try:
        release=json.loads(get('https://api.github.com/repos/'+REPO+'/releases/tags/v'+VERSION))
        registry=json.loads(get('https://pypi.org/pypi/antemortem-structural-lab/'+VERSION+'/json'))
        tag=json.loads(get('https://api.github.com/repos/'+REPO+'/git/ref/tags/v'+VERSION))
        assert tag['object']['type']=='tag'
        tag_object=json.loads(get('https://api.github.com/repos/'+REPO+'/git/tags/'+tag['object']['sha']))
        assert tag_object['object']['sha']==SOURCE and not release['draft'] and release['prerelease']
        assert registry['info']['version']==VERSION and registry['info']['yanked'] is False
        assert {r['filename'] for r in registry['urls']}==NAMES
        write(a.output/'release.json',release);write(a.output/'pypi.json',registry);write(a.output/'tag.json',tag_object)
        report['checks'].append(dict(name='live-public-identity',status='PASS'))
        files=a.output/'pypi';files.mkdir()
        github=a.output/'github';github.mkdir()
        assets={r['name']:r for r in release['assets']}
        for row in registry['urls']:
            name=row['filename'];expected=row['digests']['sha256']
            assert not row['yanked'] and assets[name]['digest']=='sha256:'+expected and assets[name]['size']==row['size']
            first=get(row['url']);second=get(assets[name]['browser_download_url'])
            assert digest(first)==digest(second)==expected and len(first)==len(second)==row['size']
            (files/name).write_bytes(first);(github/name).write_bytes(second)
            report['checks'].append(dict(name='independent-public-bytes:'+name,status='PASS',sha256=expected,size=len(first)))
        english=(a.source/'README.md').read_bytes()
        assert registry['info']['description'].encode('utf-8')==english
        report['checks'].append(dict(name='live-PyPI-description-exact-pinned-English-README',status='PASS',sha256=digest(english)))
        package=Path(__file__).with_name('package_audit.py')
        if package.exists():
            check('independent-package-inspection',lambda:command('archive-audit',sys.executable,[package,'--directory',files,'--source-root',a.source,'--pypi-json',a.output/'pypi.json','--github-release-json',a.output/'release.json','--output',a.output/'package.json'],a.output))
        for kind,name in (('wheel',f'antemortem_structural_lab-{VERSION}-py3-none-any.whl'),('sdist',f'antemortem_structural_lab-{VERSION}.tar.gz')):
            workspace=Path(tempfile.mkdtemp(prefix='public-user-audit-'+kind+'-')).resolve()
            envpath=workspace/'env';venv.EnvBuilder(with_pip=True).create(envpath)
            python=envpath/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            artifact=files/name
            def run(args,**kw):return command(kind+':'+kw.pop('name',str(args[0])),python,args,workspace,**kw)
            check(kind+':base-install',lambda:run(['-m','pip','install','--no-cache-dir','--index-url','https://pypi.org/simple',artifact],name='base-install'))
            check(kind+':outside-import-and-version',lambda:run(['-c',"import importlib.metadata as m,tomolab,pathlib; p=pathlib.Path(tomolab.__file__).resolve(); assert str(p).startswith(str(pathlib.Path('env').resolve())); assert m.version('antemortem-structural-lab')=='0.8.0a1';print(p);print(m.version('antemortem-structural-lab'))"],name='origin'))
            check(kind+':base-help',lambda:run(['-m','tomolab','--help'],name='help'))
            def missing_qa():
                text=run(['-m','tomolab','online-demo','--workspace','missing-qa','--usage-ledger','missing-qa.jsonl','--output','missing-qa.json','--allow-local-execution'],expected=2,name='missing-qa')
                assert not (workspace/'missing-qa.json').exists()
                return 'No false success; optional dependency is required.'
            check(kind+':missing-qa-rejected',missing_qa)
            if kind=='wheel':
                def contribution():
                    run(['-m','pip','install','--no-cache-dir','--index-url','https://pypi.org/simple','pytest','build','twine'],name='CONTRIBUTING-tools')
                    result=subprocess.run([str(python),'-m','pytest','--collect-only','-q',str(a.source/'tests/test_property_testing.py')],cwd=workspace,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
                    observed=dict(returncode=result.returncode,stdout=result.stdout[-4000:],stderr=result.stderr[-4000:])
                    observed['missing_hypothesis_confirmed']=result.returncode!=0 and 'hypothesis' in (result.stdout+result.stderr) and 'ModuleNotFoundError' in (result.stdout+result.stderr)
                    write(a.output/'contribution-doc-probe.json',observed)
                    return observed
                check('CONTRIBUTING-base-only-collection-probe',contribution)
            check(kind+':qa-install',lambda:run(['-m','pip','install','--no-cache-dir','--index-url','https://pypi.org/simple',str(artifact)+'[qa]'],name='qa-install'))
            check(kind+':pip-check',lambda:run(['-m','pip','check'],name='pip-check'))
            def demo():
                run(['-m','tomolab','online-demo','--workspace','demo-work','--usage-ledger','demo-usage.jsonl','--allow-local-execution','--budget','24','--shrink-budget','6','--output','demo-result.json'],name='README-quickstart')
                value=json.loads((workspace/'demo-result.json').read_text(encoding='utf-8'))
                write(a.output/(kind+'-demo.json'),value)
                assert value['status']=='COMPLETE' and value['run']['method']=='E9_A' and value['run']['outcome']=='CONFIRMED_FAILURE'
                assert value['source_learning']['enabled'] is False and all(value['source_learning'][n]==0 for n in ('target_calls','oracle_calls','rules'))
                return dict(outcome=value['run']['outcome'],source_learning=value['source_learning'],target_calls=value['run']['target_calls'])
            check(kind+':README-default-search',demo)
            def own():
                run(['-c',"from pathlib import Path;from shutil import copytree;from tomolab.cli import EXAMPLES;copytree(EXAMPLES/'product',Path('my-check'))"],name='README-copy-example')
                args=['-m','tomolab','online-run','my-check/target.py','--oracle-file','my-check/oracle.py','--contract','my-check/contract.json','--usage-ledger','my-check/usage.jsonl','--allow-local-execution','--budget','24','--shrink-budget','6','--output','my-check/run.json']
                run(args,name='README-own-function')
                value=json.loads((workspace/'my-check/run.json').read_text(encoding='utf-8'))
                assert value['run']['method']=='E9_A' and value['run']['outcome']=='CONFIRMED_FAILURE'
                replay=['-m','tomolab','online-replay','my-check/run.json','--source','my-check/target.py','--oracle-file','my-check/oracle.py','--contract','my-check/contract.json','--allow-local-execution','--output','my-check/replay.json']
                run(replay,name='README-replay')
                evidence=json.loads((workspace/'my-check/replay.json').read_text(encoding='utf-8'))
                write(a.output/(kind+'-own.json'),value);write(a.output/(kind+'-replay.json'),evidence)
                assert evidence['replay_status']=='REPRODUCED' and evidence['binding_status']=='FILE_AND_CONTRACT_BINDINGS_MATCH'
                (workspace/'my-check/target.py').write_text((workspace/'my-check/target.py').read_text(encoding='utf-8')+'\n# reviewed file changed\n',encoding='utf-8')
                replay[-1]='my-check/drift-replay.json';run(replay,expected=2,name='changed-source-refused')
                return dict(replay_status=evidence['replay_status'],binding=evidence['binding_status'])
            check(kind+':README-run-bound-replay-and-drift',own)
            def correct():
                folder=workspace/'correct';folder.mkdir();(folder/'target.py').write_text('def implementation(value):\n    return value\n',encoding='utf-8');(folder/'oracle.py').write_text('def reference(value):\n    return value\n',encoding='utf-8');(folder/'contract.json').write_text('{"kind":"int","low":-2,"high":2}',encoding='utf-8')
                run(['-m','tomolab','online-run','correct/target.py','--oracle-file','correct/oracle.py','--contract','correct/contract.json','--usage-ledger','correct/usage.jsonl','--allow-local-execution','--budget','24','--shrink-budget','6','--output','correct/run.json'],name='authored-normal-control')
                value=json.loads((folder/'run.json').read_text(encoding='utf-8'));write(a.output/(kind+'-normal.json'),value)
                assert value['run']['outcome']=='NO_CONFIRMED_FAILURE_WITHIN_BUDGET'
                return value['run']['outcome']
            check(kind+':normal-control-miss-is-not-proof',correct)
            behavior=Path(__file__).with_name('behavior_audit.py')
            if behavior.exists():
                check(kind+':independent-behavior-probes',lambda:command(kind+':behavior',sys.executable,[behavior,'--python',python,'--workspace',workspace/'behavior','--output',a.output/(kind+'-behavior.json')],workspace))
    except Exception as error:
        report['checks'].append(dict(name='setup-or-public-download',status='FAIL',error_type=type(error).__name__,error=str(error)[:3000]))
    report['status']='PASS' if all(r['status']=='PASS' for r in report['checks']) else 'FINDINGS_OR_EXECUTION_ERROR'
    write(a.output/'audit.json',report);print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
