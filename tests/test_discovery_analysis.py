from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from tomolab.discovery.analysis import analyze_source, analyze_file, validate_transfer
from tomolab.discovery.symbolic import check_contract, extract_candidates, solve_relations


SOURCE = '''def implementation(values: list[int], limit: int) -> list[int]:
    result = []
    for value in values:
        if value >= limit:
            result.append(value)
    return result
'''


def spec(ir, names=("values", "limit")):
    return {"schema":"tomolab-discovery-spec-v1", "task_id":"test-analysis",
            "inputs":[{"name":names[0],"role":"items","type":{"kind":"list","items":{"kind":"int","min":-10,"max":10},"min_size":0,"max_size":6}},
                      {"name":names[1],"role":"threshold","type":{"kind":"int","min":-10,"max":10}}],
            "contract":{"id":"filter-ge-v1","operation":"filter-ge","preconditions":[],
                        "invariants":["stable-subsequence"],"state_model":"pure",
                        "graph_signature":ir["graph_signature"]}}


def test_static_ir_never_executes_and_contains_graph_dependencies(tmp_path):
    marker = tmp_path / "executed"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + SOURCE
    path = tmp_path / "target.py"
    path.write_text(source, encoding="utf-8")
    ir = analyze_file(path, roles={"values":"items","limit":"threshold"})
    assert not marker.exists()
    assert ir["status"] == "SUPPORTED_STATIC_IR"
    assert ir["control"]["For"] == ir["control"]["If"] == 1
    assert "GtE" in ir["operators"]
    assert "method:append" in ir["calls"]
    assert ir["dependencies"] and ir["state_effects"]
    assert str(marker) not in json.dumps(ir)


def test_literal_free_graph_preserves_roles_under_parameter_and_local_rename():
    left = analyze_source(SOURCE, roles={"values":"items","limit":"threshold"})
    renamed = SOURCE.replace("values", "sequence").replace("limit", "cutoff").replace("result", "answer").replace("value", "entry")
    right = analyze_source(renamed, roles={"sequence":"items","cutoff":"threshold"})
    assert left["graph_signature"] == right["graph_signature"]
    a = analyze_source("def implementation(x:int)->int:\n    return x+1\n", roles={"x":"value"})
    b = analyze_source("def implementation(y:int)->int:\n    return y+99\n", roles={"y":"value"})
    assert a["graph_signature"] == b["graph_signature"]
    assert a["source_sha256"] != b["source_sha256"]
    assert "no semantic" in a["claim"]


def test_control_and_operator_change_changes_graph_and_unsupported_is_explicit():
    a = analyze_source(SOURCE)
    b = analyze_source(SOURCE.replace(">=", "<"))
    assert a["graph_signature"] != b["graph_signature"]
    partial = analyze_source("async def implementation(x:int):\n    return await x\n")
    assert partial["status"] == "PARTIAL_STATIC_IR" and "Await" in partial["unsupported"]
    with pytest.raises(ValueError):
        analyze_source(SOURCE, roles={"values":"one","limit":"one"})
    with pytest.raises(ValueError):
        analyze_source("#" * 262145)


def test_unsupported_nested_and_variadic_arguments_return_partial_ir():
    nested = analyze_source("def implementation(x:int):\n    def inner(z):\n        return z\n    return inner(x)\n")
    variadic = analyze_source("def implementation(x:int, *extra, **options):\n    return x\n")
    assert nested["status"] == variadic["status"] == "PARTIAL_STATIC_IR"
    assert "nested-executable-definition" in nested["unsupported"]
    assert "variadic-arguments" in variadic["unsupported"]


def test_transfer_checks_actual_ir_type_domain_contract_and_role_correspondence():
    left = analyze_source(SOURCE, roles={"values":"items","limit":"threshold"})
    renamed = SOURCE.replace("values", "sequence").replace("limit", "cutoff")
    right = analyze_source(renamed, roles={"sequence":"items","cutoff":"threshold"})
    a,b = spec(left),spec(right,("sequence","cutoff"))
    result = validate_transfer(a,b,left,right)
    assert result["status"] == "APPLICABLE_FOR_PROBING"
    assert result["failure_recurrence"] == "UNKNOWN"
    assert result["mapping"] == {"values":"sequence","limit":"cutoff"}
    for change in ("domain","contract","graph","role"):
        altered=deepcopy(b)
        target_ir=deepcopy(right)
        if change == "domain":
            altered["inputs"][1]["type"]["max"] = 20
        elif change == "contract":
            altered["contract"]["preconditions"] = ["positive-only"]
        elif change == "graph":
            target_ir["graph"]["node"] = "Injected"
        else:
            target_ir["parameters"][0]["role"] = "threshold"
        assert validate_transfer(a,altered,left,target_ir)["status"] == "UNKNOWN"


def test_positional_ir_cannot_be_treated_as_semantic_role_evidence():
    positional=analyze_source(SOURCE)
    source=spec(positional)
    assert validate_transfer(source,source,positional,positional)["status"] == "UNKNOWN"


