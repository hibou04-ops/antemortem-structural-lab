"""CORR authority and real worker tests with authored evaluator observations.

No statistics.correlation, SciPy pearsonr, Source or exact Oracle numeric call
is allowed here. Worker generation uses the unchanged five-module boundary.
These functional tests are not independent implementation research evidence.
"""
from copy import deepcopy
import json
from pathlib import Path
import statistics
import sys

import pytest

from tomolab.discovery import corroboration_adapters as adapters
from tomolab.discovery import corroboration_service as service
from tomolab.discovery import numerical_source
from tomolab.discovery.corroboration_permit import (
    CorroborationExecutionPermit, build_permit_context)
from tomolab.discovery.evaluation_usage import UsageLedger, identity_tokens
from tomolab.discovery.numerical_guidance import numerical_input_digest, public_input_contract
from tomolab.discovery.schema import canonical, digest

ROOT = Path(__file__).parents[1]
REPLAY = {"a":[0.1]*3, "b":[0.1]*3}


@pytest.fixture(autouse=True)
def no_real_numeric_subject_calls():
    watched = {statistics.correlation.__code__, numerical_source.pearson_result.__code__,
               numerical_source.oracle_result.__code__, numerical_source.exact_correlation.__code__}
    entered = []
    previous = sys.getprofile()
    def profile(frame, event, argument):
        if event == "call" and frame.f_code in watched:
            entered.append(frame.f_code.co_name)
        if previous is not None:
            previous(frame, event, argument)
    sys.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
    assert entered == [], "a prevalidation functional test consumed a real numeric subject"


@pytest.fixture(scope="module")
def plans():
    folder = ROOT/"examples/numerical"
    compiled = {"artifact":json.loads((folder/"source-guide.json").read_text()),
                "approval_receipt":json.loads((folder/"source-approval.json").read_text())}
    controls = dict(seed=17,size=3,max_examples=128,
                    excluded_digests=[numerical_input_digest(REPLAY)])
    return {
        "B":service.plan_candidates(method="B", **controls),
        "C":service.plan_candidates(method="C",replay_inputs=[REPLAY],**controls),
        "D":service.plan_candidates(method="D",compiled=compiled,
            expected_digest=compiled["artifact"]["artifact_digest"],**controls),
    }


def context_for(plan, ledger, *, pair_budget=12, shrink_budget=0, identity=None):
    identity = adapters.implementation_identity("python-statistics-correlation") if identity is None else identity
    return build_permit_context(plan,identity,common_input_contract=public_input_contract(),
        resource_budget={"pair_budget":pair_budget,"shrink_budget":shrink_budget},
        authority_id=ledger.authority_id,
        guide_digest=json.loads((ROOT/"examples/numerical/source-guide.json").read_text())["artifact_digest"],
        review_digest="a"*64)


def approved(plan, ledger, **kwargs):
    context = context_for(plan,ledger,**kwargs)
    permit = CorroborationExecutionPermit.from_host_approval(context,deepcopy(context))
    return permit, context


class AuthoredAdapter:
    """Private authored response fixture; never resolves the reviewed APIs."""
    def __init__(self, mode="match"):
        self.mode = mode
        self.counts = dict(target_calls=0,oracle_calls=0,actual_target_function_entries=0)

    @property
    def call_counters(self):
        return deepcopy(self.counts)

    def evaluate(self, point, *, contract):
        self.counts["target_calls"] += 1
        self.counts["actual_target_function_entries"] += 1
        if self.mode == "partial-error":
            raise PermissionError("authored normalization interruption after one target entry")
        self.counts["oracle_calls"] += 1
        n = self.counts["target_calls"]
        status = {"match":"MATCH","mismatch":"MISMATCH","alternating":"MISMATCH",
                  "oracle-error":"EXECUTION_ERROR","not-comparable":"NOT_COMPARABLE"}[self.mode]
        value = n % 2 if self.mode == "alternating" else int(status == "MISMATCH")
        return dict(normalized={"computability":"DEFINED","numeric_value":value},
            raw_outcome={"kind":"AUTHORED","value":value},
            expected={"computable":True,"value":0},
            comparison={"status":status,"violation_category":"AUTHORED_NUMERIC_MISMATCH" if status == "MISMATCH" else None,
                        "confirmed":False},
            timings={"target_call_seconds":0.0,"normalization_seconds":0.0,
                     "oracle_seconds":0.0,"comparison_seconds":0.0})


