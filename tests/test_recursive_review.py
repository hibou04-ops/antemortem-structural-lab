"""Independent adversarial checks over authored local paired observations.

These fixtures test integrity and behavior; their lineage labels are not
independent real-project evidence or a utility evaluation.
"""
from copy import deepcopy

import pytest

from tomolab.discovery.online_engine import OnlinePolicy
from tomolab.discovery.online_learning import learn_mold
from tomolab.discovery.online_observe import inspect_target
from tomolab.discovery.online_schema import input_identity
from tomolab.discovery.recursive_observe import (
    execute_pairs, make_diagnostics, new_trace, observe_proposal,
    validate_pair_receipt, validate_reservation, validate_trace,
)
from tomolab.discovery.schema import digest


CONTRACT = dict(kind="sequence_int", low=-8, high=8, min_size=0, max_size=4)
STRUCTURE = inspect_target(lambda point: point, CONTRACT, mode="black_box")


def _fixture():
    mold = learn_mold([
        dict(input=point, status=status, contract=CONTRACT,
             source_identity="authored-independent-review-fixture")
        for point, status in [([1, 2], "PASS"), ([1, 1], "FAILURE")]
    ], operator_grammar=["constantize"])
    identity = {name: digest(name) for name in (
        "implementation_sha256", "oracle_sha256", "environment_sha256",
        "reset_adapter_sha256")}
    identity["purity_review_id"] = "authored-pure-fixture"
    config = make_diagnostics(mold,
        experiment_contract_sha256=digest("authored-review-contract"),
        source_lineage_id="authored-review-lineage", project_id="authored-project",
        mechanism_id="authored-mechanism", run_id="authored-review-run", identity=identity)
    before = OnlinePolicy(CONTRACT, method="C", seed=7, budget=100, structure=STRUCTURE)
    before.receive([1, 2], dict(status="PASS", input_digest=input_identity([1, 2]),
        coverage=[], branch_distance=None, exception_type=None,
        exception_location=None, contract_checked=digest(CONTRACT)))
    before.attempts = 2
    actual = deepcopy(before).propose([2, 3])
    trace = new_trace(config["public"])
    observe_proposal(before, [2, 3], actual, config=config["public"], trace=trace,
        seed=7, actual_calls_before=0, shadow_rule_state=None)
    assert len(trace["reservations"]) == 1
    host = [dict(input_digest=input_identity(actual[0]), phase=actual[1], target_calls=1)]
    validate_trace(trace, config=config["public"], host_rows=host)
    return config, before, actual, trace, host


def _pair():
    config, _, _, trace, _ = _fixture()
    calls = dict(target=0, oracle=0, reset=0)
    def target(point):
        calls["target"] += 1
        return int(point == [1, 1])
    def oracle(point):
        calls["oracle"] += 1
        return 0
    def reset():
        calls["reset"] += 1
        return True
    result = execute_pairs(trace, config=config["public"], identity=config["identity"],
        target=target, oracle=oracle, contract=CONTRACT, structure=STRUCTURE, reset=reset)
    return result["receipts"][0], calls


def _rehash(value, field):
    value[field] = digest({key: item for key, item in value.items() if key != field})
    return value


def test_shadow_keeps_actual_policy_state_and_binds_distinct_same_anchor_candidates():
    config, before, actual, trace, _ = _fixture()
    original = before.state_digest()
    repeated = new_trace(config["public"])
    observe_proposal(before, [2, 3], actual, config=config["public"], trace=repeated,
        seed=7, actual_calls_before=0, shadow_rule_state=None)
    assert before.state_digest() == original
    reservation = trace["reservations"][0]
    assert reservation["native_input"] == [2, 3]
    assert reservation["anchor_input"] == [1, 2]
    assert reservation["common_input"] == [-1, -2]
    assert reservation["learned_input"] == [1, 1]
    # Measured instrumentation time varies; proposals, lookup counts and all
    # candidate/state identities must remain deterministic.
    def deterministic(value):
        captured = deepcopy(value)
        for name in ("snapshot_seconds", "shadow_seconds"):
            assert captured["cost"][name] >= 0
            del captured["cost"][name]
        return captured
    assert deterministic(repeated) == deterministic(trace)


def test_independent_pair_counter_matches_six_actual_target_oracle_and_reset_calls():
    receipt, calls = _pair()
    assert calls == dict(target=6, oracle=6, reset=6)
    assert receipt["label"] == "gain"
    assert receipt["cost"]["target_calls"] == receipt["cost"]["oracle_calls"] == 6
    assert receipt["cost"]["reset_calls"] == 6
    validate_pair_receipt(receipt)


