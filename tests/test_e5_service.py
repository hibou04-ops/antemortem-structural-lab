import json
from pathlib import Path

import pytest

from tomolab.cli import EXAMPLES, main
from tomolab.discovery.boundary import DiscoveryBoundary, GENERATOR_FILES
from tomolab.discovery.schema import validate_spec
from tomolab.discovery.service import evaluate_pair, run_discovery


def contract(type_):
    return validate_spec({"schema":"tomolab-discovery-spec-v1","task_id":"service-integration",
                          "inputs":[{"name":"value","role":"operand","type":type_}],
                          "contract":{"id":"identity-contract","operation":"identity","preconditions":[],
                                      "invariants":["reference"],"state_model":"stateless","graph_signature":"UNKNOWN"}})


def test_real_sequence_cli_learns_freezes_and_transfers(tmp_path):
    run = tmp_path / "run.json"
    assert main(["discovery-demo","--budget","12","--pool-size","32","--shrink-budget","16",
                 "--solver","z3","--output",str(run)]) == 0
    result = json.loads(run.read_text(encoding="utf-8"))
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["snapshot"]["frozen"] is True
    assert result["snapshot"]["version"] > 0
    assert result["snapshot"]["query_metrics"]["native_rounds"] > 0
    assert result["snapshot"]["query_metrics"]["solver_calls"] > 0
    assert result["metrics"]["duplicate_candidates"] == 0
    assert result["metrics"]["oracle_calls"] <= result["metrics"]["hard_call_limit"]
    assert result["counterexample"]["replay"] == "MATCHED_TWICE"
    assert result["subjective_assessment"]["used_for_verdict"] is False
    plan = tmp_path / "plan.json"
    folder = EXAMPLES / "discovery"
    assert main(["discovery-plan","--snapshot",str(run),"--spec",str(folder/"sequence-renamed-spec.json"),
                 "--public-source",str(folder/"sequence_renamed.py"),"--budget","8","--pool-size","32",
                 "--output",str(plan)]) == 0
    payload = json.loads(plan.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert payload["gate"]["failure_recurrence"] == "UNKNOWN"
    assert payload["final_feedback_allowed"] is False
    assert len(payload["candidates"]) == 8


def test_real_bounded_state_trace_cli(tmp_path):
    path = tmp_path / "state.json"
    assert main(["discovery-demo","--case","state","--budget","16","--pool-size","32",
                 "--shrink-budget","32","--output",str(path)]) == 0
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["counterexample"]["inputs"]["trace"]
    assert result["counterexample"]["actual"] != result["counterexample"]["expected"]
    assert result["metrics"]["oracle_calls"] <= 50


@pytest.mark.parametrize("type_,expected_type", [
    ({"kind":"int","min":-2,"max":2},int),
    ({"kind":"float","min":-2,"max":2},float),
    ({"kind":"str","alphabet":"ab ","min_size":0,"max_size":4},str),
    ({"kind":"list","items":{"kind":"int","min":-2,"max":2},"min_size":0,"max_size":3},list),
    ({"kind":"tuple","items":[{"kind":"int","min":-2,"max":2},{"kind":"str","alphabet":"ab","min_size":0,"max_size":2}]},tuple),
    ({"kind":"dict","keys":["a","b"],"values":{"kind":"int","min":-2,"max":2},"min_size":0,"max_size":2},dict),
])
def test_native_types_reach_trusted_evaluator(type_,expected_type):
    observed = []
    def target(value):
        observed.append(type(value))
        return value
    def oracle(value):
        return value
    result = run_discovery(target,oracle,contract(type_),budget=3,pool_size=8,shrink_budget=0,
                           trusted_execution=True)
    assert observed and set(observed) == {expected_type}
    assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert result["metrics"]["oracle_calls"] == len(observed)


def test_exact_json_comparison_and_exception_categories():
    spec = contract({"kind":"int","min":0,"max":2})
    assert evaluate_pair(lambda value:True,lambda value:1,{"value":1},spec)["failure"] is True
    def fail(value):
        raise ValueError("message is not a verdict")
    def same_category(value):
        raise ValueError("another message")
    assert evaluate_pair(fail,same_category,{"value":1},spec,expected_oracle_exceptions=(ValueError,))["failure"] is False
    assert evaluate_pair(fail,lambda value:1,{"value":1},spec)["category"] == "exception"
    with pytest.raises(TypeError):
        evaluate_pair(lambda value:object(),lambda value:1,{"value":1},spec)
    def broken_oracle(value):
        raise RuntimeError("model is broken")
    with pytest.raises(RuntimeError,match="model is broken"):
        evaluate_pair(lambda value:1,broken_oracle,{"value":1},spec)
    def positional_target(value, /):
        return value
    assert evaluate_pair(positional_target,lambda value:value,{"value":1},spec)["failure"] is False
    with pytest.raises(TypeError):
        evaluate_pair(lambda value,missing:1,lambda value:1,{"value":1},spec)


def test_forbidden_information_rejected_before_transport_and_after_freeze(monkeypatch):
    spec = contract({"kind":"int","min":-2,"max":2})
    class ForbiddenWrite:
        def write(self,*args):
            raise AssertionError("forbidden data crossed transport")
    with DiscoveryBoundary() as boundary:
        boundary.request("init",spec=spec,pool_size=8)
        assert not (boundary.root/"tomolab/discovery/service.py").exists()
        assert not (boundary.root/"tomolab/discovery/symbolic.py").exists()
        assert not (boundary.root/"tomolab/discovery/stateful.py").exists()
        assert {p.name for p in (boundary.root/"tomolab/discovery").glob("*.py")} == set(GENERATOR_FILES)
        with monkeypatch.context() as patch:
            patch.setattr(boundary.process,"stdin",ForbiddenWrite())
            with pytest.raises(ValueError):
                boundary.request("propose",final_answers=[1],score=100)
        frozen = boundary.request("freeze")
        with monkeypatch.context() as patch:
            patch.setattr(boundary.process,"stdin",ForbiddenWrite())
            with pytest.raises(ValueError,match="frozen"):
                boundary.request("observe",evidence={"kind":"FAILURE"})
    with DiscoveryBoundary() as boundary:
        with monkeypatch.context() as patch:
            patch.setattr(boundary.process,"stdin",ForbiddenWrite())
            for name in ("private/path", "private\nsource", "undeclared"):
                with pytest.raises(ValueError):
                    boundary.request("transfer",snapshot=frozen,spec=spec,target_ir=None,mapping={"value":name})


def test_inspect_does_not_execute_source_and_bad_controls_do_not_import(tmp_path):
    marker = tmp_path/"executed"
    target = tmp_path/"target.py"
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef implementation(value: int):\n    return value\n",encoding="utf-8")
    spec = tmp_path/"spec.json"
    spec.write_text(json.dumps(contract({"kind":"int","min":-2,"max":2})),encoding="utf-8")
    assert main(["discovery-inspect",str(target),"--spec",str(spec),"--output",str(tmp_path/"ir.json")]) == 0
    assert not marker.exists()
    with pytest.raises(SystemExit) as error:
        main(["discovery-run",str(target),"--oracle-file",str(tmp_path/"oracle.py"),"--spec",str(spec),
              "--public-source",str(target),"--budget","0","--allow-local-execution"])
    assert error.value.code == 2
    assert not marker.exists()
    multiple = contract({"kind":"int","min":-2,"max":2})
    multiple["contract"]["invariants"] = ["reference","unsupported-second"]
    spec.write_text(json.dumps(multiple),encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["discovery-run",str(target),"--oracle-file",str(tmp_path/"oracle.py"),"--spec",str(spec),
              "--public-source",str(target),"--allow-local-execution"])
    assert error.value.code == 2
    assert not marker.exists()