def execute_authored(plan, tmp_path, monkeypatch, *, mode="match", pair_budget=12, shrink_budget=0,on_shrink=None):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    permit, context = approved(plan,ledger,pair_budget=pair_budget,shrink_budget=shrink_budget)
    claim = ledger.claim_corroboration([permit],[context])
    adapter = AuthoredAdapter(mode)
    monkeypatch.setattr(adapters,"create_reviewed_adapter",lambda *args,**kwargs:adapter)
    if on_shrink is not None:
        monkeypatch.setattr(service,"shrink_numerical_failure",
            lambda predicate,**options:on_shrink(adapter,predicate,options))
    result = service.run_corroboration_plan(plan,permit,expected_approval_context=context,
        usage_ledger=ledger,claim_id=claim["claim_id"])
    return result, ledger, claim, adapter


def test_actual_worker_plans_keep_runtime_boundary_and_information_limits(plans):
    for method, plan in plans.items():
        assert service.validate_candidate_plan(plan) == plan
        assert plan["primary_generation_executions"] == 1
        assert plan["reference_generation_executions"] == 0
        assert plan["metrics"]["target_calls"] == plan["metrics"]["oracle_calls"] == 0
        assert plan["metrics"]["algorithm"] == "Hypothesis-strategy-plan"
        assert plan["boundary"]["full_archive_transmitted"] is False
        assert plan["boundary"]["oracle_modules_transmitted"] is False
        encoded = canonical(plan["request"])
        assert "approved_implementation_identity" not in encoded and "candidate_plan_digest" not in encoded
        # The unchanged guide legitimately cites public SciPy documentation.
        # It must not contain the chosen CORR implementation identity.
        assert "scipy-stats-pearsonr" not in encoded and "statistics.correlation" not in encoded
        assert len(plan["boundary"]["generator_sha256"]) == 5
        if method != "D":
            assert "artifact" not in plan["request"] and "approval_receipt" not in plan["request"]
        if method == "C":
            assert plan["request"]["replay_inputs"] == [REPLAY]


@pytest.mark.parametrize("field,value", [
    ("scope","FINAL_TARGET"),("final_evaluation_authorized",True),
    ("publication_authorized",True),("feedback_to_generator",True),
    ("reviewed_authority","FORCE")])
def test_corr_cannot_be_relabelled_as_final_or_publication_authority(plans,tmp_path,field,value):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    context = context_for(plans["B"],ledger)
    changed = deepcopy(context); changed[field] = value
    with pytest.raises(PermissionError):
        CorroborationExecutionPermit.from_host_approval(changed,deepcopy(changed))


@pytest.mark.parametrize("field", ["frozen_source_guide_digest","approved_implementation_identity",
    "adapter_identity","oracle_identity","common_input_contract","candidate_generation_contract",
    "resource_budget","candidate_plan_digest","review_digest","authority_id"])
def test_external_host_approval_is_required_for_each_binding(plans,tmp_path,field):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    context = context_for(plans["D"],ledger)
    changed = deepcopy(context)
    changed[field] = "0"*64 if isinstance(changed[field],str) else {"modified":True}
    with pytest.raises(PermissionError,match="external trusted host"):
        CorroborationExecutionPermit.from_host_approval(changed,context)


@pytest.mark.parametrize("component", ["adapter_identity","oracle_identity"])
def test_self_approved_component_substitution_still_checks_actual_code(plans,tmp_path,component):
    context = context_for(plans["B"],UsageLedger(tmp_path/"authority.jsonl"))
    context[component] = {"forged":"new-self-hash-is-not-the-installed-component"}
    with pytest.raises(PermissionError,match="adapter or independent Oracle"):
        CorroborationExecutionPermit.from_host_approval(context,deepcopy(context))


def test_permit_is_immutable_and_plan_rehash_does_not_reapprove(plans,tmp_path):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    permit, context = approved(plans["B"],ledger)
    copy = permit.context; copy["publication_authorized"] = True
    assert permit.context["publication_authorized"] is False
    changed = deepcopy(plans["B"])
    changed["metrics"]["generation_wall_seconds"] += 1.0
    changed["plan_digest"] = service._plan_digest(changed)
    with pytest.raises(PermissionError,match="candidate plan differs"):
        permit.validate(context,plan=changed)