def test_missing_reset_is_unknown_without_fabricated_calls():
    config, _, _, trace, _ = _fixture()
    result = execute_pairs(trace, config=config["public"], identity=config["identity"],
        target=lambda _point: pytest.fail("Target must not execute without reviewed reset"),
        oracle=lambda _point: pytest.fail("Oracle must not execute without reviewed reset"),
        contract=CONTRACT, structure=STRUCTURE, reset=None)
    assert result["status"] == "HOLD_MEASUREMENT"
    assert result["receipts"][0]["label"] == "UNKNOWN"
    assert result["cost"]["target_calls"] == result["cost"]["oracle_calls"] == 0


@pytest.mark.parametrize("field,value", [
    ("slots", [dict(semantic_digest="unreviewed-private-field")]),
    ("unknown_reasons", [dict(unbounded="unexpected object")]),
    ("limitations", dict(unbounded="unexpected object")),
])
def test_completion_nested_trace_fields_are_strict(field, value):
    config, _, _, trace, host = _fixture()
    trace[field] = value
    with pytest.raises((TypeError, ValueError)):
        validate_trace(trace, config=config["public"], host_rows=host)


def test_rehashed_reservation_with_noninteger_seed_is_rejected():
    config, _, _, trace, _ = _fixture()
    reservation = deepcopy(trace["reservations"][0])
    reservation["seed"] = "wrong-seed-type"
    _rehash(reservation, "reservation_id")
    with pytest.raises((TypeError, ValueError)):
        validate_reservation(reservation, config=config["public"])


@pytest.mark.parametrize("field,value", [
    ("observation_id", {"nested": "unsupported"}),
    ("error_type", ["not a bounded type name"]),
    ("repeat", False),
    ("reset_success", 1),
])
def test_rehashed_host_repetition_type_confusion_is_rejected(field, value):
    receipt, _ = _pair()
    receipt["branches"]["common"][0][field] = value
    if field == "reset_success":
        receipt["label"] = "UNKNOWN"
        receipt["unknown_reasons"] = ["TYPE_CONFUSION_PROBE"]
    _rehash(receipt, "pair_receipt_sha256")
    with pytest.raises((TypeError, ValueError)):
        validate_pair_receipt(receipt)


def test_trace_cannot_bind_reservation_to_another_executed_candidate():
    config, _, _, trace, host = _fixture()
    host[0]["input_digest"] = input_identity([8])
    with pytest.raises(ValueError):
        validate_trace(trace, config=config["public"], host_rows=host)


def _review_generation():
    from tomolab.discovery.recursive_policy import (
        initial_selector, make_development_manifest, update_selector,
    )
    from tomolab.discovery.recursive_store import make_generation
    receipt, _ = _pair()
    manifest = make_development_manifest([dict(
        source_lineage_id=receipt["source_lineage_id"], project_id=receipt["project_id"],
        mechanism_id=receipt["mechanism_id"],
        implementation_sha256=receipt["identity"]["implementation_sha256"],
        oracle_sha256=receipt["identity"]["oracle_sha256"],
        input_contract_sha256=receipt["input_contract_sha256"],
        independence_id="authored-review-unit", review_id="authored-review")],
        receipt["experiment_contract_sha256"])
    selector = initial_selector(receipt["mold_digest"], input_contract_digest=digest(CONTRACT))
    parent = make_generation("review-G0", selector)
    updated = update_selector(selector, [receipt], manifest)
    return parent, updated, receipt, manifest


def test_generation_requires_preserved_raw_receipts_for_new_summary_evidence():
    from tomolab.discovery.recursive_store import make_generation
    parent, selector, _, manifest = _review_generation()
    with pytest.raises(ValueError):
        make_generation("review-G1", selector, parent=parent, development_manifest=manifest)


def test_rehashed_summary_label_is_checked_against_preserved_actual_pair():
    from tomolab.discovery.recursive_store import make_generation
    parent, selector, receipt, manifest = _review_generation()
    selector["evidence"][0]["label"] = "loss"
    stat = selector["statistics"][0]
    stat["lineages"][0].update(gain=0, loss=1)
    stat["utility"] = -1.0
    _rehash(selector, "selector_digest")
    with pytest.raises(ValueError, match="receipt.*summary|summary.*receipt"):
        make_generation("review-G1", selector, parent=parent,
            development_manifest=manifest, paired_receipts=[receipt])


