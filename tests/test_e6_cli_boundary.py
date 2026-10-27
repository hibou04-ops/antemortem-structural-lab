"""E6 CLI, parent-side information controls and actual renamed-target replay."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def bundle(name="stack-contract.json"):
    return json.loads((ROOT/"examples/temporal"/name).read_text(encoding="utf-8"))


def run(*args):
    result = subprocess.run([sys.executable,"-m","tomolab",*args],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=40)
    assert result.returncode == 0,result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def test_cli_real_learning_freeze_renamed_transfer_and_independent_replay(tmp_path):
    from tomolab.discovery.native_stateful import evaluate_temporal_trace
    from tomolab.mold.service import _load
    path = tmp_path/"source.json"
    run("stateful-demo","--budget","128","--pool-size","12","--shrink-budget","64","--output",str(path))
    learned = json.loads(path.read_text(encoding="utf-8"))
    assert learned["status"]=="COUNTEREXAMPLE_FOUND" and learned["snapshot"]["frozen"]
    assert learned["snapshot"]["status"]=="HYPOTHESES_REMAIN"
    assert learned["snapshot"]["temporal_metrics"]["activation_count"]==1
    assert learned["snapshot"]["temporal_metrics"]["guided_queries"]>0
    assert learned["metrics"]["guided_trace_calls"]>0
    assert learned["counterexample"]["replay"]=="MATCHED_TWICE"
    plan = run("stateful-plan","--snapshot",str(path),"--contract","examples/temporal/renamed-contract.json",
               "--budget","8","--pool-size","12")
    assert plan["gate"]["status"]=="APPLICABLE_FOR_PROBING" and plan["final_feedback_allowed"] is False
    assert plan["gate"]["mapping"]["pop"]=="take"
    case = bundle("renamed-contract.json")
    target,_ = _load(ROOT/"examples/temporal/renamed_target.py","make_subject")
    model,_ = _load(ROOT/"examples/temporal/renamed_oracle.py","make_subject")
    def callback(action):
        return lambda subject,argument:subject.step(action,argument)
    operations = {a["name"]:{"target":callback(a["name"]),"model":callback(a["name"])} for a in case["temporal_contract"]["actions"]}
    replays = [evaluate_temporal_trace(case["spec"],case["temporal_contract"],target,model,operations,point["inputs"],
               snapshot=lambda subject:subject.snapshot(),trusted_execution=True) for point in plan["candidates"]]
    assert any(r["failed"] for r in replays)
    assert plan["snapshot"]["frozen"] and plan["snapshot"]["temporal_metrics"]["feedback_records"]==0


def test_cli_clean_native_path_has_no_temporal_activation():
    result = run("stateful-demo","--case","clean","--budget","12","--pool-size","4","--shrink-budget","0")
    assert result["status"]=="NOT_REFUTED_WITHIN_BUDGET"
    assert result["snapshot"]["temporal_metrics"]["activation_count"]==0
    assert result["metrics"]["guided_trace_calls"]==0


def test_public_contract_inspection_never_imports_target(tmp_path):
    inspected = run("stateful-inspect","--contract","examples/temporal/stack-contract.json")
    assert inspected["execution"]=="NOT_EXECUTED"
    marker = tmp_path/"executed"
    target = tmp_path/"unreviewed.py"
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef make_subject(): return None\n",encoding="utf-8")
    model = tmp_path/"model.py"
    model.write_text("def make_subject(): return None\n",encoding="utf-8")
    invalid = bundle()
    invalid["spec"]["inputs"][0]["type"]["min_size"] = 1
    contract = tmp_path/"invalid.json"
    contract.write_text(json.dumps(invalid),encoding="utf-8")
    result = subprocess.run([sys.executable,"-m","tomolab","stateful-run",str(target),"--oracle-file",str(model),
                             "--contract",str(contract),"--allow-local-execution"],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode!=0 and not marker.exists()


class WriteSpy:
    called = False
    def write(self,value):
        self.called=True
        raise ValueError("transport must not be reached")


def parent():
    from tomolab.discovery.temporal_boundary import TemporalBoundary
    value = bundle()
    boundary = object.__new__(TemporalBoundary)
    boundary._request_lock = threading.Lock()
    boundary._spec = value["spec"]
    boundary._temporal_contract = value["temporal_contract"]
    boundary._frozen = False
    spy = WriteSpy()
    boundary.process = SimpleNamespace(stdin=spy)
    return boundary,spy


def test_forbidden_information_and_invalid_native_candidates_stop_before_transport():
    boundary,spy = parent()
    evidence = {"kind":"FAILURE","evidence_id":"dev-1","inputs":{"trace":[["push",0],["pop",0]]},
                "invariant":boundary._spec["contract"]["invariants"][0],"category":"state_violation",
                "signature":"declared-state","first_failure_index":1}
    for field in ("expected","actual","source","final_label","model_score"):
        with pytest.raises(ValueError):
            boundary.request("observe",evidence={**evidence,field:"not-authorized"})
    with pytest.raises(ValueError,match="precondition"):
        boundary.request("register",inputs={"trace":[["pop",0]]})
    assert not spy.called


def test_frozen_register_and_feedback_stop_before_transport():
    boundary,spy = parent()
    boundary._frozen=True
    for action,fields in (("register",{"inputs":{"trace":[["push",0]]}}),("observe",{"evidence":{}})):
        with pytest.raises(ValueError,match="frozen"):
            boundary.request(action,**fields)
    assert not spy.called


def test_e6_generator_has_no_evaluator_target_or_symbolic_modules():
    from tomolab.discovery.temporal_boundary import GENERATOR_FILES
    assert {"temporal.py","temporal_engine.py","temporal_transfer.py","efficient.py"}<=set(GENERATOR_FILES)
    assert not {"analysis.py","service.py","temporal_service.py","native_stateful.py","symbolic.py","stateful.py"} & set(GENERATOR_FILES)
    assert all((ROOT/"tomolab/discovery"/name).is_file() for name in GENERATOR_FILES)