def test_wrong_generation_contract_and_unreviewed_implementation_fail_closed(plans,tmp_path):
    context = context_for(plans["B"],UsageLedger(tmp_path/"authority.jsonl"))
    for field, value in (("candidate_generation_contract",public_input_contract()),
                         ("common_input_contract",public_input_contract(lengths=[4,5,6]))):
        changed = deepcopy(context); changed[field] = value
        with pytest.raises(ValueError,match="unchanged full Source domain"):
            CorroborationExecutionPermit.from_host_approval(changed,deepcopy(changed))
    changed = deepcopy(context)
    changed["approved_implementation_identity"]["implementation_id"] = "arbitrary.module.function"
    with pytest.raises(PermissionError,match="allowlist"):
        CorroborationExecutionPermit.from_host_approval(changed,deepcopy(changed))


def test_source_only_guide_scope_cannot_be_rehashed_into_transfer_permission(plans):
    original = deepcopy(plans["D"])
    assert original["request"]["artifact"]["applicability_scope"] == "SOURCE_DEVELOPMENT_ONLY"
    assert original["request"]["approval_receipt"]["transfer_authorized"] is False
    changed = deepcopy(original)
    changed["request"]["artifact"]["applicability_scope"] = "INDEPENDENT_DEVELOPMENT_ONLY"
    changed["plan_digest"] = service._plan_digest(changed)
    with pytest.raises(ValueError):
        service.validate_candidate_plan(changed)
    assert plans["D"] == original


def test_open_corr_reservation_is_required_before_an_adapter_is_created(plans,tmp_path,monkeypatch):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    permit, context = approved(plans["B"],ledger)
    monkeypatch.setattr(adapters,"create_reviewed_adapter",lambda *args,**kwargs:(_ for _ in ()).throw(
        AssertionError("unapproved execution reached adapter")))
    with pytest.raises(PermissionError,match="consumed development START"):
        service.run_corroboration_plan(plans["B"],permit,expected_approval_context=context,
            usage_ledger=ledger,claim_id="f"*64)
    with pytest.raises(PermissionError,match="permit object"):
        service.run_corroboration_plan(plans["B"],context,expected_approval_context=context,
            usage_ledger=ledger,claim_id="f"*64)


def test_corr_start_remains_consumed_after_completion_and_rejects_final_receipt(plans,tmp_path):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    permit, context = approved(plans["B"],ledger)
    with pytest.raises(PermissionError,match="does not accept final readiness"):
        ledger.claim_corroboration([{"status":"PASS"}],[context])
    row = ledger.claim_corroboration([permit],[context])
    state = ledger.inspect()
    identity = context["approved_implementation_identity"]["usage_identity"]
    assert identity_tokens(identity) <= set(state["consumed_tokens"])
    assert row["payload"]["scope"] == "INDEPENDENT_DEVELOPMENT_ONLY"
    assert row["payload"]["final_evaluation_authorized"] is False
    # Exercise the existing final claim refusal; this is not a final execution.
    final_fixture_receipt = {"status":"PASS","bindings":{"authority_id":ledger.authority_id}}
    with pytest.raises(PermissionError,match="already consumed"):
        ledger.claim([{"identity":identity}],final_fixture_receipt)
    ledger.complete(row["claim_id"],{"status":"COMPLETE"})
    with pytest.raises(PermissionError,match="already consumed"):
        ledger.claim_corroboration([permit],[context])
    with pytest.raises(PermissionError,match="already consumed"):
        ledger.claim([{"identity":identity}],final_fixture_receipt)


