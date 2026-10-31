"""Installed-wheel external historical path, inside the same strict OCI gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
import venv


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('wheel receipt already exists')
    root=Path(__file__).resolve().parents[1]
    import sys
    sys.path.insert(0,str(root))
    from tomolab.historical import require_reviewed_container
    boundary=require_reviewed_container()
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    wheels=list((root/'dist').glob(f'antemortem_structural_lab-{version}-*.whl'))
    if len(wheels)!=1:raise ValueError('exactly one current candidate wheel required')
    wheel=wheels[0]
    checks=[]
    with tempfile.TemporaryDirectory(prefix='historical-installed-',dir='/tmp') as temporary:
        external=Path(temporary)
        venv.EnvBuilder(with_pip=True,symlinks=True,system_site_packages=True).create(external/'env')
        python=external/'env/bin/python'
        def run(label,*argv,success=True):
            tick=time.perf_counter()
            value=subprocess.run([str(python),'-I','-X','utf8',*map(str,argv)],cwd=external,
                text=True,capture_output=True,timeout=180)
            checks.append(dict(check=label,returncode=value.returncode,expected_success=success,
                               wall_seconds=time.perf_counter()-tick))
            if (value.returncode==0)!=success:raise RuntimeError(label+': '+value.stderr[-4000:])
            return value.stdout
        def command(label,*argv):
            path=external/(label+'.json');run(label,'-m','tomolab',*argv,'--output',path)
            io=json.loads(Path(str(path)+'.io.json').read_text(encoding='utf-8'))
            if io['receipt_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError('installed receipt and durable IO digest differ')
            return json.loads(path.read_text(encoding='utf-8')),path
        run('offline-wheel-install','-m','pip','install','--no-index','--no-deps','--force-reinstall',wheel)
        origin=json.loads(run('installed-origin','-c',
            "import inspect,json;from tomolab import historical_cli;from tomolab.discovery import online_engine;"
            "print(json.dumps([inspect.getfile(m) for m in (historical_cli,online_engine)]))"))
        if not all(Path(path).is_relative_to(external/'env')for path in origin):
            raise ValueError('historical commands did not come from installed wheel')
        for name in ('historical-inspect','historical-run','online-learn'):
            run('help-'+name,'-m','tomolab',name,'--help')
        catalog=root/'benchmarks/historical';factory=root/'benchmarks/historical.py'
        factory_sha=hashlib.sha256(factory.read_bytes()).hexdigest()
        inspected,_=command('metadata-inspection','historical-inspect','--catalog',catalog)
        assert inspected['target_calls']==inspected['oracle_calls']==0
        common=('historical-run','--catalog',catalog,'--factory',factory,
            '--expected-factory-sha256',factory_sha,'--budget','24','--shrink-budget','6',
            '--usage-ledger',external/'usage.jsonl','--allow-local-execution')
        source,source_path=command('historical-source',*common,'--case','toolz-interpose','--method','B')
        assert source['run']['first_confirmed_failure']is not None
        learned,_=command('source-mold','online-learn','--observations',source_path,'--mold',external/'mold.json')
        assert learned['rules']>0 and learned['mold_bytes']<=10240
        target,_=command('fixed-target-with-mold',*common,'--case','more-windowed-fixed-control','--method','D',
            '--mold',external/'mold.json','--expected-digest',learned['mold_digest'])
        assert target['run']['first_confirmed_failure']is None and target['status']=='COMPLETE'
        run('bad-catalog-identity-denied','-m','tomolab',*common,'--case','more-windowed',
            '--method','B','--expected-factory-sha256','0'*64,'--output',external/'denied.json',success=False)
        result=dict(schema='tomolab-installed-historical-wheel-v1',status='PASS',checks=checks,
            wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),boundary=boundary,
            source_calls=source['run']['target_calls'],fixed_control_calls=target['run']['target_calls'],
            source_rules=learned['rules'],dependency_installation='DECLARED_PINNED_IMAGE_DEPENDENCY_REUSE',
            registered_research_reexecuted=False,allow_release=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8')as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
