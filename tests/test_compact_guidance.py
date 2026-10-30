"""Authored Source-shaped fixture and actual compact subprocess execution."""
from copy import deepcopy
import json

import pytest

from tomolab.discovery.compact_guidance import (MAX_ARTIFACT_BYTES, MAX_MESSAGE,
    compile_execution_artifact, generate_baseline_candidates, host_candidate_plan, prepare_recipe_from_archive,
    validate_execution_artifact, validate_numerical_request)
from tomolab.discovery.knowledge import KnowledgeArchive
from tomolab.discovery.numerical_boundary import GENERATOR_FILES, NumericalBoundary
from tomolab.discovery.numerical_guidance import public_input_contract
from tomolab.discovery.schema import canonical, digest


@pytest.fixture(scope="module")
def compiled():
    item = {"kind": "list", "min_size": 3, "max_size": 6,
            "items": {"kind": "float", "min": -1.0, "max": 1.0}}
    spec = {"schema": "tomolab-discovery-spec-v1", "task_id": "authored-numerical-compact",
        "inputs": [{"name": "a", "role": "left-series", "type": deepcopy(item)},
                   {"name": "b", "role": "right-series", "type": deepcopy(item)}],
        "contract": {"id": "authored-correlation", "operation": "robust-linear-correlation",
            "preconditions": ["equal-series-lengths", "robust-numeric-variance-domain"],
            "invariants": ["independent-equivalence"], "state_model": "stateless", "graph_signature": "UNKNOWN"}}
    origin = {"project": "authored-fixture", "lineage": "authored-numerical", "revision": "fixture-v1",
        "oracle_id": "authored-membership", "semantics": "robust-linear-correlation",
        "implementation_sha256": "1"*64, "oracle_sha256": "2"*64, "independence_id": "authored-review"}
    evidence = []
    for i, (value, failed) in enumerate(((0.1, True), (0.25, False))):
        evidence.append({"evidence_id": "authored-"+str(i), "kind": "FAILURE" if failed else "REFUTATION",
            "inputs": {"a": [value]*3, "b": [value]*3}, "invariant": "independent-equivalence",
            "category": "mismatch", "signature": "authored-centering"})
    archive = KnowledgeArchive.from_failure_log(spec, evidence, origin,
        semantic_policy={"max_compound_relations": 0})
    snapshot = archive.freeze()
    prepared = prepare_recipe_from_archive(snapshot)
    bundle = compile_execution_artifact(snapshot, [prepared["recipe"]], public_input_contract())
    return snapshot, prepared, bundle


def plan_fields(bundle, **changes):
    result = {"artifact": bundle["artifact"], "approval_receipt": bundle["approval_receipt"],
        "expected_digest": bundle["artifact"]["artifact_digest"],
        "seed": 17, "size": 12, "max_examples": 128, "excluded_digests": []}
    result.update(changes)
    return result


def test_host_compiler_preserves_original_and_excludes_full_archive_and_answers(compiled):
    snapshot, prepared, bundle = compiled
    before = canonical(snapshot)
    assert KnowledgeArchive.from_snapshot(snapshot).snapshot() == snapshot
    assert canonical(snapshot) == before
    assert prepared["metrics"]["source_rows"] == 2
    assert len(canonical(bundle["artifact"]).encode()) < MAX_ARTIFACT_BYTES
    assert bundle["metrics"]["source_archive_bytes"] > bundle["metrics"]["artifact_bytes"]
    assert bundle["metrics"]["original_archive_sent_to_worker"] is False
    encoded = canonical(bundle["artifact"])
    assert '"journal"' not in encoded and '"inputs"' not in encoded
    assert '"actual"' not in encoded and '"expected"' not in encoded
    assert bundle["artifact"]["source_archive_digest"] == snapshot["receipt"]["sha256"]
    assert bundle["approval_receipt"]["source_archive_content_digest"] == digest(snapshot)


def test_rehashing_an_edited_original_archive_does_not_grant_compiler_approval(compiled):
    snapshot, _, bundle = compiled
    changed = deepcopy(snapshot)
    changed["claims"][0]["source_claim_status"] = "OBSERVED_WITHIN_SOURCE"
    if changed["claims"][0] == snapshot["claims"][0]:
        changed["claims"][0]["source_claim_status"] = "CONTRADICTED"
    changed["receipt"]["sha256"] = digest({k:v for k,v in changed.items() if k != "receipt"})
    with pytest.raises(ValueError):
        compile_execution_artifact(changed, bundle["artifact"]["bounded_recipe_parameters"], public_input_contract())