def test_generation_manifest_cannot_drop_the_actual_receipt_lineage():
    from tomolab.discovery.recursive_store import make_generation, validate_generation
    parent, selector, receipt, manifest = _review_generation()
    generation = make_generation("review-G1", selector, parent=parent,
        development_manifest=manifest, paired_receipts=[receipt])
    generation["consumed_development_manifest"]["lineages"][0]["source_lineage_id"] = "unrelated-lineage"
    manifest = _rehash(generation["consumed_development_manifest"], "manifest_digest")
    generation["selector"]["consumed_manifest_digests"] = [manifest["manifest_digest"]]
    generation["selector"]["evidence"][0]["manifest_digest"] = manifest["manifest_digest"]
    generation["consumed_paired_receipts"][0]["manifest_digest"] = manifest["manifest_digest"]
    _rehash(generation["selector"], "selector_digest")
    _rehash(generation, "sha256")
    with pytest.raises(ValueError, match="lineage manifest"):
        validate_generation(generation)


def test_generation_receipt_destination_failure_precedes_any_target_call(tmp_path):
    from tomolab.discovery.recursive_api import create_generation, run_generation
    from tomolab.recursive_demo import CONTRACT as DEMO_CONTRACT, fixture_mold
    mold = fixture_mold()
    store = tmp_path / "generations.jsonl"
    create_generation(store, mold, DEMO_CONTRACT)
    calls = []
    def must_not_execute(point):
        calls.append(point)
        return point
    with pytest.raises((FileNotFoundError, ValueError)):
        run_generation(store, mold, must_not_execute, must_not_execute, DEMO_CONTRACT,
            allow_local_execution=True, execution_id="invalid-destination",
            output=tmp_path / "missing-parent" / "execution.json",
            budget=6, shrink_budget=0, mode="black_box")
    assert calls == []


def test_direct_policy_honors_explicit_selector_input_contract_binding():
    from tomolab.discovery.recursive_policy import initial_selector
    config, _, _, _, _ = _fixture()
    mold = config["public"]["mold"]
    selector = initial_selector(mold["artifact_digest"], input_contract_digest=digest(CONTRACT))
    with pytest.raises(ValueError, match="contract"):
        OnlinePolicy(dict(CONTRACT, high=7), method="D", seed=7, budget=100,
            mold=mold, selector=selector)


def test_real_worker_receives_selector_projection_without_private_evidence(monkeypatch):
    from tomolab.discovery.online_boundary import OnlineBoundary
    from tomolab.discovery.online_engine import run_online
    _, selector, _, _ = _review_generation()
    config, _, _, _, _ = _fixture()
    captures = []
    original = OnlineBoundary.run
    def capture(self, configuration, execute):
        captures.append(deepcopy(configuration))
        return original(self, configuration, execute)
    monkeypatch.setattr(OnlineBoundary, "run", capture)
    result = run_online(lambda point: point, lambda point: point, CONTRACT,
        method="D", mold=config["public"]["mold"], selector=selector,
        budget=6, shrink_budget=0, max_seconds=10, mode="black_box")
    assert result["status"] == "COMPLETE"
    assert len(captures) == 1
    payload = captures[0]["selector"]
    assert payload["schema"] == "tomolab-binary-selector-runtime-v1"
    assert payload["source_selector_digest"] == selector["selector_digest"]
    def fields(value):
        if isinstance(value, dict):
            return set(value).union(*(fields(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(fields(item) for item in value))
        return set()
    assert not fields(payload) & {
        "evidence", "identity", "implementation_sha256", "oracle_sha256",
        "semantic_digest", "pair_receipt_sha256", "reservation_id", "source_lineage_id",
    }


def test_shadow_rng_is_preserved_separately_and_replayed_for_rule_selection():
    import random
    config, before, actual, _, _ = _fixture()
    trace = new_trace(config["public"])
    supplied = random.Random(987654).getstate()
    observe_proposal(before, [2, 3], actual, config=config["public"], trace=trace,
        seed=7, actual_calls_before=0, shadow_rule_state=supplied)
    reservation = trace["reservations"][0]
    assert digest(reservation["shadow_rule_rng_before"]) == digest(supplied)
    assert digest(reservation["shadow_rule_rng_before"]) != digest(reservation["state"]["rule_rng"])
    validate_reservation(reservation, config=config["public"])
    reservation["shadow_rule_rng_after"] = reservation["shadow_rule_rng_before"]
    _rehash(reservation, "reservation_id")
    with pytest.raises(ValueError, match="shadow|rule|RNG|rng"):
        validate_reservation(reservation, config=config["public"])
