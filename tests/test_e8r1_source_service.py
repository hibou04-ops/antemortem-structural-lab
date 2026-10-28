"""Bounded authored callbacks only; no historical Source/Target execution."""
from copy import deepcopy
import pytest

from test_e8_evidence import record, ledger
from tomolab.discovery.knowledge_service import run_source_development
from tomolab.discovery.evaluation_readiness import EvaluationReadiness
from tomolab.discovery.claim_semantics import SUFFICIENT, EXACT, NECESSARY
from tomolab.discovery.schema import canonical

POLICY=dict(kind="FINITE_JSON",absolute_tolerance=1e-10,relative_tolerance=1e-8,
            undefined="EXECUTION_ERROR",exceptions="EXECUTION_ERROR")


def context():
    value=record()
    return dict(spec=value["spec"],source_provenance=value["provenance"]["origin"],comparison_policy=POLICY)


def two_points(spec,predicate,**settings):
    for point in ({"value":0},{"value":1}):
        if predicate(point):return {"witness":point,"status":"COUNTEREXAMPLE_FOUND"}
    return {"witness":None,"status":"NOT_REFUTED_WITHIN_BUDGET"}


def test_source_approval_and_comparison_contract_precede_callbacks():
    def forbidden(**point):pytest.fail("preflight executed a callback")
    with pytest.raises(PermissionError):run_source_development(forbidden,lambda **p:forbidden(**p),**context())
    values=context();values["comparison_policy"]={**POLICY,"absolute_tolerance":float("nan")}
    with pytest.raises(ValueError,match="finite"):
        run_source_development(forbidden,lambda **p:forbidden(**p),trusted_execution=True,**values)


def test_numeric_source_contract_is_preserved_instead_of_raw_json_equality(monkeypatch):
    monkeypatch.setattr("tomolab.discovery.hypothesis_adapter.native_find",two_points)
    result=run_source_development(lambda value:float(value)+1e-12,lambda value:float(value),
        method="A",budget=6,guidance_budget=0,trusted_execution=True,**context())
    assert not result["found"] and result["error"] is None
    assert result["target_calls"]==result["oracle_calls"]==2
    assert not any(row["failed"] for row in result["rows"])


def test_replays_use_actual_same_per_side_budget(monkeypatch):
    monkeypatch.setattr("tomolab.discovery.hypothesis_adapter.native_find",two_points)
    result=run_source_development(lambda value:value+int(value==1),lambda value:value,
        method="B",budget=4,guidance_budget=0,trusted_execution=True,**context())
    assert result["found"] and result["replay_status"]=="MATCHED_TWICE"
    assert result["target_calls"]==result["oracle_calls"]==4
    assert sum(row["phase"]=="independent-replay" for row in result["rows"])==2
    assert result["external_transfer"]=="NOT_EXECUTED_READINESS_BLOCKED"


def test_domain_and_oracle_errors_are_not_product_failures_or_normal_refutations(monkeypatch):
    monkeypatch.setattr("tomolab.discovery.hypothesis_adapter.native_find",two_points)
    def broken(value):raise ArithmeticError("authored reference error")
    result=run_source_development(lambda value:value,broken,method="A",budget=6,guidance_budget=0,
        input_accepts=lambda point:point["value"]==1,trusted_execution=True,**context())
    assert result["status"]=="ABORTED_EXECUTION_ERROR" and not result["found"]
    assert result["target_calls"]==0 and result["oracle_calls"]==1 and result["rows"]==[]
    assert result["domain_rejections"][0]["label"] is None


def test_native_predicate_attempts_are_distinct_from_actual_oracle_calls(monkeypatch):
    def native(spec,predicate,**settings):
        predicate({"value":0});predicate({"value":1})
        return {"witness":None,"oracle_calls":2}
    monkeypatch.setattr("tomolab.discovery.hypothesis_adapter.native_find",native)
    result=run_source_development(lambda value:value,lambda value:value,method="A",budget=6,guidance_budget=0,
        input_accepts=lambda point:point["value"]==1,trusted_execution=True,**context())
    assert result["native"]["predicate_calls"]==2
    assert result["native"]["oracle_calls"]==result["native"]["target_calls"]==1
    assert result["oracle_calls"]==result["target_calls"]==1


def partial_source():
    bundle=ledger()
    values=[record("partial-first",0,True),record("partial-other",1,True),record("normal-region",-1,False)]
    for value in values:bundle.ingest(value,trusted_host=True)
    archive=bundle.build_knowledge_archive(semantic_policy={})
    return bundle,archive


def test_readiness_uses_each_claims_refutation_direction_without_weakening_transfer():
    bundle,archive=partial_source()
    same=[c for c in archive.claims() if c["typed_relation"]=={"term":{"kind":"value","roles":["quantity"]},"operator":"eq","value":0}]
    if not same:
        # Roles are taken from the authored contract rather than invented here.
        role=archive.spec["inputs"][0]["role"]
        same=[c for c in archive.claims() if c["typed_relation"]=={"term":{"kind":"value","roles":[role]},"operator":"eq","value":0}]
    bykind={c["claim_kind"]:c for c in same};assert len(bykind)==4
    ready=EvaluationReadiness()
    assert ready._counterevidence(bundle,archive,[bykind[SUFFICIENT]],source_only=True)=={}
    assert bykind[EXACT]["claim_id"] in ready._counterevidence(bundle,archive,[bykind[EXACT]],source_only=True)
    assert bykind[NECESSARY]["claim_id"] in ready._counterevidence(bundle,archive,[bykind[NECESSARY]],source_only=True)
    frozen=archive.freeze()
    blocked=EvaluationReadiness(evidence_bundle=bundle.snapshot(),knowledge_snapshot=frozen,targets=[]).authorize_final_comparison()
    assert blocked["status"]=="NOT_EXECUTED_READINESS_BLOCKED"
    assert "READINESS_BLOCKED_NO_INDEPENDENT_CORROBORATION" in blocked["blockers"]


def test_empirical_experiment_never_replaces_actual_oracle_labels(monkeypatch):
    monkeypatch.setattr("tomolab.discovery.hypothesis_adapter.native_find",two_points)
    monkeypatch.setattr("tomolab.discovery.knowledge_engine.generate_pool",lambda spec,**kw:[{"value":0},{"value":1},{"value":-1}])
    _,archive=partial_source();frozen=archive.freeze();before=canonical(frozen)
    result=run_source_development(lambda value:value,lambda value:value,method="C",archive=frozen,
        budget=6,guidance_budget=2,pool_size=3,trusted_execution=True,allow_unvalidated_empirical=True,**context())
    assert result["target_calls"]>0 and not result["found"]
    assert not any(row["failed"] for row in result["rows"])
    assert result["generator_feedback"]==0 and result["archive_updated"] is False
    assert canonical(frozen)==before
