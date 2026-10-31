"""Authored functional fixtures only; no private research observations."""
from copy import deepcopy

import pytest

from tomolab.discovery.development_evidence import DevelopmentEvidenceArchive, normalize_development_record
from tomolab.discovery.schema import digest


def record(rid="record-1", value=0, failed=True, producer="NativeHypothesis"):
    spec = {"schema": "tomolab-discovery-spec-v1", "task_id": "authored-fixture",
            "inputs": [{"name": "value", "role": "operand", "type": {"kind": "int", "min": -3, "max": 3}}],
            "contract": {"id": "authored-zero", "operation": "reciprocal", "preconditions": [],
                         "invariants": ["reference"], "state_model": "stateless", "graph_signature": "UNKNOWN"}}
    origin = dict(project="authored-fixture", lineage="authored-lineage", revision="authored-revision",
                  oracle_id="authored-oracle", semantics="authored-reciprocal", implementation_sha256="1"*64,
                  oracle_sha256="2"*64, independence_id="authored-review")
    inputs = {"value": value}
    bindings = dict(implementation_hash="1"*64, oracle_identity="authored-oracle", oracle_hash="2"*64,
                    public_spec_hash=digest(spec), input_hash=digest(inputs), original_receipt_sha256="3"*64)
    return dict(record_id=rid, generation_id="E8-AUTHORED", split="DEVELOPMENT", producer_tool=producer,
                producer_version="fixture-1", project=origin["project"], revision=origin["revision"],
                function_identity="authored_function", implementation_hash="1"*64,
                oracle_identity="authored-oracle", oracle_hash="2"*64, public_spec_hash=digest(spec), spec=spec,
                oracle_validation_receipt=dict(status="VALIDATED", receipt_id="authored-oracle-review", oracle_hash="2"*64,
                    public_spec_hash=digest(spec), receipt_sha256="4"*64, bindings=deepcopy(bindings)),
                domain_validity=dict(status="VALID", receipt_sha256="5"*64, bindings=deepcopy(bindings)),
                input_or_trace=inputs, observed_failure_or_refutation=dict(status="FAILURE" if failed else "REFUTATION",
                    invariant="reference", category="mismatch", actual_result={"fixture-secret": failed}, oracle_result=False),
                failure_signature="authored-zero-mismatch", replay_status=dict(status="REPRODUCED", deterministic=True,
                    matching_observations=2, receipt_sha256="6"*64, bindings=deepcopy(bindings)),
                execution_receipt=dict(status="COMPLETED", execution_kind="CACHED_REPLAY", target_calls=0, oracle_calls=0,
                    original_target_calls=2, original_oracle_calls=2, original_receipt_sha256="3"*64, bindings=deepcopy(bindings)),
                provenance=dict(origin=origin, evidence_origin="AUTHORED_FUNCTIONAL_FIXTURE", parent_generation_id="E7-AUTHORED",
                    source_file_sha256="7"*64, source_record_sha256="8"*64))


def ledger():
    return DevelopmentEvidenceArchive("E8-AUTHORED", parent_generation_ids=["E7-AUTHORED"])


def test_native_hypothesis_and_other_producers_share_the_evidence_contract():
    archive = ledger()
    with pytest.raises(PermissionError):
        archive.ingest(record())
    assert archive.ingest(record(), trusted_host=True)["status"] == "ACCEPTED"
    assert archive.ingest(record("record-2", producer="AnotherReviewedProducer"), trusted_host=True)["status"] == "DUPLICATE"
    assert len(archive.accepted_records()) == 1
    assert archive.summary()["unknown_mechanism_failure_groups"] == 1
    assert archive.summary()["unique_reviewed_defect_mechanisms"] == 0
    assert all(not row["decision"]["independent_implementation_claimed"] for row in archive.snapshot()["journal"])