def test_recipe_weights_must_be_derived_from_the_actual_verified_rows(compiled):
    snapshot, prepared, _ = compiled
    changed = deepcopy(prepared["recipe"])
    family = next(iter(changed["parameter_strategy"]["weights"]))
    changed["parameter_strategy"]["calibration_counts"][family] = {"failure": 1, "normal": 1}
    changed["parameter_strategy"]["weights"][family] = 8
    changed["known_counterevidence"]["normal_observations"] = sum(
        row["normal"] for row in changed["parameter_strategy"]["calibration_counts"].values())
    with pytest.raises(ValueError, match="actual validated"):
        compile_execution_artifact(snapshot, [changed], public_input_contract())


def test_recipe_refs_cannot_point_to_an_unvalidated_archive(compiled):
    snapshot, prepared, _ = compiled
    changed = deepcopy(prepared["recipe"])
    changed["source_evidence_refs"] = ["archive-receipt:"+"9"*64]
    with pytest.raises(ValueError, match="verified source archive"):
        compile_execution_artifact(snapshot, [changed], public_input_contract())


def test_worker_rejects_artifact_tampering_even_after_self_rehash(compiled):
    _, _, bundle = compiled
    artifact = deepcopy(bundle["artifact"])
    artifact["counterevidence_state_reference"] = "9"*64
    artifact["artifact_digest"] = digest({k:v for k,v in artifact.items() if k != "artifact_digest"})
    with pytest.raises(ValueError, match="separately approved"):
        validate_execution_artifact(artifact, bundle["artifact"]["artifact_digest"], bundle["approval_receipt"])


@pytest.mark.parametrize("field,value", [("schema_version", "future"),
    ("semantic_contract_version", "future"), ("compiler_version", "future"),
    ("applicability_scope", "FINAL_TARGET")])
def test_worker_versions_and_source_only_scope_are_fail_closed(compiled, field, value):
    _, _, bundle = compiled
    artifact = deepcopy(bundle["artifact"])
    artifact[field] = value
    with pytest.raises(ValueError, match="schema, version or applicability"):
        validate_execution_artifact(artifact, bundle["artifact"]["artifact_digest"], bundle["approval_receipt"])


def test_an_artifact_and_new_hash_are_insufficient_without_original_host_link(compiled):
    _, _, bundle = compiled
    artifact = deepcopy(bundle["artifact"])
    artifact["source_archive_digest"] = "9"*64
    artifact["bounded_recipe_parameters"][0]["provenance"]["source_archive_digest"] = "9"*64
    artifact["artifact_digest"] = digest({k:v for k,v in artifact.items() if k != "artifact_digest"})
    with pytest.raises(ValueError, match="linkage"):
        validate_execution_artifact(artifact, artifact["artifact_digest"], bundle["approval_receipt"])


def test_artifact_and_overall_request_have_independent_size_limits(compiled):
    _, _, bundle = compiled
    oversized = {"padding": "x"*MAX_ARTIFACT_BYTES}
    with pytest.raises(ValueError, match="compact artifact exceeds"):
        validate_execution_artifact(oversized, "1"*64, {})
    with pytest.raises(ValueError, match="request exceeds"):
        validate_numerical_request({"action": "plan", "padding": "x"*MAX_MESSAGE})
    fields = plan_fields(bundle)
    assert len(canonical(dict(action="plan", **fields)).encode())+1 < MAX_MESSAGE


def test_execution_contract_may_narrow_lengths_but_not_broaden_profile(compiled):
    _, _, bundle = compiled
    fields = plan_fields(bundle, contract=public_input_contract(lengths=[4, 5, 6]))
    accepted = validate_numerical_request(dict(action="plan", **fields))
    assert accepted["contract"]["lengths"] == [4, 5, 6]
    fields["contract"] = public_input_contract("NEAR_CONSTANT_DIAGNOSTIC")
    with pytest.raises(ValueError, match="broadens"):
        validate_numerical_request(dict(action="plan", **fields))


def test_host_and_actual_subprocess_worker_generate_identical_new_candidates(compiled):
    _, _, bundle = compiled
    fields = plan_fields(bundle, contract=public_input_contract(lengths=[4, 5, 6]))
    host = host_candidate_plan(**fields)
    assert host["reference_execution"] == "CLEAN_HOST_SUBPROCESS_REFERENCE"
    with NumericalBoundary() as boundary:
        worker = boundary.request("plan", **fields)
        assert worker["candidate_digest"] == host["candidate_digest"]
        assert worker["generation"]["candidates"] == host["generation"]["candidates"]
        assert worker["generation"]["oracle_calls"] == worker["generation"]["target_calls"] == 0
        assert all(len(row["inputs"]["a"]) in (4, 5, 6) for row in worker["generation"]["candidates"])
        assert boundary.request("snapshot")["candidate_digest"] == host["candidate_digest"]
        receipt = boundary.receipt
        assert receipt["full_archive_transmitted"] is receipt["oracle_modules_transmitted"] is False
        assert receipt["isolation"] == "LOGICAL_ISOLATION_ONLY"
        assert set(receipt["generator_sha256"]) == set(GENERATOR_FILES)


