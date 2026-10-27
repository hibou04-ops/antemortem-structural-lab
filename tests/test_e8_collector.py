"""Authored integer fixtures, never research or private project observations.

The sum of per-test primitive-call ceilings is 92, below the separately
authorized 256-call functional verification budget. Counts include replays.
"""
from copy import deepcopy

import pytest

from tomolab.discovery.development_collector import collect_native_development
from tomolab.discovery.development_evidence import DevelopmentEvidenceArchive
from tomolab.discovery.schema import digest


def fixture(domain_max=1):
    spec = {"schema": "tomolab-discovery-spec-v1", "task_id": "authored-native-collector",
            "inputs": [{"name": "value", "role": "operand", "type": {"kind": "int", "min": 0, "max": domain_max}}],
            "contract": {"id": "authored-integer-identity", "operation": "identity", "preconditions": [],
                         "invariants": ["reference"], "state_model": "stateless", "graph_signature": "UNKNOWN"}}
    origin = dict(project="authored-fixture", lineage="authored-collector-fixture", revision="authored-only",
                  oracle_id="authored-identity-oracle", semantics="authored-integer-identity", implementation_sha256="1"*64,
                  oracle_sha256="2"*64, independence_id="authored-functional-review")
    review = dict(status="VALIDATED", receipt_id="authored-math-identity-review", oracle_hash="2"*64,
                  public_spec_hash=digest(spec), receipt_sha256="3"*64, authority="AUTHORED_FUNCTIONAL_TEST_ONLY",
                  comparison_policy="EXACT_CANONICAL_JSON")
    return dict(spec=spec, provenance=origin, function_identity="authored_fixture", generation_id="E8-AUTHORED-COLLECTOR",
                oracle_validation_receipt=review, budget=8, seed=7, trusted_execution=True)


def oracle(value):
    return value


def test_explicit_approval_and_pinned_oracle_are_required_before_any_callback():
    called = []
    def callback(value):
        called.append("target")
        return value
    def reference(value):
        called.append("oracle")
        return value
    def guard(point):
        called.append("guard")
        return True
    options = fixture(); options["trusted_execution"] = False
    with pytest.raises(PermissionError):
        collect_native_development(callback, reference, input_accepts=guard, **options)
    options = fixture(); options["oracle_validation_receipt"]["public_spec_hash"] = "4"*64
    with pytest.raises(ValueError, match="before execution"):
        collect_native_development(callback, reference, input_accepts=guard, **options)
    options = fixture(); options["oracle_validation_receipt"]["comparison_policy"] = "NUMERIC_TOLERANCE"
    with pytest.raises(ValueError, match="EXACT_CANONICAL_JSON"):
        collect_native_development(callback, reference, input_accepts=guard, **options)
    assert not called


def test_native_find_shrink_and_two_fresh_replays_produce_bound_host_evidence():
    target_calls, oracle_calls = [], []
    def target(value):
        target_calls.append(value)
        return value + 1 if value == 0 else value
    def reference(value):
        oracle_calls.append(value)
        return value
    result = collect_native_development(target, reference, max_calls=18, **fixture())
    summary, raw = result["summary"], result["raw_receipt"]
    assert result["status"] == "VALID_FAILURE_COLLECTED"
    assert summary["actual_target_calls"] == len(target_calls)
    assert summary["actual_oracle_calls"] == len(oracle_calls)
    assert summary["actual_primitive_calls"] == len(target_calls) + len(oracle_calls) <= 18
    assert summary["replay_target_calls"] >= 2 and summary["replay_oracle_calls"] >= 2
    assert result["native_search"]["cache_enabled"] is False
    assert result["native_search"]["shrinking"] in ("NATIVE_COMPLETED", "INCOMPLETE_OR_NO_WITNESS")
    assert raw["receipt_sha256"] == digest({key: value for key, value in raw.items() if key != "receipt_sha256"})
    archive = DevelopmentEvidenceArchive.from_snapshot(result["evidence_bundle"])
    assert archive.summary()["new_target_calls"] == len(target_calls)
    assert archive.summary()["new_oracle_calls"] == len(oracle_calls)
    for record in archive.accepted_records():
        assert record["producer_version"] and record["execution_receipt"]["execution_kind"] == "NEW_EXECUTION"
        assert record["execution_receipt"]["original_receipt_sha256"] == raw["receipt_sha256"]
        assert record["provenance"]["source_file_sha256"] == raw["receipt_sha256"]
        event = archive.generator_evidence(record["record_id"])
        assert set(event) == {"kind", "evidence_id", "inputs", "invariant", "category", "signature"}
    assert archive.summary()["unique_reviewed_defect_mechanisms"] == 0