@pytest.mark.parametrize("field,status,reason", [
    ("oracle_validation_receipt", "INVALID_ORACLE", "INVALID_ORACLE"),
    ("domain_validity", "OUT_OF_DOMAIN", "OUT_OF_DOMAIN"),
    ("execution_receipt", "ERROR", "EXECUTION_ERROR"),
    ("replay_status", "MISMATCH", "REPLAY_NOT_VERIFIED"),
    ("observed_failure_or_refutation", "ERROR", "INVALID_OBSERVATION"),
])
def test_invalid_observations_are_retained_and_never_become_refutations(field, status, reason):
    archive = ledger(); value = record(failed=False); value[field]["status"] = status
    result = archive.ingest(value, trusted_host=True)
    assert result["status"] == "QUARANTINED" and reason in result["reasons"]
    assert archive.accepted_records() == []
    assert archive.snapshot()["journal"][0]["record"][field]["status"] == status
    with pytest.raises(ValueError): archive.generator_evidence(value["record_id"])


def test_nondeterminism_quarantines_new_conflict_without_deleting_old_original():
    archive = ledger(); archive.ingest(record(), trusted_host=True)
    result = archive.ingest(record("contradiction", failed=False), trusted_host=True)
    assert result["reasons"] == ["INCONSISTENT_REPLAY"]
    assert len(archive.snapshot()["journal"]) == 2 and not archive.accepted_records()
    with pytest.raises(ValueError): archive.generator_evidence("record-1")
    restored = DevelopmentEvidenceArchive.from_snapshot(archive.snapshot())
    assert not restored.accepted_records()


def test_receipt_binding_cannot_substitute_another_input_or_implementation():
    for receipt in ("oracle_validation_receipt", "domain_validity", "execution_receipt", "replay_status"):
        value = record(); value[receipt]["bindings"]["input_hash"] = "9"*64
        with pytest.raises(ValueError, match="bound to different"):
            normalize_development_record(value)
    value = record(); value["provenance"]["origin"]["implementation_sha256"] = "9"*64
    with pytest.raises(ValueError, match="reviewed provenance"):
        normalize_development_record(value)


def test_final_records_and_cached_claims_of_new_execution_are_rejected():
    value = record(); value["split"] = "FINAL"
    with pytest.raises(ValueError, match="DEVELOPMENT"):
        normalize_development_record(value)
    value = record(); value["execution_receipt"]["target_calls"] = 2
    with pytest.raises(ValueError, match="cached"):
        normalize_development_record(value)


def test_generator_export_is_exact_minimal_contract_without_host_results():
    archive = ledger(); archive.ingest(record(), trusted_host=True)
    minimal = archive.generator_evidence("record-1")
    assert set(minimal) == {"kind", "evidence_id", "inputs", "invariant", "category", "signature"}
    observation = archive.observation("record-1")
    assert observation["evidence"] == minimal
    assert "fixture-secret" not in str(observation)
    assert observation["split"] == "development"
    assert "fixture-secret" in str(archive.accepted_records()[0])


def test_archive_reuses_real_version_space_and_normal_observations_refute_candidates():
    archive = ledger()
    archive.ingest(record(), trusted_host=True)
    archive.ingest(record("normal", value=1, failed=False), trusted_host=True)
    knowledge = archive.build_knowledge_archive()
    assert knowledge.claims()
    assert any(c["status"] == "CONTRADICTED" for c in knowledge.claims())
    assert any(c["status"] == "HYPOTHESIS" and not c["coordinate_only"] for c in knowledge.claims())
    assert all(c["status"] != "SUPPORTED_WITHIN_SCOPE" for c in knowledge.claims())
    assert archive.summary()["new_target_calls"] == archive.summary()["new_oracle_calls"] == 0