def test_existing_readiness_rejects_the_actual_corr_consumption_tokens(plans,tmp_path):
    from test_e8_readiness import setup_data
    from tomolab.discovery.evaluation_readiness import EvaluationReadiness
    data = setup_data(tmp_path)
    ledger = data["usage_ledger"]
    reviewed = adapters.implementation_identity("python-statistics-correlation")
    # This is authored readiness metadata, never a claim about actual target
    # behavior. Bind its hypothetical final target to the CORR identity.
    target = data["targets"][0]
    target["identity"] = deepcopy(reviewed["usage_identity"])
    target["provenance"]["implementation_sha256"] = target["identity"]["implementation_sha256"]
    for field in ("oracle_validation","controls"):
        target[field]["target_identity_sha256"] = digest(target["identity"])
    before = EvaluationReadiness(**data).validate_target_contracts()
    assert before["status"] == "PASS", before
    permit, context = approved(plans["B"],ledger,identity=reviewed)
    ledger.claim_corroboration([permit],[context])
    after = EvaluationReadiness(**data).validate_target_contracts()
    assert after["status"] == "READINESS_BLOCKED_NO_APPLICABLE_TARGET"
    assert "overlaps Source/Corroboration/consumed final identity" in " ".join(after["reasons"])


def test_authored_negative_observations_have_no_invented_first_failure(plans,tmp_path,monkeypatch):
    result, ledger, claim, adapter = execute_authored(plans["B"],tmp_path,monkeypatch)
    assert result["status"] == "COMPLETE"
    assert result["outcome"] == "NO_CONFIRMED_FAILURE_WITHIN_BUDGET"
    assert result["first_mismatch_observation"] is result["first_confirmed_failure"] is None
    assert result["target_calls"] == result["oracle_calls"] == result["actual_target_function_entries"] == len(result["rows"])
    assert result["confirmed_contract_violation_inputs"] == 0
    assert result["generator_feedback_calls"] == 0
    assert not result["allow_release"] and not result["source_archive_modified"]
    assert result["cost"]["logical_prepared_before_receipt_seconds"] >= plans["B"]["metrics"]["generation_wall_seconds"]
    assert result["receipt_sha256"] == digest({k:v for k,v in result.items() if k != "receipt_sha256"})


def test_authored_mismatches_need_two_separate_identical_replays(plans,tmp_path,monkeypatch):
    result, _, _, _ = execute_authored(plans["B"],tmp_path,monkeypatch,mode="mismatch")
    assert result["status"] == "COMPLETE"
    assert result["outcome"] == "CONFIRMED_CONTRACT_VIOLATION_WITHIN_BUDGET"
    assert result["first_mismatch_observation"]["target_calls"] == 1
    assert result["first_confirmed_failure"]["target_calls"] == 3
    assert result["confirmed_fresh_violation_inputs"] == len(plans["B"]["generation"]["candidates"])
    assert result["target_calls"] == 3*result["confirmed_fresh_violation_inputs"]


def test_nonidentical_replays_cannot_be_confirmed(plans,tmp_path,monkeypatch):
    result, _, _, _ = execute_authored(plans["B"],tmp_path,monkeypatch,mode="alternating")
    assert result["status"] == "INCONCLUSIVE_REPLAY_MISMATCH"
    assert result["outcome"] == "INCONCLUSIVE"
    assert result["confirmed_contract_violation_inputs"] == 0
    assert result["first_confirmed_failure"] is None


@pytest.mark.parametrize("mode,expected_counts", [("oracle-error",(1,1)),("partial-error",(1,0))])
def test_partial_errors_preserve_actual_attempts_without_normal_negative_evidence(plans,tmp_path,monkeypatch,mode,expected_counts):
    result, _, _, _ = execute_authored(plans["B"],tmp_path,monkeypatch,mode=mode)
    assert result["status"] == "ABORTED_EXECUTION_ERROR"
    assert result["outcome"] == "INCONCLUSIVE"
    assert (result["target_calls"],result["oracle_calls"]) == expected_counts
    assert result["actual_target_function_entries"] == 1
    assert result["confirmed_contract_violation_inputs"] == 0


def test_not_comparable_is_reported_as_partial_not_clean_failure_free(plans,tmp_path,monkeypatch):
    result, _, _, _ = execute_authored(plans["B"],tmp_path,monkeypatch,mode="not-comparable")
    assert result["status"] == "COMPLETE"
    assert result["outcome"] == "PARTIAL_NOT_COMPARABLE"
    assert result["not_comparable"] == len(result["rows"])
    assert result["first_confirmed_failure"] is None


