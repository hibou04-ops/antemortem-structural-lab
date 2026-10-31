"""Authored paired executions exercise updates, not real-project independence."""
from copy import deepcopy

import pytest

from tomolab.discovery.online_engine import OnlinePolicy
from tomolab.discovery.online_learning import learn_mold
from tomolab.discovery.online_observe import inspect_target
from tomolab.discovery.recursive_observe import (make_diagnostics, new_trace,
    observe_proposal, execute_pairs)
from tomolab.discovery.recursive_policy import (initial_selector, make_context,
    choose_candidate, update_selector, make_development_manifest, validate_selector,
    validate_development_manifest, public_selector, validate_runtime_selector)
from tomolab.discovery.schema import digest, canonical

CONTRACT = dict(kind="sequence_int", low=-10, high=10, max_size=8)
EXPERIMENT = digest("authored-selector-functional-test-v1")


def authored_mold():
    return learn_mold([
        dict(input=[1, 2], status="PASS", contract=CONTRACT, source_identity="authored-source"),
        dict(input=[1, 1], status="FAILURE", contract=CONTRACT, source_identity="authored-source")],
        operator_grammar=["constantize"])


def paired_fixture(lineage="fixture-a", label="gain", run="wave-one"):
    """Execute six real calls on two candidates from one authored C state."""
    mold = authored_mold()
    identity = dict(implementation_sha256=digest(dict(authored=lineage, role="implementation")),
        oracle_sha256=digest(dict(authored=lineage, role="oracle")),
        environment_sha256=digest("authored-python-fixture-environment"),
        reset_adapter_sha256=digest("authored-pure-callable-reset"),
        purity_review_id="authored-pure-fixture-review")
    diagnostics = make_diagnostics(mold, experiment_contract_sha256=EXPERIMENT,
        source_lineage_id=lineage, project_id="authored-fixture-project", mechanism_id="authored-equality",
        run_id=run, identity=identity)
    config = diagnostics["public"]
    structure = inspect_target(sum, CONTRACT, mode="black_box")
    policy = OnlinePolicy(CONTRACT, method="C", seed=7, budget=100, structure=structure)
    policy.attempts = 2
    policy.last_feedback = dict(status="FAILURE", input_digest=digest([1, 2]), coverage=[],
        branch_distance=None, contract_checked=digest(CONTRACT))
    before = deepcopy(policy)
    actual = policy.propose([1, 2])
    trace = new_trace(config)
    observe_proposal(before, [1, 2], actual, config=config, trace=trace,
        seed=7, actual_calls_before=0, shadow_rule_state=None)
    assert len(trace["reservations"]) == 1

    def oracle(point):
        return sum(point)

    def target(point):
        mismatch = (label == "gain" and len(point) > 1 and len(set(point)) == 1
            or label == "loss" and len(point) == 1 or label == "neutral_failure")
        return sum(point) + int(mismatch)

    result = execute_pairs(trace, config=config, identity=identity, target=target,
        oracle=oracle, contract=CONTRACT, structure=structure, tracing=False,
        reset=(lambda: label != "UNKNOWN"))
    receipt = result["receipts"][0]
    assert receipt["label"] == label
    lineage_metadata = dict(source_lineage_id=lineage, project_id=config["project_id"],
        mechanism_id=config["mechanism_id"], implementation_sha256=identity["implementation_sha256"],
        oracle_sha256=identity["oracle_sha256"], input_contract_sha256=digest(CONTRACT),
        independence_id=lineage + ":authored-unit", review_id="authored-fixture-review")
    return receipt, lineage_metadata


def fixture_batch(labels, *, run="wave-one"):
    rows = [paired_fixture(name, label, run) for name, label in labels]
    receipts = [row[0] for row in rows]
    manifest = make_development_manifest([row[1] for row in rows], EXPERIMENT)
    return receipts, manifest


