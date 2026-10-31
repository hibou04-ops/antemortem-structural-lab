"""Scope semantics on authored data/mocked OCI receipts; external execution0."""
from copy import deepcopy
import hashlib

import pytest

from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.harvester_github import candidate_identity, validate_candidate
from tomolab.discovery.harvester_review import make_review, source_function_identity
from tomolab.discovery.recursive_api import update_generation
from tomolab.discovery.online_engine import OnlinePolicy
from tomolab.discovery.online_learning import learn_mold
from tomolab.discovery.online_observe import inspect_target
from tomolab.discovery.recursive_observe import make_diagnostics, new_trace, observe_proposal, execute_pairs
from tomolab.discovery.recursive_policy import initial_selector, make_development_manifest
from tomolab.discovery.recursive_store import GenerationStore, make_generation
from tomolab.discovery.schema import digest
from tomolab.discovery.transfer_audit import audit_transfer_scope
from test_harvester_execution import mock_launcher, reproduction_fixture
from test_harvester_review import candidate_fixture, review_fixture, blob, resign, BUGGY, FIXED, ORACLE, RESET, CONTRACT
from test_recursive_policy import paired_fixture


def g0(tmp_path, *, contract=CONTRACT, mold=None):
    path = tmp_path / "generations.jsonl"
    selector = initial_selector(mold or digest("authored-scope-only-mold"), input_contract_digest=digest(contract))
    GenerationStore(path).append(make_generation("G0", selector))
    return path


@pytest.fixture
def qualification(tmp_path, monkeypatch):
    # Existing real validators inspect exact source hashes and authored/mock
    # runtime receipts. They do not establish a real daemon in this fixture.
    return dict(candidate=candidate_fixture(), review=review_fixture(),
                execution_receipt=reproduction_fixture(tmp_path, monkeypatch))


def case(case_id, proof, inputs):
    return dict(case_id=case_id, identity=deepcopy(proof["review"]["function_identity"]),
                contract=deepcopy(proof["review"]["contract"]), inputs=deepcopy(inputs))


def audit(scope, source, evaluation, proof, store=None, **kwargs):
    evidence = {row["case_id"]: proof for row in source + evaluation}
    return audit_transfer_scope(claim_scope=scope, source_cases=source, evaluation_cases=evaluation,
        qualification_evidence=evidence, trusted_review=True, generation_store=store,
        generation_id="G0" if store else None, **kwargs)


def test_same_function_fresh_typed_input_is_permitted_but_is_not_cross_implementation(qualification, tmp_path):
    source = [case("source", qualification, [[1, 1]])]
    evaluation = [case("eval", qualification, [[2, 2]])]
    store = g0(tmp_path)
    within = audit("WITHIN_FUNCTION_UNSEEN_INPUT", source, evaluation, qualification, store)
    assert within["status"] == "PASS" and within["claim_supported"] is True
    assert within["exposure"]["overlaps"]["function_identity_tokens"] == 4
    cross = audit("CROSS_IMPLEMENTATION_TRANSFER", source, evaluation, qualification, store)
    assert cross["status"] == "BLOCK"
    assert "DEVELOPMENT_POOL_FUNCTION_IDENTITY_EXPOSURE" in cross["reasons"]
    assert within["generalization_demonstrated"] is False and within["promotion_authorized"] is False
    assert within["transfer_utility"] == "NOT_ESTABLISHED" and within["provider_calls"] == 0


def test_pool_presence_blocks_unseen_without_claiming_actual_observation(qualification, tmp_path):
    result = audit("WITHIN_FUNCTION_UNSEEN_INPUT", [case("s", qualification, [[2, 2]])],
        [case("e", qualification, [[2, 2]])], qualification, g0(tmp_path))
    assert result["status"] == "BLOCK"
    assert "POOL_INPUT_ALREADY_EXPOSED" in result["reasons"]
    assert "SELECTED_INPUT_ALREADY_OBSERVED" not in result["reasons"]
    assert result["exposure"]["selected_observed_points"] == 0
    assert result["exposure"]["learning_consumed_receipts"] == 0