def test_transfer_rejects_contradictory_source_annotations_and_string_choice_expansion():
    wrong = analyze_source(SOURCE.replace("limit: int", "limit: str"), roles={"values":"items","limit":"threshold"})
    contract = spec(wrong)
    assert validate_transfer(contract,contract,wrong,wrong)["status"] == "UNKNOWN"
    ir=analyze_source("def implementation(s:str)->str:\n    return s\n",roles={"s":"text"})
    source={"schema":"tomolab-discovery-spec-v1","task_id":"strings",
            "inputs":[{"name":"s","role":"text","type":{"kind":"str","alphabet":"ab","min_size":1,"max_size":1,"choices":["a"]}}],
            "contract":{"id":"text-v1","operation":"identity","preconditions":[],"invariants":["same-text"],"state_model":"pure","graph_signature":ir["graph_signature"]}}
    target=deepcopy(source)
    del target["inputs"][0]["type"]["choices"]
    assert validate_transfer(source,target,ir,ir)["status"] == "UNKNOWN"


def test_symbolic_candidate_parser_accepts_only_bounded_literal_calls(tmp_path):
    marker=tmp_path/"executed"
    rows=[{"message":"false when calling check([1, -2], n=3) (which returns False)"},
          {"message":f"false when calling check(__import__('pathlib').Path({str(marker)!r}).touch(), n=3)"},
          {"message":"false when calling unrelated([9], n=3)"}]
    assert extract_candidates(rows,"check",["items","n"]) == [{"items":[1,-2],"n":3}]
    assert not marker.exists()


def test_z3_real_consistency_and_witness_with_validated_dsl():
    variables={"x":{"kind":"int","min":-4,"max":4},"y":{"kind":"int","min":-4,"max":4}}
    total={"op":"add","args":[{"var":"x"},{"var":"y"}]}
    relations=[{"op":"eq","left":total,"right":3},{"op":"gt","left":{"var":"x"},"right":1}]
    result=solve_relations(variables,relations)
    assert result["status"] == "SAT"
    assert result["witness"]["x"]+result["witness"]["y"] == 3
    assert solve_relations(variables,relations+[{"op":"le","left":{"var":"x"},"right":1}])["status"] == "UNSAT"
    with pytest.raises(ValueError):
        solve_relations(variables,[{"op":"eq","left":"__import__('os')","right":1}])
    with pytest.raises(ValueError):
        solve_relations({"x":{"kind":"float","min":-1,"max":1}},relations)


def test_crosshair_actual_counterexample_requires_independent_replay(tmp_path):
    source=tmp_path/"contract_bug.py"
    source.write_text('''def broken(x: int) -> int:
    """post: _ == x + 1"""
    return x
''',encoding="utf-8")
    result=check_contract(source,"broken",timeout_seconds=10,per_condition_seconds=2,trusted_execution=True)
    assert result["status"] == "SYMBOLIC_COUNTEREXAMPLE_CANDIDATE",result
    assert result["exit_code"] == 1 and result["candidates"]
    assert result["candidate_validation"] == "INDEPENDENT_ORACLE_REQUIRED"
    assert result["oracle_calls"] is None and result["source_access"] is True
    for candidate in result["candidates"]:
        # Independently evaluate the literal witness without importing the file.
        assert candidate["x"] != candidate["x"]+1


def test_crosshair_clean_contract_is_not_promoted_to_global_proof(tmp_path):
    source=tmp_path/"contract_clean.py"
    source.write_text('''def clean(x: int) -> int:
    """post: _ == x + 1"""
    return x + 1
''',encoding="utf-8")
    result=check_contract(source,"clean",timeout_seconds=10,per_condition_seconds=2,trusted_execution=True)
    assert result["status"] == "NO_COUNTEREXAMPLE_WITHIN_BUDGET",result
    assert result["candidates"] == []
    with pytest.raises(PermissionError):
        check_contract(source)


def test_crosshair_timeout_cannot_be_claimed_as_pass(tmp_path, monkeypatch):
    source=tmp_path/"timeout_contract.py"
    source.write_text('def slow(x:int)->int:\n    """post: _ == x"""\n    return x\n',encoding="utf-8")
    def timed_out(*args,**kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"",stderr=b"")
    monkeypatch.setattr(subprocess,"run",timed_out)
    result=check_contract(source,"slow",timeout_seconds=0.1,trusted_execution=True)
    assert result["status"] == "UNKNOWN_TIMEOUT" and result["exit_code"] is None


def test_crosshair_no_contract_is_unknown_not_clean(tmp_path):
    source=tmp_path/"no_contract.py"
    source.write_text('def no_contract(x:int)->int:\n    return x\n',encoding="utf-8")
    result=check_contract(source,"no_contract",timeout_seconds=10,per_condition_seconds=1,trusted_execution=True)
    assert result["status"] == "UNKNOWN_NOT_ANALYZED",result
    assert result["candidates"] == []