def test_empty_features_remain_unknown_and_g0_chooses_common():
    context = make_context([], CONTRACT, "delete", ["constantize"])
    assert context["all_equal"] == context["has_negative"] == "UNKNOWN"
    assert context["size_class"] == "EMPTY"
    selector = initial_selector(authored_mold()["artifact_digest"], input_contract_digest=digest(CONTRACT))
    assert choose_candidate(selector, context) == "common"


def test_actual_development_gain_changes_choice_and_new_loss_reverses_it():
    receipts, manifest = fixture_batch([("fixture-a", "gain"), ("fixture-b", "gain")])
    s0 = initial_selector(authored_mold()["artifact_digest"], input_contract_digest=digest(CONTRACT))
    s1 = update_selector(s0, receipts, manifest)
    context = receipts[0]["context"]
    assert choose_candidate(s0, context) == "common"
    assert choose_candidate(s1, context) == "learned"
    losses, second_manifest = fixture_batch([("fixture-a", "loss"), ("fixture-b", "loss")], run="wave-two")
    s2 = update_selector(s1, losses, second_manifest)
    assert choose_candidate(s2, context) == "common"
    assert s2["statistics"][0]["utility"] == 0
    assert [row["label"] for row in s2["evidence"]] == ["gain", "gain", "loss", "loss"]


def test_duplicate_receipt_replay_is_fully_idempotent():
    receipts, manifest = fixture_batch([("fixture-a", "gain"), ("fixture-b", "gain")])
    s1 = update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)
    assert update_selector(s1, receipts + receipts, manifest) == s1


def test_seed_repetition_does_not_create_independent_lineage_votes():
    receipt, metadata = paired_fixture("fixture-a", "gain", "seed-seven")
    repeated, _ = paired_fixture("fixture-a", "gain", "seed-eight")
    manifest = make_development_manifest([metadata], EXPERIMENT)
    selector = update_selector(initial_selector(authored_mold()["artifact_digest"]), [receipt, repeated], manifest)
    assert selector["statistics"][0]["resolved_lineages"] == 1
    assert choose_candidate(selector, receipt["context"]) == "common"


def test_neutral_types_and_unknown_are_preserved_without_zero_imputation():
    receipts, manifest = fixture_batch([("fixture-a", "neutral_pass"),
        ("fixture-b", "neutral_failure"), ("fixture-c", "UNKNOWN")])
    selector = update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)
    stats = selector["statistics"][0]
    assert stats["utility"] is None
    assert sum(row["neutral_pass"] for row in stats["lineages"]) == 1
    assert sum(row["neutral_failure"] for row in stats["lineages"]) == 1
    assert sum(row["unknown"] for row in stats["lineages"]) == 1
    assert sum(row["resolved"] for row in stats["lineages"]) == 2
    assert stats["choice"] == "common"


def test_equal_lineage_weight_does_not_let_repeated_gain_overwhelm_loss():
    a, metadata_a = paired_fixture("fixture-a", "gain", "a-0")
    many = [a] + [paired_fixture("fixture-a", "gain", "a-" + str(i))[0] for i in range(1, 5)]
    b, metadata_b = paired_fixture("fixture-b", "loss", "b-0")
    manifest = make_development_manifest([metadata_a, metadata_b], EXPERIMENT)
    selector = update_selector(initial_selector(authored_mold()["artifact_digest"]), many + [b], manifest)
    assert selector["statistics"][0]["utility"] == 0
    assert choose_candidate(selector, a["context"]) == "common"


def test_final_manifest_and_receipts_are_rejected():
    receipts, manifest = fixture_batch([("fixture-a", "gain")])
    selector = initial_selector(authored_mold()["artifact_digest"])
    final_manifest = deepcopy(manifest)
    final_manifest["split"] = "final"
    final_manifest["manifest_digest"] = digest({k: v for k, v in final_manifest.items() if k != "manifest_digest"})
    with pytest.raises(PermissionError):
        update_selector(selector, receipts, final_manifest)
    receipts[0]["split"] = "final"
    receipts[0]["pair_receipt_sha256"] = digest({k: v for k, v in receipts[0].items() if k != "pair_receipt_sha256"})
    with pytest.raises(PermissionError):
        update_selector(selector, receipts, manifest)


