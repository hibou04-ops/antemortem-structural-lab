"""Independent authored user fixtures for public 0.8.0a1, never a research cohort.

No Source learning, historical capsules, external targets, publishing, or edits
to the installed package. Results distinguish observations from defect claims.
"""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--python',required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=args.workspace.resolve();root.mkdir(parents=True,exist_ok=False)
    environment=dict(os.environ)
    environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
    environment['PYTHONUTF8']='1'
    records=[]

    def invoke(case,label,command):
        started=time.perf_counter()
        result=subprocess.run([args.python,*map(str,command)],cwd=case,env=environment,
            capture_output=True,text=True,encoding='utf-8',timeout=75)
        (case/(label+'.stdout.txt')).write_text(result.stdout,encoding='utf-8')
        (case/(label+'.stderr.txt')).write_text(result.stderr,encoding='utf-8')
        return dict(returncode=result.returncode,wall_seconds=time.perf_counter()-started,
            stdout=result.stdout[-3000:],stderr=result.stderr[-6000:])

    def prepare(name,target,oracle='def reference(point):\n    return point\n',comparison=None):
        case=root/name;case.mkdir()
        (case/'target.py').write_text(target,encoding='utf-8')
        (case/'oracle.py').write_text(oracle,encoding='utf-8')
        contract={'kind':'int','low':0,'high':0}
        if comparison:contract['comparison']=comparison
        (case/'contract.json').write_text(json.dumps(contract),encoding='utf-8')
        return case

    def run(case):
        result=invoke(case,'run',['-m','tomolab','online-run','target.py',
            '--oracle-file','oracle.py','--contract','contract.json',
            '--usage-ledger','usage.jsonl','--allow-local-execution',
            '--budget','12','--shrink-budget','3','--output','run.json'])
        if (case/'run.json').exists():
            payload=json.loads((case/'run.json').read_text(encoding='utf-8'))
            result['receipt']={k:payload.get(k) for k in ('status','schema','replay_binding')}
            result['run']={k:payload['run'].get(k) for k in ('status','outcome','method',
                'target_calls','oracle_calls','oracle_errors','execution_errors','unknown',
                'confirmed_failures','first_confirmed_failure','shrinking')}
        return result

    def replay(case,label='replay',extra=()):
        result=invoke(case,label,['-m','tomolab','online-replay','run.json','--source','target.py',
            '--oracle-file','oracle.py','--contract','contract.json',
            '--allow-local-execution','--output',label+'.json',*extra])
        if (case/(label+'.json')).exists():
            result['receipt']=json.loads((case/(label+'.json')).read_text(encoding='utf-8'))
        return result

    # A normal source module using dataclasses with postponed annotations is
    # valid Python and still exposes exactly one synchronous JSON argument.
    case=prepare('dataclass_module',
        'from __future__ import annotations\nfrom dataclasses import dataclass\n'
        '@dataclass\nclass Item:\n    value: int\n'
        'def implementation(point):\n    return Item(point).value\n')
    direct=invoke(case,'direct',['-c',
        'from target import implementation; assert implementation(0)==0; print("VALID_PYTHON_MODULE")'])
    actual=run(case)
    records.append(dict(id='DATACLASS_MODULE_LOADING',direct=direct,actual=actual,
        observed_issue=direct['returncode']==0 and actual['returncode']!=0,
        expected='Normal valid module imports and exposes the supported pure function',
        classification='PRODUCT_LOADER_DEFECT_IF_CONFIRMED'))

    # The function is explicitly exported under the CLI default name. The run
    # accepts it, but _binding records __name__ rather than the selected name.
    case=prepare('function_alias',
        'def actual_function(point):\n    return point+1\nimplementation=actual_function\n')
    actual=run(case)
    repeated=replay(case)
    workaround=replay(case,'replay_actual_name',('--function','actual_function'))
    records.append(dict(id='EXPORTED_FUNCTION_ALIAS_REPLAY',actual=actual,replay=repeated,
        explicit_actual_name_control=workaround,
        observed_issue=actual['returncode']==0 and actual.get('run',{}).get('outcome')=='CONFIRMED_FAILURE'
            and repeated['returncode']==2 and workaround.get('receipt',{}).get('replay_status')=='REPRODUCED',
        expected='Unchanged source, Oracle, contract and original CLI default names replay successfully',
        classification='PRODUCT_REPLAY_BINDING_DEFECT_IF_CONFIRMED'))

    # User-specified absolute tolerance is tested symmetrically at and away
    # from zero. No existing research Oracle or tolerance is changed.
    tolerance={'absolute':0.000001,'relative':0.0}
    zero=prepare('tolerance_zero','def implementation(point):\n    return 0.0\n',
        'def reference(point):\n    return 0.000000001\n',tolerance)
    nonzero=prepare('tolerance_nonzero','def implementation(point):\n    return 1.0\n',
        'def reference(point):\n    return 1.000000001\n',tolerance)
    zr,nzr=run(zero),run(nonzero)
    records.append(dict(id='ABSOLUTE_TOLERANCE_ZERO_POLICY',zero=zr,nonzero=nzr,
        independent_expected_model='math.isclose with abs_tol=1e-6 and rel_tol=0 is True for both pairs',
        observed_issue=zr.get('run',{}).get('outcome')=='CONFIRMED_FAILURE'
            and nzr.get('run',{}).get('outcome')=='NO_CONFIRMED_FAILURE_WITHIN_BUDGET',
        classification='NUMERIC_COMPARISON_CONTRACT_AND_DOCUMENTATION_ISSUE_IF_CONFIRMED',
        scope='Not proof that a source function is defective; strict zero is explicit implementation policy but undocumented in user README'))

    # Positive controls exercise documented exception meaning rather than
    # treating any exception as a product defect.
    raising='def implementation(point):\n    raise ValueError("documented")\n'
    oracle_raising='def reference(point):\n    raise ValueError("documented")\n'
    case=prepare('allowed_exception',raising,oracle_raising,
        {'expected_exceptions':['builtins.ValueError'],'exception_policy':'match_type'})
    allowed=run(case)
    case=prepare('oracle_error','def implementation(point):\n    return point\n',oracle_raising)
    oracle_error=run(case)
    records.append(dict(id='EXCEPTION_CLASSIFICATION_CONTROLS',allowed=allowed,oracle_error=oracle_error,
        passed=allowed.get('run',{}).get('outcome')=='NO_CONFIRMED_FAILURE_WITHIN_BUDGET'
            and oracle_error['returncode']==3 and oracle_error.get('run',{}).get('outcome')=='INCONCLUSIVE'
            and oracle_error.get('run',{}).get('oracle_errors',0)>0
            and not oracle_error.get('run',{}).get('confirmed_failures')))

    metadata=invoke(root,'installed_identity',['-c',
        'import json,sys,tomolab,importlib.metadata as m; print(json.dumps({"version":m.version("antemortem-structural-lab"),"origin":tomolab.__file__,"python":sys.version}))'])
    files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json')}
    output=dict(schema='tomolab-independent-public-behavior-audit-v1',
        status='EXECUTED',installed_identity=metadata,records=records,authored_cases_only=True,
        source_collection_calls=0,research_cohort_runs=0,package_edits=0,publishing_calls=0,
        file_sha256=files)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
    print(json.dumps(output,indent=2,ensure_ascii=True))

if __name__=='__main__':main()
