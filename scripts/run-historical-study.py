"""One gated preflight or explicitly dispatched historical comparison.

Uses the existing online runner, registration, Source learning and usage ledger.
No upstream implementation may execute outside the verified container.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tomolab.historical import require_reviewed_container
from tomolab.discovery.schema import canonical,digest


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n')
        stream.flush();os.fsync(stream.fileno())


def driver():
    spec=importlib.util.spec_from_file_location('_historical_shared_driver',ROOT/'scripts/evaluate-online.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def inspection_options(case):
    import inspect
    original=case.target.upstream_function
    return (dict(mode='structural',inspection_target=original) if inspect.isfunction(original)
            else dict(mode='black_box'))


def validate_source_preparation(prepared):
    rows=prepared['source_runs']
    if len(rows)!=2:
        raise ValueError('both registered Sources must complete before Target registration')
    for entry in rows:
        run=entry['run']
        if (run['status']!='COMPLETE' or not run.get('first_confirmed_failure')
                or any(run.get(key,0) for key in ('oracle_errors','execution_errors','unknown'))
                or not any(row['status']=='PASS' for row in run['observations'])):
            raise ValueError('incomplete or unresolved Source preparation; no Target comparison authorized')


def eligibility(corpus):
    """Only evaluator-owned regressions; never supplied as a strategy/example."""
    from tomolab.discovery.online_observe import _capture,observe
    rows=[]
    for case in corpus:
        before=deepcopy(case.target.upstream_execution_metrics)
        point=deepcopy(case.entry['reproduction_input'])
        direct,_,_= _capture(case.direct,deepcopy(point),tracing=False)
        adapted,_,_= _capture(case.target,deepcopy(point),tracing=False)
        if direct!=adapted:raise ValueError('original/adapter semantic mismatch: '+case.id)
        observed=[observe(case.target,case.oracle,deepcopy(point),case.contract,tracing=False) for _ in range(3)]
        expected='PASS'if case.role=='CONTROL'else'FAILURE'
        if any(row['feedback']['status']!=expected for row in observed):
            write(Path('/output')/('unresolved-'+case.id+'.json'),dict(case=case.metadata(),observed=observed))
            raise ValueError('historical eligibility or fixed-control disagreement: '+case.id)
        if len({row['semantic_digest']for row in observed})!=1:
            raise ValueError('historical witness does not reproduce identically')
        metrics=deepcopy(case.target.upstream_execution_metrics)
        if metrics['adapter_invocations']-before['adapter_invocations']!=4 or metrics['original_entry_events']-before['original_entry_events']<4:
            raise ValueError('reviewed original implementation entry not observed')
        rows.append(dict(case=case.metadata(),status=expected,oracle_calls=3,
            adapter_calls=4,direct_original_calls=1,adapter_equivalent=True,
            original_entry=metrics,witness_digest=digest(point),reproductions=3))
    return rows


def register(config,prepared,corpus):
    names={p.relative_to(ROOT).as_posix()for folder in ('tomolab','benchmarks','scripts','tests')
           for p in(ROOT/folder).rglob('*.py')}
    names|={p.relative_to(ROOT).as_posix()for p in(ROOT/'benchmarks/historical').rglob('*')if p.is_file()}
    names|={'pyproject.toml','MANIFEST.in','.github/workflows/tests.yml','containers/historical-review.Dockerfile',
            'docs/HISTORICAL_ARTIFACT_RECIPIENT.pem'}
    files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in sorted(names)}
    initial={fold:mold['artifact_digest']for fold,mold in prepared['molds'].items()}
    authority=digest(dict(scope='E9_R1_REVIEWED_HISTORICAL_COMPARISON',code=digest(files),
                          knowledge=initial,config=digest(config)))
    profile=dict(schema='tomolab-online-execution-profile-v1',scope='EXPERIMENTAL_PROBE',
        authority_id=authority,algorithm_digest=digest(files),initial_knowledge_digest=digest(initial),
        configuration_digest=digest(config),target_local_feedback=True,cross_target_feedback=False,
        final_evaluation_authorized=False,publication_authorized=False)
    return dict(schema='tomolab-online-registration-v1',frozen_config=config,
        source_preparation_digest=digest(prepared),initial_molds=initial,code_files=files,
        targets=[case.metadata()for case in corpus if case.role!='SOURCE'],profile=profile,
        environment=driver().environment_identity())


def public_runs(result):
    """Keep complete misses/costs and provenance, without inputs/Oracle values."""
    rows=[]
    for row in result['runs']:
        run=row['result']
        safe={key:deepcopy(run.get(key))for key in('status','outcome','target_calls','oracle_calls',
            'first_confirmed_failure','cost','scheduler','invalid_inputs','execution_errors','oracle_errors',
            'unknown','source_replay_calls','new_valid_inputs')}
        safe['shrinking']={key:value for key,value in run['shrinking'].items()if key!='witness'}
        safe['confirmation_events']=[dict(input_digest=o['input_digest'],status=o['status'],phase=o['phase'],
            observation_id=e.get('observation_id'),reference_match=e.get('reference_match'),
            origin=o.get('origin'),operator=o.get('operator'),rule_id=o.get('rule_id'),
            source_selection=e.get('source_selection'),common_policy_state_before=e.get('common_policy_state_before'),
            common_policy_state_after=e.get('common_policy_state_after'))
            for o,e in zip(run['observations'],run['events'])]
        safe['boundary']={key:deepcopy(run['boundary'].get(key))for key in('isolation','generator_sha256',
            'worker_lifecycle','rpc_evaluations','worker_exit_code','target_code_transferred','oracle_code_transferred',
            'oracle_values_transferred','oracle_hashes_transferred','imported_modules')}
        rows.append(dict(evaluation=row['evaluation'],fold=row['fold'],case=row['case'],
            seed=row['seed'],method=row['method'],budget=row.get('budget',run['budget']),
            routing=row.get('routing'),executor_call_wall_seconds=row.get('executor_call_wall_seconds'),result=safe))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase',choices=('preflight','study'),required=True)
    p.add_argument('--output-directory',type=Path,required=True)
    args=p.parse_args()
    started=time.perf_counter();boundary=require_reviewed_container()
    out=args.output_directory.resolve();out.mkdir(parents=True,exist_ok=True)
    marker=out/'START.json';write(marker,dict(phase=args.phase,binding=boundary['binding'],automatic_retry=False))
    from benchmarks.historical import cases
    from benchmarks.online import historical_config,prepare_sources,run_comparison
    from tomolab.discovery.online_engine import run_online
    from tomolab.discovery.evaluation_usage import UsageLedger
    corpus=cases(load=True)
    if args.phase=='preflight':
        first_ids={'toolz-interpose','more-windowed','more-windowed-fixed-control'}
        first_checks=eligibility([case for case in corpus if case.id in first_ids])
        source=next(case for case in corpus if case.id=='toolz-interpose')
        source_run=run_online(source.target,source.oracle,source.contract,method='B',seed=1811,
            budget=24,shrink_budget=6,max_seconds=30,**inspection_options(source))
        from tomolab.discovery.online_learning import learn_mold
        first_mold=learn_mold(source_run['observations'])
        fixed=next(case for case in corpus if case.id=='more-windowed-fixed-control')
        first_target=run_online(fixed.target,fixed.oracle,fixed.contract,method='D',seed=1811,
            budget=12,shrink_budget=0,max_seconds=30,**inspection_options(fixed),mold=first_mold,
            replays=[row['input']for row in source_run['observations']if row['status']=='FAILURE'])
        if first_target['status']!='COMPLETE' or first_target['confirmed_failures']:
            raise ValueError('first Source-to-reviewed-fixed-target functional path did not validate')
        write(out/'first-link-private.json',dict(source=source_run,target=first_target,mold=first_mold))
        write(out/'first-link.public.json',dict(status='PASS',source='toolz-interpose',target=fixed.id,
            source_target_calls=source_run['target_calls'],target_calls=first_target['target_calls'],
            mold_digest=first_mold['artifact_digest'],rules=len(first_mold['rules']),
            buggy_witness_eligibility=first_checks,classification='FIXED_CONTROL_PIPELINE_NOT_METHOD_PERFORMANCE'))
        checks=eligibility(corpus)
        probes=[]
        for case in corpus:
            if case.role!='SOURCE':continue
            for budget in (24,48):
                run=run_online(case.target,case.oracle,case.contract,method='B',seed=1811,
                    budget=budget,shrink_budget=6,max_seconds=30,**inspection_options(case))
                if run['status']!='COMPLETE' or not run['first_confirmed_failure'] or not any(o['status']=='PASS'for o in run['observations']):
                    raise ValueError('Source/development budget cannot support observations and confirmation')
                probes.append(dict(case=case.id,budget=budget,run=run))
        config=historical_config(budgets=[24,48],seeds=[4201,4211,4229],source_budget=48,
                                 source_seed=1811,shrink_budget=6,max_seconds=30)
        prepared=prepare_sources(config,corpus=corpus)
        write(out/'prepared.json',prepared)
        validate_source_preparation(prepared)
        write(out/'preflight-private.json',dict(eligibility=checks,source_probes=probes))
        write(out/'preflight.public.json',dict(schema='tomolab-historical-preflight-v1',status='PASS',
            boundary=boundary,eligibility=checks,source_budget_probe=[dict(case=r['case'],budget=r['budget'],
                target_calls=r['run']['target_calls'],oracle_calls=r['run']['oracle_calls'],
                first_confirmed_failure=r['run']['first_confirmed_failure'],status=r['run']['status'])for r in probes],
            source_coverage=prepared.get('coverage'),fold_plan=prepared.get('fold_plan'),
            source_target_calls=prepared['target_calls'],source_oracle_calls=prepared['oracle_calls'],
            selected_budget_basis='SOURCE_ONLY_24_AND_48_SUPPORT_PASS_FAILURE_CONFIRMATION_AND_BOUNDED_SHRINKING',
            target_method_comparison_calls=0,wall_seconds=time.perf_counter()-started,allow_release=False))
    else:
        config=historical_config(budgets=[24,48],seeds=[4201,4211,4229],source_budget=48,
                                 source_seed=1811,shrink_budget=6,max_seconds=30)
        prepared=prepare_sources(config,corpus=corpus)
        write(out/'prepared.json',prepared)
        validate_source_preparation(prepared)
        registration=register(config,prepared,corpus)
        registration['registration_digest']=digest(registration)
        write(out/'registration.json',registration)
        write(out/'source-before-target.public.json',dict(config=config,coverage=prepared.get('coverage'),
            fold_plan=prepared.get('fold_plan'),initial_molds=registration['initial_molds'],
            registration_digest=registration['registration_digest'],target_method_comparison_calls=0))
        print(canonical(dict(event='FROZEN_BEFORE_TARGET',registration_digest=registration['registration_digest'],
            code_digest=digest(registration['code_files']),target_method_comparison_calls=0)),flush=True)
        common=driver();common.validate_registration(registration,config,prepared)
        ledger=UsageLedger(out/'usage.jsonl',authority_id=registration['profile']['authority_id'])
        targets=[dict(identity=row['identity'],evaluation_role=row.get('usage_role'),
                      control_group=row.get('control_group'))for row in registration['targets']]
        start=ledger.claim_experimental(targets,registration['profile'],expected_profile=registration['profile'])
        result=run_comparison(config,prepared,corpus=corpus,event_path=out/'events.jsonl')
        write(out/'results.json',result)
        common.validate_registration(registration,config,prepared)
        ledger.complete(start['claim_id'],dict(status='COMPLETE',raw_results_sha256=hashlib.sha256((out/'results.json').read_bytes()).hexdigest(),runs=len(result['runs'])))
        write(out/'results.public.json',dict(schema='tomolab-historical-public-results-v1',status='COMPLETE',
            config=config,registration=registration,source_coverage=prepared.get('coverage'),
            fold_plan=prepared.get('fold_plan'),source_cost=prepared['cost'],summary=result['summary'],
            runs=public_runs(result),boundary=boundary,run_count=len(result['runs']),reruns=0,
            original_entry_metrics={case.id:case.target.upstream_execution_metrics for case in corpus},
            raw_results_sha256=hashlib.sha256((out/'results.json').read_bytes()).hexdigest(),
            source_target_calls=prepared['target_calls'],source_oracle_calls=prepared['oracle_calls'],
            wall_seconds=time.perf_counter()-started,allow_release=False))
    print(canonical(dict(status='COMPLETE',phase=args.phase,wall_seconds=time.perf_counter()-started,allow_release=False)))


if __name__=='__main__':main()