def test_append_only_id_conflict_parent_and_snapshot_replay_checks():
    archive = ledger(); archive.ingest(record(), trusted_host=True)
    with pytest.raises(ValueError, match="ID conflict"):
        archive.ingest(record(failed=False), trusted_host=True)
    value = record("wrong-parent"); value["provenance"]["parent_generation_id"] = "UNDECLARED"
    with pytest.raises(ValueError, match="parent"):
        archive.ingest(value, trusted_host=True)
    original = archive.snapshot(); restored = DevelopmentEvidenceArchive.from_snapshot(original)
    assert restored.snapshot() == original
    altered = deepcopy(original); altered["journal"][0]["decision"]["status"] = "DUPLICATE"
    altered["receipt_sha256"] = digest({k:v for k,v in altered.items() if k != "receipt_sha256"})
    with pytest.raises(ValueError, match="replay mismatch"):
        DevelopmentEvidenceArchive.from_snapshot(altered)
    captured = archive.accepted_records(); captured[0]["input_or_trace"]["value"] = 3
    assert archive.accepted_records()[0]["input_or_trace"]["value"] == 0


def test_execution_cost_fields_require_nonnegative_numbers_not_truthy_strings():
    for field, value in [("original_target_calls", True), ("original_oracle_calls", "2"), ("wall_seconds", -1), ("wall_seconds", True)]:
        original = record(); original["execution_receipt"][field] = value
        with pytest.raises(ValueError): normalize_development_record(original)


def test_changed_failure_family_is_conflict_even_when_actual_results_match():
    archive = ledger(); archive.ingest(record(), trusted_host=True)
    other = record("changed-family"); other["failure_signature"] = "another-reviewed-family"
    assert archive.ingest(other, trusted_host=True)["reasons"] == ["INCONSISTENT_REPLAY"]
    assert not archive.accepted_records()


def bounded_source_records(total, failure_index=0):
    archive = ledger()
    for index in range(total):
        value = record("bounded-%04d" % index, failed=index == failure_index)
        value["spec"]["inputs"][0]["type"] = {"kind": "str", "alphabet": "ab", "min_size": 0, "max_size": 9}
        value["input_or_trace"] = {"value": "" if index == 0 else format(index - 1, "09b").replace("0", "a").replace("1", "b")}
        value["public_spec_hash"] = digest(value["spec"])
        value["oracle_validation_receipt"]["public_spec_hash"] = value["public_spec_hash"]
        for receipt in ("oracle_validation_receipt", "domain_validity", "replay_status", "execution_receipt"):
            value[receipt]["bindings"].update(public_spec_hash=value["public_spec_hash"], input_hash=digest(value["input_or_trace"]))
        assert archive.ingest(value, trusted_host=True)["status"] == "ACCEPTED"
    return archive


@pytest.mark.parametrize("total", [257, 512])
def test_source_cap_uses_existing_observation_path_without_claiming_independence(total):
    archive = bounded_source_records(total)
    knowledge = archive.build_knowledge_archive()
    snapshot = knowledge.snapshot()
    assert snapshot["source_observations"] == 256
    assert snapshot["independent_observations"] == total - 256  # Legacy row-count name; this origin is the SAME source.
    assert len(snapshot["journal"]) == 1 + total - 256
    assert snapshot["journal"][1]["action"] == "observe"
    assert snapshot["journal"][1]["observation"] == archive.observation("bounded-0256")
    assert all(not c["independent_positive"] and not c["independent_negative"] for c in knowledge.claims())
    assert not any(c["status"] == "SUPPORTED_WITHIN_SCOPE" for c in knowledge.claims())


def test_over_capacity_and_late_first_failure_fail_without_reordering_records():
    archive = bounded_source_records(513)
    with pytest.raises(ValueError, match="capacity"):
        archive.build_knowledge_archive()
    assert len(archive.accepted_records()) == 513
    late = bounded_source_records(257, failure_index=256)
    with pytest.raises(ValueError, match="prefix has no valid failure"):
        late.build_knowledge_archive()
    assert late.accepted_records()[0]["record_id"] == "bounded-0000"