def test_freeze_blocks_feedback_and_new_parameters_before_transport(compiled):
    _, _, bundle = compiled
    fields = plan_fields(bundle, size=2, max_examples=16)
    with NumericalBoundary() as boundary:
        boundary.request("plan", **fields)
        count = boundary.receipt["validated_requests"]
        for action, updates in (("observe", {"evidence": {}}), ("plan", fields),
                                ("init", {"spec": {}}), ("learn", {})):
            with pytest.raises(ValueError, match="before transport"):
                boundary.request(action, **updates)
        assert boundary.receipt["validated_requests"] == count


def test_raw_answer_or_code_fields_are_rejected_before_worker_transport(compiled):
    _, _, bundle = compiled
    for forbidden in ("actual", "expected", "oracle_outputs", "target_code", "journal"):
        with pytest.raises(ValueError):
            validate_numerical_request(dict(action="plan", **plan_fields(bundle), **{forbidden: []}))
    assert not any("oracle" in name or name == "knowledge.py" for name in GENERATOR_FILES)


def test_loaded_host_constants_do_not_change_reference_or_baseline_candidates(compiled, tmp_path, monkeypatch):
    """Public module constants used to perturb native draws in the host.

    Fresh public-code processes prevent the same mechanism from accidentally
    mining evaluator/Oracle constants, without patching Hypothesis internals.
    """
    import sys
    from types import ModuleType
    fields = plan_fields(compiled[2], size=4, max_examples=64)
    before_reference = host_candidate_plan(**fields)
    before_baseline = generate_baseline_candidates("B", seed=17, size=4, max_examples=64)
    public_module = tmp_path/"public_context_constants.py"
    public_module.write_text("PUBLIC_DIAGNOSTIC_CONSTANT = 0.01000000000017\n", encoding="utf-8")
    context = ModuleType("public_context_constants")
    context.__file__ = str(public_module)
    context.PUBLIC_DIAGNOSTIC_CONSTANT = 0.01000000000017
    monkeypatch.setitem(sys.modules, context.__name__, context)
    after_reference = host_candidate_plan(**fields)
    after_baseline = generate_baseline_candidates("B", seed=17, size=4, max_examples=64)
    assert before_reference["generation"]["candidates"] == after_reference["generation"]["candidates"]
    assert before_baseline["candidates"] == after_baseline["candidates"]
    assert after_baseline["generation_execution"] == "CLEAN_HOST_SUBPROCESS_BASELINE"
    assert set(after_baseline["generation_boundary"]["generator_sha256"]) == set(GENERATOR_FILES)


@pytest.mark.parametrize("method", ["A", "B"])
def test_uninformed_baselines_cannot_receive_failure_material_or_guides(method):
    request = {"action": "baseline", "method": method, "seed": 7, "size": 2,
        "max_examples": 16, "excluded_digests": [], "contract": public_input_contract()}
    for forbidden, value in (("replay_inputs", []), ("recipe", {}), ("artifact", {}),
                             ("oracle_outputs", []), ("labels", []), ("journal", [])):
        with pytest.raises(ValueError):
            validate_numerical_request(dict(request, **{forbidden: value}))


def test_c_receives_only_bounded_input_exemplars_not_oracle_answers():
    request = {"action": "baseline", "method": "C", "seed": 7, "size": 2,
        "max_examples": 16, "excluded_digests": [], "contract": public_input_contract(),
        "replay_inputs": [{"a": [0.1]*3, "b": [0.1]*3}]}
    assert validate_numerical_request(request)["replay_inputs"] == request["replay_inputs"]
    bad = deepcopy(request); bad["replay_inputs"][0]["expected"] = {"computable": False}
    with pytest.raises(ValueError, match="replay inputs"):
        validate_numerical_request(bad)
    bad = deepcopy(request); bad["replay_inputs"] *= 65
    with pytest.raises(ValueError, match="one to 64"):
        validate_numerical_request(bad)


def test_baseline_worker_freezes_after_generation_and_cannot_be_repurposed():
    with NumericalBoundary() as boundary:
        generated = boundary.request("baseline", method="A", seed=7, size=2, max_examples=16,
            excluded_digests=[], contract=public_input_contract())
        assert generated["oracle_calls"] == generated["target_calls"] == 0
        assert boundary.request("snapshot")["frozen"]
        count = boundary.receipt["validated_requests"]
        with pytest.raises(ValueError, match="before transport"):
            boundary.request("baseline", method="B", seed=9, size=2, max_examples=16,
                excluded_digests=[], contract=public_input_contract())
        assert boundary.receipt["validated_requests"] == count
