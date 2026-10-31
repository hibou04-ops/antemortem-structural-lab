"""Functional corpus eligibility and comparison fairness, never final research."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from benchmarks import online as benchmark
from tomolab.discovery.online_schema import hypothesis_strategy, validate_input, input_identity
from tomolab.discovery.schema import digest


def test_corpus_separates_developer_known_sources_targets_and_controls():
    rows = benchmark.cases()
    assert len(rows) == 20
    assert len({row.id for row in rows}) == 20
    assert sum(row.role == "SOURCE" for row in rows) == 5
    assert sum(row.role == "TARGET" for row in rows) == 10
    assert sum(row.role == "CONTROL" for row in rows) == 5
    for axis in {row.axis for row in rows}:
        selected = [row for row in rows if row.axis == axis]
        assert [row.role for row in selected].count("TARGET") == 2
        assert all(row.metadata()["project_independence"] == "NOT_ESTABLISHED" for row in selected)
        assert all(row.metadata()["developer_known"] is True for row in selected)
    identities = [row.metadata()["identity"] for row in rows]
    assert len({identity["implementation_sha256"] for identity in identities}) == 20


@settings(max_examples=32, deadline=None, database=None)
@given(st.data())
def test_clean_controls_agree_with_independent_contract_models(data):
    for case in benchmark.cases():
        if case.role != "CONTROL":
            continue
        point = data.draw(hypothesis_strategy(case.contract), label=case.axis)
        before = deepcopy(point)
        assert case.target(deepcopy(point)) == case.oracle(deepcopy(point))
        assert point == before
        assert case.target(deepcopy(point)) == case.target(deepcopy(point))


@pytest.mark.parametrize("axis,witness", [
    ("numerical", [0.0]), ("container", [1]), ("serialization", "aa\n\n"),
    ("state", [{"op": "push", "value": 1}, {"op": "pop", "value": 0}]),
    ("graph", {"n": 1, "edges": []}),
])
def test_evaluator_only_eligibility_witness_is_valid_and_reproducible(axis, witness):
    for case in benchmark.cases():
        if case.role != "TARGET" or case.axis != axis:
            continue
        assert validate_input(witness, case.contract)
        expected = case.oracle(deepcopy(witness))
        observations = []
        for _ in range(3):
            try:
                actual = case.target(deepcopy(witness))
            except Exception as exc:
                observations.append(("exception", type(exc).__name__))
            else:
                observations.append(("return", actual))
        assert observations[0] == observations[1] == observations[2]
        assert observations[0] != ("return", expected)


def test_source_preparation_only_observes_sources(monkeypatch):
    from tomolab.discovery import online_engine, online_learning
    observed = []
    sources = {case.target for case in benchmark.cases() if case.role == "SOURCE"}
    def execute(target, oracle, contract, **kwargs):
        assert target in sources
        observed.append(target)
        point=[] if contract["kind"] not in ("text","graph") else "" if contract["kind"] == "text" else {"n":0,"edges":[]}
        return dict(observations=[dict(input=point,input_digest=input_identity(point),status="PASS")],
                    target_calls=1, oracle_calls=1)
    def learn(rows):
        return dict(source_ids=sorted({row["source_identity"] for row in rows}))
    monkeypatch.setattr(online_engine, "run_online", execute)
    monkeypatch.setattr(online_learning, "learn_mold", learn)
    result = benchmark.prepare_sources(benchmark.default_config())
    assert len(observed) == 5
    assert result["target_evaluation_calls"] == 0
    assert len(result["molds"]["ALL"]["source_ids"]) == 5
    for fold in set(result["molds"])-{"ALL"}:
        assert len(result["molds"][fold]["source_ids"]) == 4


def test_common_runner_uses_same_c_d_engine_budgets_and_fresh_state(monkeypatch, tmp_path):
    from tomolab.discovery import online_engine
    config = benchmark.default_config()
    config["seeds"] = [2081]
    prepared = dict(config_digest=digest(config), target_evaluation_calls=0,
                    records=[],source_runs=[], molds={fold: {"fold": fold} for fold in ["ALL", "numerical", "container", "serialization", "state", "graph"]},
                    cost={}, target_calls=0, oracle_calls=0)
    invocations = []
    def execute(target, oracle, contract, **kwargs):
        invocations.append((target, oracle, deepcopy(contract), deepcopy(kwargs)))
        if kwargs["mold"] is not None:
            kwargs["mold"]["local_mutation"] = True
        return dict(status="COMPLETE", events=[], target_calls=0, oracle_calls=0,
                    first_confirmed_failure=None,cost={"wall_seconds":0})
    monkeypatch.setattr(online_engine, "run_online", execute)
    result = benchmark.run_comparison(config, prepared,event_path=tmp_path/"events.jsonl")
    assert len(result["runs"]) == 120
    for target in {call[0] for call in invocations}:
        selected = [call for call in invocations if call[0] is target]
        assert len(selected) == 8
        for call in selected:
            assert call[3]["budget"] == 48
            assert call[3]["shrink_budget"] == 8
            assert call[3]["seed"] == 2081
            assert call[3]["max_seconds"] == 30
    assert not any("local_mutation" in value for value in prepared["molds"].values())
    assert all(summary["methods"]["E9_D"]["missed_runs"] == 10
               for summary in result["summary"].values())
    assert all(item["measurement"] is None for summary in result["summary"].values()
               for item in summary["methods"]["E9_D"]["first_confirmed"])


def test_configuration_and_preparation_fail_closed():
    config = benchmark.default_config()
    config["allow_release"] = True
    with pytest.raises(ValueError):
        benchmark.validate_config(config)
    config = benchmark.default_config()
    config["seeds"] = [1, 1]
    with pytest.raises(ValueError):
        benchmark.validate_config(config)
    with pytest.raises(ValueError):
        benchmark.run_comparison(benchmark.default_config(), dict(config_digest="0"*64))


def test_source_replays_are_exact_contract_filtered_and_not_target_witnesses():
    records = [dict(input=[1], status="FAILURE", contract=dict(kind="sequence_int")),
               dict(input=[1], status="FAILURE", contract=dict(kind="sequence_int")),
               dict(input=[2], status="PASS", contract=dict(kind="sequence_int")),
               dict(input="aa", status="FAILURE", contract=dict(kind="text"))]
    assert benchmark._replays(records, dict(kind="sequence_int")) == [[1]]
    assert benchmark._replays(records, dict(kind="text")) == ["aa"]


@pytest.mark.parametrize("field,value", [("maximum_wall_ratio", True),
    ("maximum_wall_ratio", .9), ("require_more_detected_defects", False),
    ("forbid_C_detected_D_missed", False), ("overhead_target", "PENDING")])
def test_success_criteria_cannot_be_silently_weakened(field, value):
    config = benchmark.default_config()
    config["success"][field] = value
    with pytest.raises(ValueError):
        benchmark.validate_config(config)


def test_registration_checks_frozen_bytes_before_any_execution(monkeypatch, tmp_path):
    path=Path(__file__).resolve().parents[1]/"scripts/evaluate-online.py"
    spec=importlib.util.spec_from_file_location("online_evaluation_driver_test",path)
    driver=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    monkeypatch.setattr(driver,"ROOT",tmp_path)
    (tmp_path/"tomolab").mkdir()
    (tmp_path/"scripts").mkdir()
    (tmp_path/"benchmarks").mkdir()
    (tmp_path/"tomolab/a.py").write_text("# registered\n")
    (tmp_path/"scripts/evaluate-online.py").write_text("# driver\n")
    (tmp_path/"benchmarks/online.py").write_text("# fixtures\n")
    class Fixture:
        role="TARGET"
        def metadata(self):
            return {"id":"fixture","identity":dict.fromkeys(("canonical_function_identity",
                "cross_revision_function_key","normalized_ast_clone_sha256","implementation_sha256"),"2"*64),
                "oracle_sha256":"3"*64}
    monkeypatch.setattr(driver,"cases",lambda:[Fixture()])
    actual=driver.environment_identity()
    registered={**actual,"python":"0.0.0"}
    config=benchmark.default_config()
    prepared=dict(molds={"ALL":{"artifact_digest":"1"*64}},records=[],source_runs=[])
    files={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()
           for name in ("tomolab/a.py","scripts/evaluate-online.py","benchmarks/online.py")}
    initial={"ALL":"1"*64}
    profile=dict(algorithm_digest=digest(files),initial_knowledge_digest=digest(initial),
                 configuration_digest=digest(config))
    registration=dict(schema="tomolab-online-registration-v1",frozen_config=config,
        source_preparation_digest=digest(prepared),initial_molds=initial,
        code_files=files,targets=[Fixture().metadata()],profile=profile,environment=registered)
    registration["registration_digest"]=digest(registration)
    registration_path=tmp_path/"registration.json"
    registration_path.write_text(json.dumps(registration),encoding="utf-8")
    output=tmp_path/"checked.json"
    assert driver.main(["--check-registration","--registration",str(registration_path),
                        "--output",str(output)]) == 0
    receipt=json.loads(output.read_text())
    assert receipt["target_calls"] == receipt["oracle_calls"] == 0
    assert receipt["environment_matches_registered"] is False
    assert receipt["ast_identity_verified"] is False
    assert receipt["source_preparation_verified"] is False
    with pytest.raises(ValueError,match="Python"):
        driver.validate_registration(registration,config,prepared)
    changed=deepcopy(registration)
    changed["targets"][0]["identity"]["normalized_ast_clone_sha256"]="4"*64
    changed["registration_digest"]=digest({k:v for k,v in changed.items() if k!="registration_digest"})
    driver.validate_registration(changed,config,check_environment=False)
    changed["environment"]=actual
    changed["registration_digest"]=digest({k:v for k,v in changed.items() if k!="registration_digest"})
    with pytest.raises(ValueError,match="identity changed"):
        driver.validate_registration(changed,config,check_environment=False)
    changed=deepcopy(registration)
    changed["targets"][0]["identity"]["implementation_sha256"]="4"*64
    changed["registration_digest"]=digest({k:v for k,v in changed.items() if k!="registration_digest"})
    with pytest.raises(ValueError,match="identity changed"):
        driver.validate_registration(changed,config,check_environment=False)
    (tmp_path/"tomolab/a.py").write_text("# changed after freeze\n")
    with pytest.raises(ValueError,match="changed after"):
        driver.validate_registration(registration,config,check_environment=False)
    files.pop("tomolab/a.py")
    registration["registration_digest"]=digest({k:v for k,v in registration.items()
                                                if k!="registration_digest"})
    with pytest.raises(ValueError,match="all runtime"):
        driver.validate_registration(registration,config,check_environment=False)


def test_ordered_mapping_source_inputs_survive_storage_and_reject_order_tampering(tmp_path):
    point={"b":1,"a":2}
    other={"a":2,"b":1}
    row=dict(input=point,input_digest=input_identity(point),status="FAILURE",contract=dict(kind="mapping"))
    prepared=dict(records=[row],source_runs=[])
    assert benchmark.validate_prepared_inputs(prepared)
    prepared["records"][0]["input"]=other
    with pytest.raises(ValueError,match="mapping insertion order"):
        benchmark.validate_prepared_inputs(prepared)
    row["input"]=point
    opposite={**row,"input":other,"input_digest":input_identity(other)}
    assert len(benchmark._replays([row,opposite],row["contract"])) == 2
    path=Path(__file__).resolve().parents[1]/"scripts/evaluate-online.py"
    spec=importlib.util.spec_from_file_location("ordered_online_driver_test",path)
    driver=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    output=tmp_path/"ordered-source.json"
    driver.write_new(output,dict(records=[row]))
    assert list(json.loads(output.read_text())["records"][0]["input"]) == ["b","a"]