def test_actual_qualification_witness_is_not_an_unseen_evaluation_input(qualification, tmp_path):
    result = audit("WITHIN_FUNCTION_UNSEEN_INPUT", [case("s", qualification, [[0]])],
        [case("e", qualification, [[1, 1]])], qualification, g0(tmp_path))
    assert result["status"] == "BLOCK"
    assert "QUALIFICATION_WITNESS_ALREADY_OBSERVED" in result["reasons"]
    assert result["exposure"]["qualification_observed_points"] == 1


def test_paired_identical_remeasurement_passes_without_authorizing_utility_or_oci(qualification):
    result = audit("PAIRED_REMEASUREMENT", [case("s", qualification, [[1, 1]])],
        [case("e", qualification, [[1, 1]])], qualification)
    assert result["status"] == "PASS"
    assert result["qualified_cases"] == 2 and result["qualified_function_identities"] == 1
    assert result["generation_history_status"] == "UNKNOWN"
    assert result["paired_oci_linkage"] == "NOT_ESTABLISHED_BY_THIS_SCOPE_AUDIT"
    assert result["execution_authorized"] is False and result["generalization_demonstrated"] is False


def test_paired_cannot_relabel_different_inputs_as_identical_remeasurement(qualification):
    result = audit("PAIRED_REMEASUREMENT", [case("s", qualification, [[1, 1]])],
        [case("e", qualification, [[2, 2]])], qualification)
    assert result["status"] == "BLOCK"
    assert "PAIRED_REMEASUREMENT_REQUIRES_IDENTICAL_FUNCTION_CONTRACT_AND_INPUTS" in result["reasons"]


@pytest.mark.parametrize("authority", [False, 1, "true"])
def test_caller_truthy_or_missing_proof_does_not_establish_oracle_or_execution(qualification, authority):
    row = case("s", qualification, [[1, 1]])
    result = audit_transfer_scope(claim_scope="PAIRED_REMEASUREMENT", source_cases=[row], evaluation_cases=[row],
        qualification_evidence={"s": qualification}, trusted_review=authority)
    assert result["status"] == "HOLD" and result["claim_supported"] is False
    assert "ACCOUNTABLE_HOST_REVIEW_REQUIRED" in result["reasons"]


def test_self_declared_pass_and_postfix_oracle_are_held(qualification):
    row = case("s", qualification, [[1, 1]])
    for proof in ({"status": "PASS"}, deepcopy(qualification)):
        if "review" in proof:
            proof["review"]["oracle_sha256"] = proof["review"]["fixed_implementation_sha256"]
            resign(proof["review"], "review_digest")
        result = audit_transfer_scope(claim_scope="PAIRED_REMEASUREMENT", source_cases=[row], evaluation_cases=[row],
            qualification_evidence={"s": proof}, trusted_review=True)
        assert result["status"] == "HOLD" and result["claim_supported"] is False


def test_complete_source_proof_rejects_renamed_caller_identity(qualification):
    source = case("s", qualification, [[1, 1]])
    evaluation = case("e", qualification, [[1, 1]])
    evaluation["identity"]["canonical_function_identity"] = "f" * 64
    result = audit("PAIRED_REMEASUREMENT", [source], [evaluation], qualification)
    assert result["status"] == "BLOCK"
    assert "e:DECLARED_CASE_DIFFERS_FROM_REVIEWED_SOURCE_OR_CONTRACT" in result["reasons"]


def test_newness_requires_a_frozen_generation_even_if_the_current_store_is_valid(qualification, tmp_path):
    store = g0(tmp_path)
    source, evaluation = case("s", qualification, [[1, 1]]), case("e", qualification, [[2, 2]])
    result = audit_transfer_scope(claim_scope="WITHIN_FUNCTION_UNSEEN_INPUT", source_cases=[source], evaluation_cases=[evaluation],
        qualification_evidence={"s": qualification, "e": qualification}, trusted_review=True, generation_store=store)
    assert result["status"] == "HOLD" and "FROZEN_GENERATION_HISTORY_UNKNOWN" in result["reasons"]