def test_normal_observations_need_real_replays_and_do_not_invent_a_failure():
    def target(value):
        return value
    result = collect_native_development(target, oracle, max_calls=18, **fixture())
    assert result["status"] == "NO_VALID_FAILURE_COLLECTED"
    archive = DevelopmentEvidenceArchive.from_snapshot(result["evidence_bundle"])
    assert archive.accepted_records()
    assert all(record["observed_failure_or_refutation"]["status"] == "REFUTATION" for record in archive.accepted_records())
    assert result["summary"]["actual_primitive_calls"] <= 18


@pytest.mark.parametrize("failing_side", ["oracle", "target"])
def test_target_and_oracle_exceptions_are_quarantined_not_product_refutations(failing_side):
    def throws(value):
        raise ArithmeticError("authored failure fixture")
    def normal(value):
        return value
    target, reference = (normal, throws) if failing_side == "oracle" else (throws, normal)
    result = collect_native_development(target, reference, max_calls=10, **fixture(0))
    assert not DevelopmentEvidenceArchive.from_snapshot(result["evidence_bundle"]).accepted_records()
    assert result["summary"]["valid_failures"] == 0
    assert result["summary"]["actual_primitive_calls"] <= 10
    assert result["summary"]["quarantine_reasons"]["EXECUTION_ERROR"]
    if failing_side == "oracle":
        assert result["summary"]["actual_target_calls"] == 0
        assert result["summary"]["quarantine_reasons"]["INVALID_ORACLE"]


def test_guard_rejection_is_not_a_target_execution_or_normal_observation():
    called = []
    def target(value):
        called.append(value)
        return value
    result = collect_native_development(target, oracle, max_calls=8, input_accepts=lambda point: False, **fixture())
    assert not called and result["summary"]["actual_primitive_calls"] == 0
    assert result["summary"]["domain_rejections"] > 0
    assert not DevelopmentEvidenceArchive.from_snapshot(result["evidence_bundle"]).accepted_records()
    assert result["summary"]["quarantine_reasons"]["OUT_OF_DOMAIN"]


def test_changing_outcome_is_quarantined_even_when_hypothesis_rejects_flakiness():
    calls = []
    def changing(value):
        calls.append(value)
        return len(calls) % 2
    result = collect_native_development(changing, oracle, max_calls=18, **fixture(0))
    assert result["summary"]["actual_target_calls"] == len(calls)
    assert result["summary"]["actual_primitive_calls"] <= 18
    assert not DevelopmentEvidenceArchive.from_snapshot(result["evidence_bundle"]).accepted_records()
    assert result["summary"]["quarantine_reasons"]["REPLAY_NOT_VERIFIED"]


def test_primitive_budget_includes_replays_and_unreplayed_normals_stay_quarantined():
    def target(value):
        return value
    result = collect_native_development(target, oracle, max_calls=10, **fixture(2))
    assert result["summary"]["actual_primitive_calls"] <= 10
    assert result["summary"]["replay_target_calls"] == result["summary"]["replay_oracle_calls"] == 2
    assert result["summary"]["quarantine_reasons"]["REPLAY_NOT_VERIFIED"]
    no_calls = collect_native_development(target, oracle, max_calls=0, **fixture())
    assert no_calls["summary"]["actual_primitive_calls"] == 0
    assert no_calls["evidence_bundle"]["journal"] == []
