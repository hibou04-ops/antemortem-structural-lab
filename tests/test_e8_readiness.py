"""Authored functional fixtures only; these tests establish no research result."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from test_e8_evidence import record, ledger
from tomolab.discovery.evaluation_readiness import (EvaluationReadiness, runtime_versions,
    planning_product_hashes, plans_fingerprint)
from tomolab.discovery.evaluation_usage import UsageLedger, identity_tokens
from tomolab.discovery.schema import digest


ROOT = Path(__file__).resolve().parents[1]


def identity(n):
    return {"canonical_function_identity":digest([n,"canonical"]),
            "cross_revision_function_key":digest([n,"cross"]),
            "normalized_ast_clone_sha256":digest([n,"clone"]),
            "implementation_sha256":str(n)*64}


def different_implementation(value, number):
    value = deepcopy(value); origin = value["provenance"]["origin"]
    origin.update(project="fixture-"+str(number), lineage="lineage-"+str(number), revision="revision-"+str(number),
                  oracle_id="oracle-"+str(number), semantics="authored-reciprocal",
                  implementation_sha256=str(number)*64, oracle_sha256=str(number+4)*64,
                  independence_id="review-"+str(number))
    value.update(project=origin["project"], revision=origin["revision"], implementation_hash=origin["implementation_sha256"],
                 oracle_identity=origin["oracle_id"], oracle_hash=origin["oracle_sha256"])
    value["oracle_validation_receipt"]["oracle_hash"] = value["oracle_hash"]
    for field in ("oracle_validation_receipt", "domain_validity", "replay_status", "execution_receipt"):
        value[field]["bindings"].update(implementation_hash=value["implementation_hash"],
            oracle_identity=value["oracle_identity"], oracle_hash=value["oracle_hash"])
    return value


def setup_data(tmp_path, *, seed=11):
    evidence = ledger()
    sources = [record("source-positive", 0, True), record("source-negative", 1, False)]
    corroboration = [different_implementation(record("C-positive", 0, True), 2),
                     different_implementation(record("C-negative", 1, False), 2)]
    for row in sources+corroboration:
        evidence.ingest(row, trusted_host=True)
    knowledge = evidence.build_knowledge_archive([r["record_id"] for r in sources])
    for row in corroboration:
        knowledge.observe(evidence.observation(row["record_id"]), trusted_observation=True)
    knowledge.freeze()
    reviews = []
    for row in sources+corroboration:
        origin = row["provenance"]["origin"]
        reviews.append(dict(record_id=row["record_id"], identity=identity(1 if row in sources else 2),
            lineage=origin["lineage"], independence_id=origin["independence_id"], review_receipt_sha256="a"*64))
    targets = []
    for number, role in [(3,"POSITIVE_REPRODUCTION"), (4,"CLEAN_CONTROL")]:
        origin = different_implementation(record(), number)["provenance"]["origin"]
        target_identity = identity(number); spec = sources[0]["spec"]
        bindings = dict(target_identity_sha256=digest(target_identity), public_spec_hash=digest(spec), oracle_sha256=origin["oracle_sha256"])
        targets.append(dict(target_id="target-"+str(number), spec=deepcopy(spec), provenance=origin,
            identity=target_identity, scope="AUTHORED_FUNCTIONAL_FIXTURE", evaluation_role=role, control_group=None,
            oracle_validation=dict(status="VALIDATED", **bindings, receipt_sha256="a"*64),
            controls=dict(status="VALIDATED", scope="AUTHORED_FUNCTIONAL_FIXTURE", **bindings,
                known_positive_receipt_sha256="b"*64, clean_control_receipt_sha256="c"*64),
            public_guard=dict(kind="DECLARED_SPEC", predicates=[])))
    usage = UsageLedger(tmp_path/"fixed-authority.jsonl")
    protocol = dict(schema="tomolab-e8-fixed-protocol-v1", methods=["A","B","C","D"], seeds=[seed],
        budget=4, pool_size=32, guidance_budget=2,
        product_hashes=planning_product_hashes(),
        versions=runtime_versions(), metrics=["first-failure-calls","false-alerts","wall-seconds"],
        splits=dict(source="DEVELOPMENT", corroboration="DEVELOPMENT", target="FINAL"),
        nonadaptive=True, final_feedback_allowed=False, authority_id=usage.authority_id, protocol_revision="authored-1",
        comparison_policy=dict(kind="FINITE_JSON", absolute_tolerance=1e-10, relative_tolerance=1e-8,
                               undefined="EXECUTION_ERROR", exceptions="EXECUTION_ERROR"))
    return dict(evidence_bundle=evidence.snapshot(), knowledge_snapshot=knowledge.snapshot(),
        lineage_review=dict(status="REVIEWED", development=reviews, consumed_targets=[], review_receipt_sha256="f"*64),
        targets=targets, fixed_protocol=protocol, usage_ledger=usage, authority=usage.authority_id)


def test_empty_and_malformed_inputs_fail_closed_without_measurement():
    for values in ({}, {"evidence_bundle":{"status":"PASS"}}, {"targets":[lambda: 1]}):
        result = EvaluationReadiness(**values).authorize_final_comparison()
        assert result["status"] == "NOT_EXECUTED_READINESS_BLOCKED"
        assert "READINESS_BLOCKED_NO_VALID_FAILURE" in result["blockers"]
        assert result["bindings"]["target_calls"] == result["bindings"]["oracle_calls"] == 0


def test_actual_evidence_and_independent_same_origin_contrast_are_required(tmp_path):
    data = setup_data(tmp_path)
    readiness = EvaluationReadiness(**data)
    assert readiness.validate_evidence()["status"] == "PASS"
    assert readiness.validate_corroboration()["status"] == "PASS"
    data["lineage_review"]["development"][2]["identity"]["normalized_ast_clone_sha256"] = identity(1)["normalized_ast_clone_sha256"]
    data["lineage_review"]["development"][3]["identity"]["normalized_ast_clone_sha256"] = identity(1)["normalized_ast_clone_sha256"]
    assert EvaluationReadiness(**data).validate_corroboration()["status"] == "READINESS_BLOCKED_NO_INDEPENDENT_CORROBORATION"


def test_knowledge_cannot_include_unbacked_observation_even_after_rehash(tmp_path):
    data = setup_data(tmp_path); snapshot = data["evidence_bundle"]
    trimmed = ledger()
    for row in snapshot["journal"][:2]:
        trimmed.ingest(row["record"], trusted_host=True)
    data["evidence_bundle"] = trimmed.snapshot()
    assert EvaluationReadiness(**data).validate_evidence()["status"] == "READINESS_BLOCKED_NO_VALID_FAILURE"


def test_omitted_known_counterevidence_blocks_subset_and_provenance_laundering(tmp_path):
    data = setup_data(tmp_path)
    evidence = type(ledger()).from_snapshot(data["evidence_bundle"])
    # This extra accepted point is absent from the otherwise supported snapshot.
    disproof = different_implementation(record("known-disproof", 0, False), 5)
    evidence.ingest(disproof, trusted_host=True); data["evidence_bundle"] = evidence.snapshot()
    result = EvaluationReadiness(**data).validate_evidence()
    assert result["status"] == "READINESS_BLOCKED_NO_SURVIVING_HYPOTHESIS"
    assert any("known-disproof" in ids for ids in result["omitted_counterevidence"].values())


def test_same_code_semantics_relabel_cannot_hide_known_counterevidence(tmp_path):
    data = setup_data(tmp_path); evidence = type(ledger()).from_snapshot(data["evidence_bundle"])
    disproof = record("relabelled-known-negative", -1, False)
    disproof["provenance"]["origin"]["semantics"] = "different-provenance-label"
    assert evidence.ingest(disproof, trusted_host=True)["status"] == "ACCEPTED"
    data["evidence_bundle"] = evidence.snapshot()
    result = EvaluationReadiness(**data).validate_evidence()
    assert result["status"] == "READINESS_BLOCKED_NO_SURVIVING_HYPOTHESIS"
    assert any("relabelled-known-negative" in ids for ids in result["omitted_counterevidence"].values())


def test_conflicted_replay_history_cannot_restore_qualification_by_omitting_both_rows(tmp_path):
    data = setup_data(tmp_path); evidence = type(ledger()).from_snapshot(data["evidence_bundle"])
    evidence.ingest(record("later-positive", -1, True), trusted_host=True)
    conflict = evidence.ingest(record("later-conflict", -1, False), trusted_host=True)
    assert conflict["reasons"] == ["INCONSISTENT_REPLAY"]
    data["evidence_bundle"] = evidence.snapshot()
    result = EvaluationReadiness(**data).validate_evidence()
    assert result["status"] == "READINESS_BLOCKED_NO_VALID_FAILURE"
    assert "inconsistent-known-scope" in result["reasons"][0]


@pytest.mark.parametrize("field", ["canonical_function_identity", "cross_revision_function_key", "normalized_ast_clone_sha256", "implementation_sha256"])
def test_individual_consumed_identity_blocks_alias_mixed_batch(tmp_path, field):
    data = setup_data(tmp_path)
    consumed = identity(8); consumed[field] = data["targets"][0]["identity"][field]
    data["lineage_review"]["consumed_targets"] = [consumed]
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] == "READINESS_BLOCKED_NO_APPLICABLE_TARGET"


def test_hidden_target_payload_and_c_as_target_are_blocked(tmp_path):
    data = setup_data(tmp_path); data["targets"][0]["patch"] = "hidden"
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] != "PASS"
    data = setup_data(tmp_path); target = data["targets"][0]
    target["identity"] = identity(2)
    target["provenance"] = different_implementation(record(), 2)["provenance"]["origin"]
    for receipt in (target["oracle_validation"], target["controls"]):
        receipt.update(target_identity_sha256=digest(target["identity"]), oracle_sha256=target["provenance"]["oracle_sha256"])
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] == "READINESS_BLOCKED_NO_APPLICABLE_TARGET"


def test_oracle_and_evaluator_controls_are_identity_spec_and_scope_bound(tmp_path):
    data = setup_data(tmp_path); data["targets"][0]["controls"]["oracle_sha256"] = "0"*64
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] == "READINESS_BLOCKED_ORACLE"
    data = setup_data(tmp_path); data["targets"][0]["controls"]["scope"] = "REVIEWED_REAL_PROJECT"
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] == "READINESS_BLOCKED_ORACLE"


def test_public_guard_rejecting_all_candidates_blocks_guidance(tmp_path):
    data = setup_data(tmp_path)
    for target in data["targets"]:
        target["public_guard"] = dict(kind="REVIEWED_PREDICATE", predicates=[False])
    result = EvaluationReadiness(**data).validate_guidance()
    assert result["status"] == "READINESS_BLOCKED_NO_EFFECTIVE_GUIDANCE"
    assert result["target_calls"] == result["oracle_calls"] == 0


def test_real_planner_effective_input_changes_authorize_and_fingerprint_repeats(tmp_path):
    data = setup_data(tmp_path)
    readiness = EvaluationReadiness(**data)
    first = readiness.authorize_final_comparison()
    assert first["status"] == "PASS"
    plans = readiness.get_prepared_plans()
    assert len(plans) == 4 and {p["method"] for p in plans} == {"B", "C"}
    assert all(p["plan"]["target_calls"] == p["plan"]["oracle_calls"] == 0 for p in plans)
    assert all(p["parent_plan_wall_seconds"] > 0 for p in plans)
    assert plans_fingerprint(plans) == first["bindings"]["prepared_plans_sha256"]
    changed_timings=deepcopy(plans)
    for row in changed_timings:
        row["parent_plan_wall_seconds"] += 100
    assert plans_fingerprint(changed_timings) == plans_fingerprint(plans)
    metrics=readiness.get_validation_metrics()
    assert metrics["readiness_validation_wall_seconds"] > 0
    assert metrics["cost_scope"].startswith("NON_ADDITIVE")
    second = readiness.authorize_final_comparison()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    plans[0]["plan"]["candidates"] = []
    assert readiness.get_prepared_plans()[0]["plan"]["candidates"]


def test_guided_metadata_without_changed_input_order_is_blocked_by_actual_planner(tmp_path):
    data = setup_data(tmp_path)
    evidence = type(ledger()).from_snapshot(data["evidence_bundle"])
    source_ids = ["source-positive", "source-negative"]
    for index, value in enumerate([-3, -2, -1, 2, 3]):
        row = record("complete-source-"+str(index), value, False)
        evidence.ingest(row, trusted_host=True); source_ids.append(row["record_id"])
        origin = row["provenance"]["origin"]
        data["lineage_review"]["development"].append(dict(record_id=row["record_id"], identity=identity(1),
            lineage=origin["lineage"], independence_id=origin["independence_id"], review_receipt_sha256="a"*64))
    knowledge = evidence.build_knowledge_archive(source_ids)
    for rid in ("C-positive", "C-negative"):
        knowledge.observe(evidence.observation(rid), trusted_observation=True)
    data.update(evidence_bundle=evidence.snapshot(), knowledge_snapshot=knowledge.freeze())
    readiness = EvaluationReadiness(**data)
    assert readiness.validate_target_contracts()["status"] == "PASS"
    result = readiness.validate_guidance()
    assert result["status"] == "READINESS_BLOCKED_NO_EFFECTIVE_GUIDANCE"
    assert "identical-input-order" in result["reasons"][0]
    assert readiness.get_prepared_plans() == []


def test_caller_mutation_does_not_change_captured_contract(tmp_path):
    data = setup_data(tmp_path); readiness = EvaluationReadiness(**data)
    data["targets"][0]["patch"] = "hidden"
    assert readiness.validate_target_contracts()["status"] == "PASS"
    assert EvaluationReadiness(**data).validate_target_contracts()["status"] != "PASS"


def test_usage_start_remains_consumed_with_alias_output_oracle_seed_changes(tmp_path):
    usage = UsageLedger(tmp_path/"host-authority.jsonl")
    authorization = {"status":"PASS", "bindings":{"authority_id":usage.authority_id}}
    target = {"identity":identity(3), "target_id":"first-alias"}
    row = usage.claim([target], authorization, output=tmp_path/"first")
    assert usage.inspect()["open_claim_ids"] == [row["claim_id"]]
    alias = dict(target, target_id="new-name", oracle="different", seed=999)
    with pytest.raises(PermissionError, match="already consumed"):
        usage.claim([alias], authorization, output=tmp_path/"changed-output")
    usage.complete(row["claim_id"], {"status":"ERROR"})
    with pytest.raises(PermissionError):
        usage.claim([alias], authorization)


def test_usage_exclusive_lock_and_corruption_fail_closed(tmp_path):
    usage = UsageLedger(tmp_path/"host-authority.jsonl")
    lock = usage.path.with_name(usage.path.name+".lock"); lock.write_text("busy")
    auth = {"status":"PASS", "bindings":{"authority_id":usage.authority_id}}
    with pytest.raises(FileExistsError): usage.claim([identity(3)], auth)
    lock.unlink(); usage.path.write_text('{"event":"START"}\n')
    with pytest.raises(ValueError): usage.inspect()


def test_usage_complete_json_without_final_newline_is_not_a_committed_append(tmp_path):
    usage = UsageLedger(tmp_path/"host-authority.jsonl")
    auth = {"status":"PASS", "bindings":{"authority_id":usage.authority_id}}
    usage.claim([identity(3)], auth)
    usage.path.write_bytes(usage.path.read_bytes().rstrip(b"\n"))
    with pytest.raises(ValueError, match="terminal newline"):
        usage.inspect()


def test_paired_buggy_fixed_controls_share_history_tokens_once_without_alias_loophole(tmp_path):
    usage = UsageLedger(tmp_path/"host-authority.jsonl")
    auth = {"status":"PASS", "bindings":{"authority_id":usage.authority_id}}
    positive = dict(identity=identity(3), evaluation_role="POSITIVE_REPRODUCTION", control_group="historical-pair")
    clean = dict(identity=identity(4), evaluation_role="CLEAN_CONTROL", control_group="historical-pair")
    clean["identity"]["cross_revision_function_key"] = positive["identity"]["cross_revision_function_key"]
    usage.claim([positive, clean], auth)
    with pytest.raises(PermissionError): usage.claim([clean], auth)
    other = UsageLedger(tmp_path/"separate-unit-fixture.jsonl")
    bad = deepcopy(positive); bad["evaluation_role"] = "CLEAN_CONTROL"
    with pytest.raises(ValueError, match="distinct buggy/fixed"):
        other.claim([positive, bad], {"status":"PASS", "bindings":{"authority_id":other.authority_id}})


def test_batch_requires_actual_positive_and_clean_target_roles(tmp_path):
    data = setup_data(tmp_path); data["targets"] = data["targets"][:1]
    result = EvaluationReadiness(**data).validate_target_contracts()
    assert result["status"] == "READINESS_BLOCKED_NO_APPLICABLE_TARGET"


def test_runtime_and_product_drift_block_before_plan_generation(tmp_path):
    data = setup_data(tmp_path); data["fixed_protocol"]["versions"]["python"] = "0.0"
    assert EvaluationReadiness(**data).validate_guidance()["status"] == "READINESS_BLOCKED_NO_EFFECTIVE_GUIDANCE"
    data = setup_data(tmp_path); data["fixed_protocol"]["product_hashes"]["tomolab/discovery/knowledge.py"] = "0"*64
    assert EvaluationReadiness(**data).validate_guidance()["status"] == "READINESS_BLOCKED_NO_EFFECTIVE_GUIDANCE"
    data=setup_data(tmp_path)
    data["fixed_protocol"]["decision_rules"]=dict(max_reuse_cost_ratio=0.8,max_extra_discovery_cost_ratio=1.25,
        source_costs=dict(S_seconds=1.0,C_seconds=1.0,archive_seconds=1.0,receipt_sha256="a"*64))
    assert EvaluationReadiness(**data)._protocol()["decision_rules"]["source_costs"]["S_seconds"] == 1.0
    data["fixed_protocol"]["decision_rules"]["source_costs"]["S_seconds"]=-1.0
    assert EvaluationReadiness(**data).validate_guidance()["status"] == "READINESS_BLOCKED_NO_EFFECTIVE_GUIDANCE"