def raw_cases(receipt):
    identity = dict(canonical_function_identity=digest("authored-raw-function"), cross_revision_function_key=digest("authored-raw-cross-revision"),
        normalized_ast_clone_sha256=digest("authored-raw-ast"), implementation_sha256=receipt["identity"]["implementation_sha256"])
    contract = receipt["reservation"]["state"]["contract"]
    source = dict(case_id="s", identity=identity, contract=contract, inputs=[[9]])
    evaluation = dict(case_id="e", identity=deepcopy(identity), contract=deepcopy(contract),
                      inputs=[deepcopy(receipt["reservation"]["common_input"])])
    return source, evaluation


def test_selected_observation_is_not_automatically_learning_consumption(tmp_path):
    receipt, _ = paired_fixture()
    source, evaluation = raw_cases(receipt)
    store = g0(tmp_path, contract=source["contract"], mold=receipt["mold_digest"])
    result = audit_transfer_scope(claim_scope="WITHIN_FUNCTION_UNSEEN_INPUT", source_cases=[source], evaluation_cases=[evaluation],
        paired_receipts=[receipt], generation_store=store, generation_id="G0")
    assert result["status"] == "BLOCK"
    assert "SELECTED_INPUT_ALREADY_OBSERVED" in result["reasons"]
    assert result["exposure"]["selected_receipts"] == 1 and result["exposure"]["selected_observed_points"] > 0
    assert result["exposure"]["learning_consumed_receipts"] == 0


def test_exact_frozen_generation_prefix_derives_consumption_without_using_later_generation(tmp_path):
    receipt, lineage = paired_fixture()
    source, evaluation = raw_cases(receipt)
    store = g0(tmp_path, contract=source["contract"], mold=receipt["mold_digest"])
    manifest = make_development_manifest([lineage], receipt["experiment_contract_sha256"])
    update_generation(store, [receipt], manifest, generation_id="G1")
    args = dict(claim_scope="WITHIN_FUNCTION_UNSEEN_INPUT", source_cases=[source], evaluation_cases=[evaluation], generation_store=store)
    old = audit_transfer_scope(**args, generation_id="G0")
    new = audit_transfer_scope(**args, generation_id="G1")
    assert old["exposure"]["learning_consumed_receipts"] == 0
    assert "INPUT_ALREADY_CONSUMED_BY_LEARNING" not in old["reasons"]
    assert new["exposure"]["learning_consumed_receipts"] == 1
    assert "INPUT_ALREADY_CONSUMED_BY_LEARNING" in new["reasons"]
    assert new["frozen_generation"]["generation_id"] == "G1"


def test_duplicate_or_tampered_receipt_cannot_inflate_observation_evidence(tmp_path):
    receipt, _ = paired_fixture()
    source, evaluation = raw_cases(receipt)
    for rows, reason in (([receipt, receipt], "SELECTED:DUPLICATE_PAIRED_EXECUTION"),
                         ([dict(receipt, label="UNKNOWN")], "SELECTED:INVALID_PAIRED_RECEIPT")):
        result = audit_transfer_scope(claim_scope="PAIRED_REMEASUREMENT", source_cases=[source], evaluation_cases=[evaluation], paired_receipts=rows)
        assert result["status"] == "BLOCK" and reason in result["reasons"]
        assert result["exposure"]["selected_receipts"] <= 1


@pytest.mark.parametrize("kind,left,right", [("float", -0.0, 0.0), ("mapping", {"a": 1, "b": 2}, {"b": 2, "a": 1})])
def test_existing_input_identity_preserves_signed_zero_and_mapping_order(kind, left, right):
    identity = {name: digest(name) for name in ("canonical_function_identity", "cross_revision_function_key", "normalized_ast_clone_sha256", "implementation_sha256")}
    contract = dict(kind=kind, low=-4, high=4, max_size=4)
    row = dict(case_id="s", identity=identity, contract=contract, inputs=[left])
    evaluation = dict(row, case_id="e", inputs=[right])
    result = audit_transfer_scope(claim_scope="WITHIN_FUNCTION_UNSEEN_INPUT", source_cases=[row], evaluation_cases=[evaluation])
    assert result["status"] == "HOLD"
    assert "POOL_INPUT_ALREADY_EXPOSED" not in result["reasons"]