def test_same_implementation_cannot_be_renamed_into_independent_support():
    _, a = paired_fixture("fixture-a")
    b = {**a, "source_lineage_id": "fixture-b", "project_id": "different-visible-project",
         "independence_id": "different-visible-independence"}
    with pytest.raises(ValueError, match="independence"):
        make_development_manifest([a, b], EXPERIMENT)


def test_forged_statistics_and_contract_or_manifest_mismatch_fail_closed():
    receipts, manifest = fixture_batch([("fixture-a", "gain"), ("fixture-b", "gain")])
    selector = update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)
    selector["statistics"][0]["utility"] = 0.75
    selector["selector_digest"] = digest({k: v for k, v in selector.items() if k != "selector_digest"})
    with pytest.raises(ValueError, match="statistics"):
        validate_selector(selector)
    wrong = initial_selector(authored_mold()["artifact_digest"], input_contract_digest=digest("wrong-contract"))
    with pytest.raises(ValueError, match="contract"):
        update_selector(wrong, receipts, manifest)
    manifest["lineages"][0]["oracle_sha256"] = digest("wrong-oracle")
    manifest["manifest_digest"] = digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
    validate_development_manifest(manifest)
    with pytest.raises(ValueError, match="Oracle identity"):
        update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)


def test_worker_projection_preserves_choices_and_excludes_private_receipt_identities():
    receipts, manifest = fixture_batch([("fixture-a", "gain"), ("fixture-b", "gain")])
    full = update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)
    runtime = public_selector(full)
    assert runtime["source_selector_digest"] == full["selector_digest"]
    assert public_selector(runtime) == runtime
    assert choose_candidate(full, receipts[0]["context"]) == choose_candidate(runtime, receipts[0]["context"]) == "learned"
    encoded = canonical(runtime)
    for field in ("evidence", "branches", "semantic_digest", "oracle_sha256", "implementation_sha256",
                  "pair_receipt_sha256", "reservation_id", "source_lineage_id", "independence_id"):
        assert '"' + field + '"' not in encoded
    for receipt in receipts:
        assert receipt["identity"]["oracle_sha256"] not in encoded
        assert receipt["identity"]["implementation_sha256"] not in encoded
        assert receipt["reservation_id"] not in encoded
        assert receipt["branches"]["common"][0]["semantic_digest"] not in encoded
    with pytest.raises(ValueError, match="complete host selector"):
        update_selector(runtime, receipts, manifest)


def test_runtime_schema_does_not_allow_smuggled_fields_or_policy_override():
    receipts, manifest = fixture_batch([("fixture-a", "gain")])
    runtime = public_selector(update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest))
    bad = deepcopy(runtime)
    bad["contexts"][0]["choice"] = "learned"
    bad["selector_digest"] = digest({k: v for k, v in bad.items() if k != "selector_digest"})
    with pytest.raises(ValueError, match="fixed selection rule"):
        validate_runtime_selector(bad)
    bad = deepcopy(runtime)
    bad["oracle_sha256"] = receipts[0]["identity"]["oracle_sha256"]
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_runtime_selector(bad)


def test_exact_zero_utility_cannot_turn_into_learned_via_floating_roundoff():
    receipts, lineages = [], []
    for lineage, gains, losses in (("fixture-a", 1, 0), ("fixture-b", 2, 0), ("fixture-c", 0, 3)):
        for index in range(10):
            label = "gain" if index < gains else "loss" if index < gains + losses else "neutral_pass"
            receipt, metadata = paired_fixture(lineage, label, "exact-zero-" + str(index))
            receipts.append(receipt)
        lineages.append(metadata)
    manifest = make_development_manifest(lineages, EXPERIMENT)
    selector = update_selector(initial_selector(authored_mold()["artifact_digest"]), receipts, manifest)
    assert selector["statistics"][0]["utility"] == 0.0
    assert choose_candidate(selector, receipts[0]["context"]) == "common"