def test_method_c_replay_is_separate_from_fresh_generation_contract(plans,tmp_path,monkeypatch):
    result, _, _, _ = execute_authored(plans["C"],tmp_path,monkeypatch)
    known = [row for row in result["rows"] if row["phase"] == "known_source_replay"]
    assert len(known) == 3 and all(row["source_replay"] for row in known)
    assert all(len(row["inputs"]["a"]) == 3 for row in known)
    assert result["common_input_contract"]["lengths"] == [3,4,5,6]
    assert result["candidate_generation_contract"]["lengths"] == [4,5,6]
    assert all(len(row["inputs"]["a"]) in (4,5,6) for row in result["rows"] if row["phase"] == "fresh_generation")
    assert result["target_calls"] <= result["resource_budget"]["pair_budget"]


def test_approval_remains_stable_after_repeated_metadata_execution(plans,tmp_path):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    first_adapter = adapters.adapter_identity()
    first_oracle = adapters.oracle_identity()
    for _ in range(12):
        permit, context = approved(plans["B"],ledger)
        assert permit.validate(context).context == context
        assert adapters.adapter_identity() == first_adapter
        assert adapters.oracle_identity() == first_oracle


@pytest.mark.parametrize("field", ["canonical_function_identity","cross_revision_function_key",
    "normalized_ast_clone_sha256","implementation_sha256"])
def test_corr_consumption_blocks_final_aliases_by_each_original_lineage_token(plans,tmp_path,field):
    ledger = UsageLedger(tmp_path/"authority.jsonl")
    permit, context = approved(plans["B"],ledger)
    ledger.claim_corroboration([permit],[context])
    original = context["approved_implementation_identity"]["usage_identity"]
    alias = {name:digest(["different",name]) for name in original}
    alias[field] = original[field]
    final_fixture_receipt = {"status":"PASS","bindings":{"authority_id":ledger.authority_id}}
    with pytest.raises(PermissionError,match="already consumed"):
        ledger.claim([{"identity":alias,"target_id":"new-name","oracle":"changed","seed":999}],
                     final_fixture_receipt,output=tmp_path/"different-output")


def test_changed_source_guide_cannot_be_used_by_a_preapproved_d_plan(plans,tmp_path):
    context = context_for(plans["D"],UsageLedger(tmp_path/"authority.jsonl"))
    context["frozen_source_guide_digest"] = "0"*64
    permit = CorroborationExecutionPermit.from_host_approval(context,deepcopy(context))
    with pytest.raises(PermissionError,match="Source guide differs"):
        permit.validate(context,plan=plans["D"])


@pytest.mark.parametrize("replays_match", [True,False])
def test_shrink_witness_requires_identical_replay_semantics(plans,tmp_path,monkeypatch,replays_match):
    def shrink(adapter,predicate,options):
        witness = deepcopy(options["initial_witness"])
        assert predicate(witness) is True
        if not replays_match:
            adapter.mode = "alternating"
        return {"witness":witness,"scope":"AUTHORED_NATIVE_SHRINK_CALLBACK_CHECK"}
    result, _, _, _ = execute_authored(plans["B"],tmp_path,monkeypatch,
        mode="mismatch",pair_budget=24,shrink_budget=4,on_shrink=shrink)
    assert result["target_calls"] == result["oracle_calls"] <= 24
    assert result["shrinking"]["reproduced_twice"] is replays_match
    if replays_match:
        assert result["status"] == "COMPLETE"
    else:
        assert result["status"] == "INCONCLUSIVE_REPLAY_MISMATCH"
        assert result["outcome"] == "INCONCLUSIVE"
        assert result["replay_mismatches"] >= 1


def test_no_source_archive_replay_or_learning_is_used_during_corr_evaluation(plans,tmp_path,monkeypatch):
    from tomolab.discovery import compact_guidance, knowledge
    def forbidden(*args,**kwargs):
        raise AssertionError("CORR execution tried to modify or relearn Source knowledge")
    monkeypatch.setattr(knowledge.KnowledgeArchive,"from_snapshot",forbidden)
    monkeypatch.setattr(compact_guidance,"prepare_recipe_from_archive",forbidden)
    monkeypatch.setattr(compact_guidance,"compile_execution_artifact",forbidden)
    before = canonical(plans["D"])
    result, _, _, _ = execute_authored(plans["D"],tmp_path,monkeypatch)
    assert result["status"] == "COMPLETE"
    assert result["generator_feedback_calls"] == 0
    assert not result["source_archive_modified"]
    assert canonical(plans["D"]) == before