def test_data_caps_and_invalid_integer_booleans_are_rejected(qualification):
    row = case("s", qualification, [[1, 1]])
    for source in ([dict(row, case_id="s"+str(i)) for i in range(65)], [dict(row, inputs=[[1]]*129)], [dict(row, inputs=[[True]])]):
        with pytest.raises(ValueError):
            audit_transfer_scope(claim_scope="PAIRED_REMEASUREMENT", source_cases=source, evaluation_cases=[row])


@pytest.mark.parametrize("same_unit", [False, True])
def test_different_functions_share_project_but_need_reviewed_lineage_independence(qualification, tmp_path, monkeypatch, same_unit):
    c = candidate_fixture()
    c.update(number=8, candidate_id=candidate_identity(c["repository"], 8), source_url="https://github.com/authored/project/pull/8")
    buggy = BUGGY.replace("implementation", "different").replace("+ int(", "+ 2 * int(")
    fixed = FIXED.replace("implementation", "different")
    c["source_blobs"] = [blob(buggy, "second.py", c["buggy_revision"]), blob(fixed, "second.py", c["fixed_revision"])]
    c = validate_candidate(resign(c, "metadata_digest"))
    old = qualification["review"]
    r = make_review(c, contract=CONTRACT, implementation_sha256=hashlib.sha256(buggy.encode()).hexdigest(),
        fixed_implementation_sha256=hashlib.sha256(fixed.encode()).hexdigest(), oracle_sha256=hashlib.sha256(ORACLE.encode()).hexdigest(),
        reset_adapter_sha256=hashlib.sha256(RESET.encode()).hexdigest(), function_identity=source_function_identity(c,path="second.py",function="different"),
        lineage=dict(old["lineage"], source_lineage_id="other-authored-lineage",
                     independence_id=old["lineage"]["independence_id"] if same_unit else "other-authored-unit"),
        review_ids=old["review_ids"], oracle_independence_basis=old["oracle_independence_basis"],
        exports=dict(buggy="different",fixed="different",oracle="reference",reset="reset"))
    bundle = execution.make_source_bundle(buggy,fixed,ORACLE,RESET,buggy_function="different",fixed_function="different")
    mock_launcher(monkeypatch)
    branches = []
    for variant in ("buggy", "fixed"):
        repeats=[]
        for n in range(3):
            calls={role:execution.execute_reviewed_case(c,r,bundle,variant=variant if role=="target" else "oracle",input=[1,1],image="reviewed-image",
                output_directory=tmp_path/(variant+str(n)+role),allow_external_execution=True,trusted_review=True) for role in ("target","oracle")}
            repeats.append(calls)
        branches.append(repeats)
    alternate = dict(candidate=c,review=r,execution_receipt=execution.make_reproduction_receipt(c,r,*branches))
    source, evaluation = case("s", qualification, [[1,1]]), case("e", alternate, [[2,2]])
    result = audit_transfer_scope(claim_scope="CROSS_IMPLEMENTATION_TRANSFER",source_cases=[source],evaluation_cases=[evaluation],
        qualification_evidence={"s":qualification,"e":alternate},trusted_review=True,generation_store=g0(tmp_path),generation_id="G0")
    assert result["status"] == ("BLOCK" if same_unit else "PASS")
    assert result["exposure"]["overlaps"]["function_identity_tokens"] == 0
    assert ("CROSS_IMPLEMENTATION_LINEAGE_NOT_INDEPENDENT" in result["reasons"]) is same_unit
    assert result["host_external_code_executed"] is False and result["provider_calls"] == 0


