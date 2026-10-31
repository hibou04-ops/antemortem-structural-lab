"""Exposed authored functional probe, never an independent utility benchmark.

Four compact, reviewed fixtures exercise the consultation's four mechanisms.
The native A engine and a separate native @given relational path are measured
separately. Nothing here changes the ALL Mold, selector, or M0 qualification.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re
import time

from .discovery.online_engine import run_online
from .discovery.online_observe import observe, inspect_target
from .discovery.online_schema import hypothesis_strategy, input_identity
from .discovery.relational_candidates import (MUTATORS, CONSULTATION_SHA256,
    extract_relational_signature, propose_relational_candidates)
from .discovery.schema import digest

EVIDENCE_CLASS = "DEVELOPMENT_SYNTHETIC_EXPOSED"
CONTRACT = dict(kind="sequence_int",low=-32,high=32,min_size=0,max_size=8)


def _length_target(xs):
    n=len(xs)
    if n>=4 and xs[0]==n and xs[-1]==n-1:
        return xs[n]
    return sum(xs[1:-1]) if n>=4 else sum(xs)


def _length_reference(xs):
    return sum(value for i,value in enumerate(xs) if len(xs)<4 or 0<i<len(xs)-1)


def _adjacent_target(xs):
    if len(xs)>=5 and all(xs[i+1]>xs[i] for i in range(len(xs)-2)):
        return xs[-1]-xs[0]
    return max(xs)-min(xs) if xs else 0


def _adjacent_reference(xs):
    ordered=sorted(xs)
    return ordered[-1]-ordered[0] if ordered else 0


def _aggregate_target(xs):
    volume=sum(abs(v) for v in xs)
    if len(xs)>=4 and max(abs(v) for v in xs)>=2 and sum(xs)==0:
        return 0
    return volume


def _aggregate_reference(xs):
    return sum(v if v>=0 else -v for v in xs)


def _cardinality_target(xs):
    if len(xs)<5:
        return 0
    if xs[0]!=0 and len(set(xs))==2 and xs.count(xs[0])==len(xs)-1 and xs[-1]!=xs[0]:
        return 0
    return sum(sorted(xs)[1:-1])


def _cardinality_reference(xs):
    if len(xs)<5:
        return 0
    values=sorted(xs)
    return sum(values[i] for i in range(1,len(values)-1))


def _reset_authored_fixture():
    # Only these stateless authored callables are reviewed by this adapter.
    return True


def _cases():
    return tuple(zip(MUTATORS,(_length_target,_adjacent_target,_aggregate_target,_cardinality_target),
                     (_length_reference,_adjacent_reference,_aggregate_reference,_cardinality_reference)))


def _sha(fn):
    return hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()


def _resolved(rows):
    if len(rows)!=3 or any(row["reset_success"] is not True or row["status"] not in ("PASS","FAILURE")
        or row["target_calls"]!=1 or row["oracle_calls"]!=1
        or type(row["semantic_digest"]) is not str or re.fullmatch(r"[0-9a-f]{64}",row["semantic_digest"]) is None for row in rows):
        return None
    if len({row["status"] for row in rows})!=1 or len({row["semantic_digest"] for row in rows})!=1:
        return None
    return rows[0]["status"]


def _measure_pair(target,oracle,common,candidate,*,reset,structure,contract=CONTRACT):
    """Actual candidate-level repetitions, not full policy counterfactuals."""
    tick=time.perf_counter()
    branches={"common":[],"relational":[]}
    cost=dict(target_calls=0,oracle_calls=0,reset_calls=0,wall_seconds=0.0)
    for name,point in (("common",common),("relational",candidate)):
        for repeat in range(3):
            cost["reset_calls"]+=1
            try:
                reset_ok=reset() is True
            except Exception:
                reset_ok=False
            if not reset_ok:
                row=dict(repeat=repeat,status="UNKNOWN",semantic_digest=None,reset_success=False,
                         target_calls=0,oracle_calls=0,reason="RESET_NOT_VERIFIED")
            else:
                observation=observe(target,oracle,point,contract,structure,tracing=False)
                row=dict(repeat=repeat,status=observation["feedback"]["status"],
                    semantic_digest=observation.get("semantic_digest"),reset_success=True,
                    target_calls=observation["target_calls"],oracle_calls=observation["oracle_calls"],reason=None)
                cost["target_calls"]+=row["target_calls"]; cost["oracle_calls"]+=row["oracle_calls"]
            branches[name].append(row)
    c,l=(_resolved(branches[name]) for name in ("common","relational"))
    label="UNKNOWN" if c is None or l is None else {
        ("PASS","FAILURE"):"gain",("FAILURE","PASS"):"loss",
        ("PASS","PASS"):"neutral_pass",("FAILURE","FAILURE"):"neutral_failure"}[(c,l)]
    cost["wall_seconds"]=time.perf_counter()-tick
    receipt=dict(schema="tomolab-relational-authored-pair-v1",evidence_class=EVIDENCE_CLASS,
        common_input=deepcopy(common),relational_input=deepcopy(candidate),
        common_digest=input_identity(common),relational_digest=input_identity(candidate),
        implementation_sha256=_sha(target),oracle_sha256=_sha(oracle),
        reset_sha256=_sha(reset),contract_sha256=digest(contract),branches=branches,label=label,cost=cost,
        unknown_reasons=["RESET_STATUS_OR_SEMANTIC_REPETITION_UNRESOLVED"] if label=="UNKNOWN" else [],
        scope="AUTHORED_STATELESS_SAME_ANCHOR_LOCAL_PAIR_NOT_POLICY_UTILITY")
    receipt["receipt_sha256"]=digest(receipt)
    return receipt


def _run_relational(target,oracle,operator,*,seed,budget):
    from hypothesis import given,settings,seed as hypothesis_seed,target as hypothesis_target,Phase,HealthCheck
    structure=inspect_target(target,CONTRACT)
    signature=extract_relational_signature(target,CONTRACT)
    strategy=hypothesis_strategy(CONTRACT,structure)
    receipts,seen,decisions=[],set(),[]
    started=time.perf_counter()
    max_pairs=budget//6
    @hypothesis_seed(seed)
    @settings(max_examples=budget*4,database=None,deadline=None,
              phases=(Phase.generate,Phase.target),suppress_health_check=list(HealthCheck))
    @given(strategy)
    def search(base):
        if len(receipts)>=max_pairs:
            return
        proposal=propose_relational_candidates(base,CONTRACT,signature,mutator_id=operator,seen=seen)
        decisions.append(dict(status=proposal["status"],reasons=proposal["reasons"],
                              anchor_digest=input_identity(base),proposal_count=len(proposal["candidates"])))
        if not proposal["candidates"]:
            return
        selected=proposal["candidates"][0]
        receipt=_measure_pair(target,oracle,base,selected["input"],reset=_reset_authored_fixture,structure=structure)
        receipt.update(mutator_id=operator,signature_sha256=digest(signature),
            proposal_sha256=digest(proposal),relationship=selected["relationship"])
        receipt.pop("receipt_sha256"); receipt["receipt_sha256"]=digest(receipt)
        receipts.append(receipt)
        seen.add(selected["input_digest"]); seen.add(input_identity(base))
        hypothesis_target(float(sum(row["status"]=="FAILURE" for rows in receipt["branches"].values() for row in rows)),label="authored_relational_observed_failures")
    search()
    cost={name:sum(r["cost"][name] for r in receipts) for name in ("target_calls","oracle_calls","reset_calls")}
    cost["wall_seconds"]=time.perf_counter()-started
    return dict(schema="tomolab-relational-native-functional-v1",evidence_class=EVIDENCE_CLASS,
        engine="NATIVE_HYPOTHESIS_GIVEN_TARGET_PUBLIC_STRATEGY",seed=seed,budget=budget,
        actual=cost,receipts=receipts,decisions=decisions,signature=signature,
        routing="AUTHORED_MECHANISM_SELECTION_NOT_LEARNED_OR_BLIND",
        status="COMPLETE" if receipts and all(r["label"]!="UNKNOWN" for r in receipts) else "HOLD_MEASUREMENT",
        learning_updates=0,external_target_calls=0,scope="FUNCTIONAL_ONLY_NOT_EQUAL_COST_POLICY_UTILITY")


def _write(path,value):
    with path.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=True,sort_keys=True,separators=(",",":"))
        stream.write("\n")


def run_probe(workspace,*,allow_local_execution=False,seed=47,budget=24):
    """Run only this module's four exposed fixtures, with explicit opt-in.

    Each of the two paths has a per-fixture Target/Oracle ceiling of budget.
    This is a bounded functional smoke probe, not a performance comparison.
    """
    if allow_local_execution is not True:
        raise PermissionError("explicit --allow-local-execution is required for authored fixtures")
    if type(seed) is not int or not 0<=seed<2**32 or type(budget) is not int or not 12<=budget<=48:
        raise ValueError("seed must be uint32; per-path functional budget must be 12..48")
    workspace=Path(workspace)
    workspace.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    registration=dict(schema="tomolab-structural-probe-contract-v1",evidence_class=EVIDENCE_CLASS,
        contract=CONTRACT,seed=seed,budget_per_fixture_per_path=budget,
        total_target_cap=len(_cases())*2*budget,total_oracle_cap=len(_cases())*2*budget,
        total_reset_cap=len(_cases())*(budget//6)*6,
        source=dict(sha256=CONSULTATION_SHA256,pages=[23,24,25,26,27,28,29,30,31,32,33,34,37,38,39]),
        cases=[dict(mutator_id=o,implementation_sha256=_sha(t),oracle_sha256=_sha(r)) for o,t,r in _cases()],
        real_eligible=0,real_research_execution=False,independent_oos=False,allow_release=False,
        all_m0_modified=False,learning_updates=0,baseline="EXISTING_RUN_ONLINE_METHOD_A_NATIVE_HYPOTHESIS",
        relational="SEPARATE_NATIVE_GIVEN_FUNCTIONAL_LOCAL_PAIRS",guarantees_no_regression=False)
    registration["contract_sha256"]=digest(registration)
    _write(workspace/"contract.json",registration)
    rows=[]
    for index,(operator,target,reference) in enumerate(_cases()):
        baseline=run_online(target,reference,CONTRACT,method="A",seed=seed,budget=budget,
                            shrink_budget=0,max_seconds=10,mode="structural")
        relational=_run_relational(target,reference,operator,seed=seed,budget=budget)
        _write(workspace/("case-"+str(index+1)+".json"),dict(native_baseline=baseline,relational=relational))
        rows.append(dict(mutator_id=operator,native_baseline=dict(method=baseline["method"],
            engine=baseline.get("hypothesis",{}).get("engine","BOUNDARY_ERROR"),status=baseline["status"],
            target_calls=baseline["target_calls"],oracle_calls=baseline["oracle_calls"],reset_calls=0,
            confirmed_inputs=len(baseline["confirmed_failures"])),
            relational=dict(engine=relational["engine"],status=relational["status"],**relational["actual"],
                pairs=len(relational["receipts"]),labels={label:sum(r["label"]==label for r in relational["receipts"])
                    for label in ("gain","loss","neutral_pass","neutral_failure","UNKNOWN")})))
    actual={name:sum(row[path][name] for row in rows for path in ("native_baseline","relational"))
            for name in ("target_calls","oracle_calls","reset_calls")}
    summary=dict(schema="tomolab-structural-probe-summary-v1",evidence_class=EVIDENCE_CLASS,
        status="FUNCTIONAL_COMPLETE" if all(r["native_baseline"]["status"]=="COMPLETE" and r["relational"]["status"]=="COMPLETE" for r in rows) else "HOLD_MEASUREMENT",
        contract_sha256=registration["contract_sha256"],cases=rows,actual=actual,
        caps=dict(target_calls=registration["total_target_cap"],oracle_calls=registration["total_oracle_cap"],reset_calls=registration["total_reset_cap"]),
        wall_seconds=time.perf_counter()-started,real_eligible=0,external_target_calls=0,
        paid_api_calls=0,learning_updates=0,independent_oos_cases=0,
        utility="NOT_ESTABLISHED",policy_no_regression="NOT_GUARANTEED",
        limitation="EXPOSED_AUTHORED_FIXTURES_AND_MECHANISM_SELECTED_PROPOSALS_NOT_BLIND_TRANSFER")
    if any(actual[name]>summary["caps"][name] for name in actual):
        raise ValueError("actual functional calls exceeded frozen caps")
    _write(workspace/"summary.json",summary)
    return summary