def test_audit_receipt_binds_actual_case_points_not_only_aggregate_counts(qualification, tmp_path):
    store = g0(tmp_path)
    source = [case("s", qualification, [[1,1]])]
    first = audit("WITHIN_FUNCTION_UNSEEN_INPUT", source, [case("e", qualification, [[2,2]])], qualification, store)
    second = audit("WITHIN_FUNCTION_UNSEEN_INPUT", source, [case("e", qualification, [[3,3]])], qualification, store)
    assert first["status"] == second["status"] == "PASS"
    assert first["exposure"] == second["exposure"]
    assert first["bindings"]["evaluation_cases_sha256"] != second["bindings"]["evaluation_cases_sha256"]
    assert first["audit_sha256"] != second["audit_sha256"]


def reviewed_authored_pair(proof):
    """First-party authored callbacks only, not execution of source strings."""
    review = proof["review"]
    mold = learn_mold([dict(input=[1,2],status="PASS",contract=CONTRACT,source_identity="authored"),
        dict(input=[1,1],status="FAILURE",contract=CONTRACT,source_identity="authored")], operator_grammar=["constantize"])
    identity = dict(implementation_sha256=review["implementation_sha256"],oracle_sha256=review["oracle_sha256"],
        reset_adapter_sha256=review["reset_adapter_sha256"],environment_sha256=digest("authored-test-environment"),
        purity_review_id=review["review_ids"]["reset_review_id"])
    public = make_diagnostics(mold,experiment_contract_sha256=digest("authored-audit-pair"),run_id="authored-pair",
        identity=identity,**{k:review["lineage"][k] for k in ("source_lineage_id","project_id","mechanism_id")})["public"]
    structure=inspect_target(sum,CONTRACT,mode="black_box")
    policy=OnlinePolicy(CONTRACT,method="C",seed=7,budget=100,structure=structure)
    policy.attempts=2
    policy.last_feedback=dict(status="FAILURE",input_digest=digest([1,2]),coverage=[],branch_distance=None,contract_checked=digest(CONTRACT))
    before=deepcopy(policy);actual=policy.propose([1,2]);trace=new_trace(public)
    observe_proposal(before,[1,2],actual,config=public,trace=trace,seed=7,actual_calls_before=0,shadow_rule_state=None)
    def authored_target(point):
        return sum(point)+int(len(point)>1 and len(set(point))==1)
    result=execute_pairs(trace,config=public,identity=identity,target=authored_target,oracle=sum,
        contract=CONTRACT,structure=structure,tracing=False,reset=lambda:True)
    return result["receipts"][0]


def test_actual_paired_review_binding_allows_same_function_alias_but_blocks_swapped_reset(qualification):
    receipt=reviewed_authored_pair(qualification)
    alternate=deepcopy(qualification)
    alternate["review"]["lineage"]["source_lineage_id"]="same-function-alias"
    resign(alternate["review"],"review_digest")
    reproduction=alternate["execution_receipt"]
    reproduction["review_digest"]=alternate["review"]["review_digest"]
    for branch in ("buggy","fixed"):
        for repeat in reproduction[branch]:
            for record in repeat.values():
                record["review_digest"]=alternate["review"]["review_digest"]
                resign(record,"sha256")
    resign(reproduction,"sha256")
    point=receipt["reservation"]["common_input"]
    source,evaluation=case("s",qualification,[point]),case("e",alternate,[point])
    args=dict(claim_scope="PAIRED_REMEASUREMENT",source_cases=[source],evaluation_cases=[evaluation],
              qualification_evidence={"s":qualification,"e":alternate},trusted_review=True)
    clean=audit_transfer_scope(**args,paired_receipts=[receipt])
    assert clean["status"]=="PASS" and clean["qualified_function_identities"]==1
    modified=deepcopy(receipt);modified["identity"]["reset_adapter_sha256"]="f"*64
    resign(modified,"pair_receipt_sha256")
    bad=audit_transfer_scope(**args,paired_receipts=[modified])
    assert bad["status"]=="BLOCK" and "SELECTED:PAIRED_REVIEW_IDENTITY_MISMATCH" in bad["reasons"]
