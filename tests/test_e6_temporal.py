"""Executable E6 temporal semantics, shared learning, selection and transfer."""
from copy import deepcopy

import pytest

from tomolab.discovery.analysis import analyze_source
from tomolab.discovery.engine import DiscoveryEngine
from tomolab.discovery.schema import canonical, digest
from tomolab.discovery.stateful import trace_spec
from tomolab.discovery.temporal import (apply_action, initial_state, normalize_temporal_evidence,
    simulate_trace, temporal_holds, validate_temporal_contract)
from tomolab.discovery.temporal_engine import TemporalEngine, validate_temporal_snapshot
from tomolab.discovery.temporal_transfer import transfer_temporal


def setup(*, renamed=False, public_ir=False):
    names = ["put", "take"] if renamed else ["insert", "remove"]
    spec = trace_spec(names, {"kind": "int", "min": -2, "max": 2}, max_steps=8,
                      name="operations" if renamed else "trace")
    spec["contract"]["invariants"] = ["state-match"]
    contract = {"schema": "tomolab-temporal-contract-v1", "disabled_action": "NO_OP",
        "state": [{"name": "occupied" if renamed else "count", "role": "size",
                   "type": {"kind": "int", "min": 0, "max": 8}, "initial": 0}],
        "actions": [
            {"name": names[0], "role": "insert", "preconditions": [],
             "effects": {"size": {"op": "add", "args": [{"var": "pre:size"}, 1]}},
             "postconditions": [], "dependencies": []},
            {"name": names[1], "role": "remove", "preconditions": [{"op": "gt", "left": {"var": "pre:size"}, "right": 0}],
             "effects": {"size": {"op": "sub", "args": [{"var": "pre:size"}, 1]}},
             "postconditions": [{"op": "lt", "left": {"var": "post:size"}, "right": {"var": "pre:size"}}],
             "dependencies": ["insert"]}],
        "invariants": [{"id": "nonnegative", "predicate": {"op": "ge", "left": {"var": "post:size"}, "right": 0}}]}
    name = spec["inputs"][0]["name"]
    points = [{name: [[names[0], 1], [names[0], 1], [names[1], 1]]},
              {name: [[names[0], 1], [names[1], 1]]},
              {name: [[names[0], 2], [names[0], 1], [names[1], 2]]},
              {name: [[names[1], 0]]}]
    ir = None
    if public_ir:
        ir = analyze_source("def implementation(trace: list[tuple[str, int]]):\n    if len(trace) > 1:\n        return 1\n    return 0\n",
                            roles={"trace": spec["inputs"][0]["role"]})
        spec["contract"]["graph_signature"] = ir["graph_signature"]
    return spec, contract, points, ir


def event(point, *, failed=True, index=2, eid="source-failure"):
    return {"kind": "FAILURE" if failed else "REFUTATION", "evidence_id": eid,
            "inputs": point, "invariant": "state-match", "category": "state_violation",
            "signature": "remove-many" if failed else "checked-clean", "first_failure_index": index if failed else None}


def engine(*, public_ir=False):
    spec, contract, points, ir = setup(public_ir=public_ir)
    return TemporalEngine(spec, contract, candidate_pool=points, pool_size=4, budget=12, public_ir=ir)


def test_public_efsm_simultaneous_effects_and_explicit_noop():
    spec, contract, points, _ = setup()
    validated = validate_temporal_contract(contract, spec)
    assert simulate_trace(points[0], spec, validated)["state"] == {"size": 1}
    noop = simulate_trace(points[-1], spec, validated)
    assert noop["valid"] and not noop["transitions"][0]["enabled"] and noop["state"] == {"size": 0}
    validated["disabled_action"] = "REJECT"
    assert not simulate_trace(points[-1], spec, validated)["valid"]
    # Assignments see one pre-state, not preceding assignments in the mapping.
    validated["state"].append({"name": "saved", "role": "saved", "type": {"kind": "int", "min": 0, "max": 8}, "initial": 0})
    validated["actions"][0]["effects"]["saved"] = {"var": "pre:size"}
    validate_temporal_contract(validated, spec)
    row = apply_action(initial_state(validated), "insert", 1, 0, None, validated, spec)
    assert row["post"] == {"size": 1, "saved": 0}


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(oracle_source="hidden"),
    lambda c: c["state"][0].update(expected_state=[0]),
    lambda c: c["actions"][0]["effects"].update(hidden={"op": "exec", "args": []}),
    lambda c: c["actions"][0]["preconditions"].append({"op": "gt", "left": {"var": "post:size"}, "right": 0}),
])
def test_contract_fails_closed_on_hidden_or_unsupported_data(mutate):
    spec, contract, _, _ = setup()
    mutate(contract)
    with pytest.raises(ValueError):
        validate_temporal_contract(contract, spec)


def test_conditional_public_effect_and_future_state_rejection():
    spec, contract, _, _ = setup()
    contract["actions"][0]["effects"]["size"] = {"op": "if", "condition": {"op": "eq", "left": {"var": "arg"}, "right": 0},
                                                "then": {"var": "pre:size"}, "else": {"op": "add", "args": [{"var": "pre:size"}, 1]}}
    validate_temporal_contract(contract, spec)
    assert simulate_trace({"trace": [["insert", 0]]}, spec, contract)["state"]["size"] == 0
    contract["actions"][0]["effects"]["size"] = {"var": "post:size"}
    with pytest.raises(ValueError, match="pre-state"):
        validate_temporal_contract(contract, spec)


def test_initial_invariant_contradiction_is_configuration_error():
    spec, contract, _, _ = setup()
    contract["state"][0]["type"]["min"] = -1
    contract["state"][0]["initial"] = -1
    with pytest.raises(ValueError, match="initial state contradicts"):
        validate_temporal_contract(contract, spec)


def test_minimal_trace_evidence_validates_first_transition_and_channels():
    spec, contract, points, _ = setup()
    assert normalize_temporal_evidence(event(points[0]), spec, contract)["first_failure_index"] == 2
    with pytest.raises(ValueError):
        normalize_temporal_evidence(event(points[0], index=3), spec, contract)
    invalid = event(points[0]); invalid["expected"] = {"size": 1}
    with pytest.raises(ValueError):
        normalize_temporal_evidence(invalid, spec, contract)


def test_native_first_lazy_state_grammar_and_preexecution_admission():
    learner = engine()
    assert isinstance(learner, DiscoveryEngine) and not learner.temporal_relations
    point = {"trace": [["insert", -2], ["remove", -2]]}
    proposal = learner.admit_native(point)
    assert not proposal["duplicate"] and proposal["reason"] == "native-stateful-registration"
    learner.observe(event(point, failed=False))
    assert not learner.temporal_relations
    before = len(learner.seen)
    assert learner.admit_native(point)["duplicate"] and len(learner.seen) == before
    learner.freeze()
    with pytest.raises(ValueError, match="frozen"):
        learner.admit_native({"trace": []})


def test_default_clean_registration_never_generates_a_fixed_pool(monkeypatch):
    import tomolab.discovery.efficient as efficient
    def forbid(*args, **kwargs):
        pytest.fail("clean native registration must not precompute a Hypothesis pool")
    monkeypatch.setattr(efficient, "generate_temporal_pool", forbid)
    spec, contract, points, _ = setup()
    learner = TemporalEngine(spec, contract, pool_size=128)
    assert learner.initial_pool == [{"trace": []}]
    learner.admit_native(points[1]); learner.observe(event(points[1], failed=False))
    snapshot = learner.freeze()
    assert snapshot["temporal_metrics"]["activation_count"] == 0
    assert snapshot["temporal_metrics"]["pool_generation_seconds"] == 0
    assert validate_temporal_snapshot(snapshot) == snapshot


def test_lazy_failure_and_prior_compile_once_and_recheck_earlier_static_evidence(monkeypatch):
    import tomolab.discovery.efficient as efficient
    calls = []
    def generated(spec, contract, **kwargs):
        calls.append(bool(kwargs.get("relations")))
        name = spec["inputs"][0]["name"]
        roles = {a["role"]: a["name"] for a in contract["actions"]}
        return [{name: [[roles["insert"], 1], [roles["insert"], 1], [roles["remove"], 1]]},
                {name: [[roles["insert"], 1], [roles["remove"], 1]]},
                {name: [[roles["insert"], 2], [roles["insert"], 1], [roles["remove"], 2]]},
                {name: [[roles["remove"], 0]]}]
    monkeypatch.setattr(efficient, "generate_temporal_pool", generated)
    spec, contract, points, ir = setup(public_ir=True)
    learner = TemporalEngine(spec, contract, public_ir=ir)
    learner.admit_native(points[1]); learner.observe(event(points[1], failed=False, eid="earlier-clean"))
    clean_snapshot = learner.snapshot()
    assert TemporalEngine.from_snapshot(clean_snapshot).snapshot() == clean_snapshot and not calls
    learner.admit_native(points[0]); learner.observe(event(points[0]))
    assert calls == [False]
    group = next(iter(learner.groups.values()))
    assert group["remaining"] & learner.temporal_relations
    assert any(learner.relations[r]["term"]["kind"] == "length" for r in group["remaining"])
    assert not any(learner.relations[r]["term"]["kind"] == "ast" for r in group["remaining"])
    frozen = learner.freeze()
    assert validate_temporal_snapshot(frozen) == frozen and calls == [False]
    target_spec, target_contract, _, _ = setup(renamed=True)
    plan = transfer_temporal(frozen, target_spec, target_contract, budget=1)
    assert plan["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert calls == [False, False]  # one full pool per qualified source/target activation
    assert validate_temporal_snapshot(plan["snapshot"]) == plan["snapshot"]
    changed = deepcopy(frozen)
    changed["activation_pool_size"] = 1
    changed["receipt"]["sha256"] = digest({k:v for k,v in changed.items() if k != "receipt"})
    with pytest.raises(ValueError):
        validate_temporal_snapshot(changed)


def test_ast_and_temporal_terms_share_real_e5_elimination_and_preserve_competitors():
    learner = engine(public_ir=True)
    first = learner.propose()
    learner.observe(event(first["inputs"]))
    group = next(iter(learner.groups.values()))
    positive_ast = {rid for rid in group["remaining"] if learner.relations[rid]["term"]["kind"] == "ast"}
    temporal_before = group["remaining"] & learner.temporal_relations
    assert positive_ast and len(temporal_before) > 1
    assert all(learner.relations[r]["term"]["action"] == "remove" for r in temporal_before)
    clean = {"trace": [["insert", 1], ["remove", 1]]}
    learner.admit_native(clean)
    learner.observe(event(clean, failed=False, eid="clean-small"))
    temporal_after = group["remaining"] & learner.temporal_relations
    assert temporal_after and len(temporal_after) < len(temporal_before)
    assert not positive_ast & group["remaining"]
    assert any(learner.relations[r]["term"]["relation_kind"] == "pre-state-boundary" for r in temporal_after)
    assert any(c["constraint_id"] in positive_ast for c in learner.contradictions)


def test_actual_failure_feedback_changes_next_query_and_selects_incremental_witness():
    failure, control = engine(), engine()
    fp, cp = failure.propose(), control.propose()
    assert fp["inputs"] == cp["inputs"]
    failure.observe(event(fp["inputs"]))
    control.observe(event(cp["inputs"], failed=False))
    guided, native = failure.propose(), control.propose()
    assert guided["inputs"] != native["inputs"]
    assert guided["reason"] == "incremental-temporal-witness"
    assert guided["solver_check"]["status"] == "SAT"
    assert guided["solver_check"]["concrete_readback"] == "MATCHED"
    assert guided["inputs"]["trace"][-1][1] == guided["solver_check"]["witness"]["argument"]
    assert failure.temporal_metrics["solver_calls"] == failure.temporal_metrics["solver_sat"] == 1
    assert failure.temporal_metrics["fresh_candidates"] > 0


def test_relations_do_not_memorize_observed_coordinates_and_snapshot_replays():
    learner = engine()
    learner.propose()
    learner.observe(event(learner.pool[0]))
    learner.propose()
    saved = learner.freeze()
    assert TemporalEngine.from_snapshot(saved).snapshot() == saved
    assert validate_temporal_snapshot(saved) == saved
    assert all(r["term"]["kind"] == "temporal" for rid, r in saved["relations"].items() if rid.startswith("TEMP-"))
    altered = deepcopy(saved)
    altered["groups"][next(iter(altered["groups"]))]["remaining"] = []
    altered["receipt"]["sha256"] = digest({k: v for k, v in altered.items() if k != "receipt"})
    with pytest.raises(ValueError, match="derived"):
        validate_temporal_snapshot(altered)
    with pytest.raises(ValueError, match="frozen"):
        learner.observe(event(learner.pool[0], eid="late-feedback"))


def test_all_four_transfer_decisions_and_renamed_actual_trace_plan():
    source = engine(); proposal = source.propose(); source.observe(event(proposal["inputs"]))
    frozen = source.freeze()
    target_spec, target_contract, points, _ = setup(renamed=True)
    plan = transfer_temporal(frozen, target_spec, target_contract, budget=3, pool_size=4, candidate_pool=points)
    assert plan["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert plan["gate"]["mapping"]["insert"] == "put"
    assert plan["gate"]["mapping"]["count"] == "occupied"
    assert plan["final_feedback_allowed"] is False and plan["snapshot"]["frozen"]
    assert any(p["temporal_guidance"] == "TEMPORAL_DISAGREEMENT" for p in plan["candidates"])
    assert TemporalEngine.from_snapshot(plan["snapshot"]).snapshot() == plan["snapshot"]
    # Different internal implementations expose the same declared size role.
    def check(point):
        expected, actual = [], {"occupied": 0}
        for action, value in point["operations"]:
            if action == "put":
                expected.append(value); actual["occupied"] += 1
            elif expected:
                expected.pop(); actual["occupied"] = 0
        return len(expected) != actual["occupied"]
    assert any(check(p["inputs"]) for p in plan["candidates"])
    changed = deepcopy(target_contract); changed["actions"][0]["effects"]["size"]["args"][1] = 2
    incompatible = transfer_temporal(frozen, target_spec, changed, budget=1, candidate_pool=points[:1])
    assert incompatible["gate"]["status"] == "NOT_APPLICABLE"
    empty = engine().freeze()
    assert transfer_temporal(empty, target_spec, target_contract, budget=1, candidate_pool=points)["gate"]["status"] == "UNKNOWN"
    clean = event(points[0], failed=False, eid="checked-clean-target")
    contradicted = transfer_temporal(frozen, target_spec, target_contract, budget=1, candidate_pool=points, target_evidence=[clean])
    assert contradicted["gate"]["status"] == "CONTRADICTED"
    assert contradicted["gate"]["failure_recurrence"] == "UNKNOWN"


def test_transfer_requires_frozen_source_and_rejects_wrong_mapping():
    source = engine(); target_spec, contract, points, _ = setup(renamed=True)
    with pytest.raises(ValueError, match="frozen"):
        transfer_temporal(source.snapshot(), target_spec, contract, candidate_pool=points)
    source.propose(); source.observe(event(source.pool[0])); saved = source.freeze()
    plan = transfer_temporal(saved, target_spec, contract, budget=1, candidate_pool=points, mapping={"remove": "put"})
    assert plan["gate"]["status"] == "NOT_APPLICABLE"


def test_public_development_models_agree_with_reviewed_temporal_contracts():
    from benchmarks.e6_public_cases import CASES
    for case in CASES:
        if case["kind"] != "stateful":
            continue
        spec = trace_spec([a["name"] for a in case["temporal_contract"]["actions"]], case["argument_type"], max_steps=case["max_steps"])
        contract = validate_temporal_contract(case["temporal_contract"], spec)
        state, prior = initial_state(contract), None
        for index, action in enumerate(case["temporal_contract"]["actions"] * 2):
            try:
                row = apply_action(state, action["name"], 1, index, prior, contract, spec)
            except ValueError:
                continue
            next_state = case["model_step"](state, action["name"], 1)
            assert row["post"] == next_state, case["case_id"]
            state, prior = row["post"], row


def test_empty_native_expansion_is_not_repeated_after_snapshot(monkeypatch):
    import tomolab.discovery.efficient as efficient
    calls = []
    monkeypatch.setattr(efficient, "generate_temporal_pool", lambda *args, **kwargs: calls.append(kwargs) or [])
    spec, contract, _, _ = setup()
    learner = TemporalEngine(spec, contract, pool_size=4)
    assert learner.propose()["inputs"] == {"trace": []}
    assert learner.propose() is None
    assert len(calls) == 1
    saved = learner.freeze()
    assert saved["native_expanded"] is True and saved["pool_events"] == []
    restored = TemporalEngine.from_snapshot(saved)
    assert restored.propose() is None and len(calls) == 1


def test_activation_reuses_an_already_expanded_native_pool(monkeypatch):
    import tomolab.discovery.efficient as efficient
    spec, contract, points, _ = setup()
    calls = []
    monkeypatch.setattr(efficient, "generate_temporal_pool", lambda *args, **kwargs: calls.append(kwargs) or points)
    learner = TemporalEngine(spec, contract, pool_size=4)
    learner.propose()  # empty cold seed
    proposal = learner.propose()  # one requested native expansion
    assert len(calls) == 1
    learner.observe(event(proposal["inputs"]))
    assert len(calls) == 1 and learner.activation_pool_size == len(learner.pool)
    saved = learner.freeze()
    assert TemporalEngine.from_snapshot(saved).snapshot() == saved and len(calls) == 1


def test_qualified_cutoff_prevents_future_points_from_changing_static_grammar(monkeypatch):
    import tomolab.discovery.efficient as efficient
    spec, contract, points, _ = setup()
    monkeypatch.setattr(efficient, "generate_temporal_pool", lambda *args, **kwargs: points)
    learner = TemporalEngine(spec, contract, pool_size=4)
    learner.admit_native(points[1]); learner.observe(event(points[1], failed=False, eid="early-clean"))
    learner.admit_native(points[0]); learner.observe(event(points[0]))
    cutoff = learner.activation_pool_size
    static_ids = set(learner.relations) - learner.temporal_relations
    learner.admit_native({"trace": [["insert", 2]] * 8})
    saved = learner.freeze()
    restored = TemporalEngine.from_snapshot(saved)
    assert restored.activation_pool_size == cutoff < len(restored.pool)
    assert set(restored.relations) - restored.temporal_relations == static_ids
    assert restored.snapshot() == saved
    changed = deepcopy(saved)
    changed["activation_pool_size"] = len(changed["pool"])
    changed["receipt"]["sha256"] = digest({k:v for k,v in changed.items() if k != "receipt"})
    with pytest.raises(ValueError, match="derived"):
        TemporalEngine.from_snapshot(changed)


def test_sat_query_skips_redundant_guided_hypothesis_batch(monkeypatch):
    import tomolab.discovery.efficient as efficient
    learner = engine()
    first = learner.propose()
    learner.observe(event(first["inputs"]))
    monkeypatch.setattr(efficient, "generate_temporal_pool", lambda *args, **kwargs: pytest.fail("SAT witness already supplies novel information"))
    query = learner.propose()
    assert query["reason"] == "incremental-temporal-witness"
    assert query["solver_check"]["concrete_readback"] == "MATCHED"
    assert learner.temporal_metrics["guided_rounds"] == 0


def test_solver_version_cache_restores_actual_version_after_new_feedback():
    learner = engine()
    first = learner.propose(); learner.observe(event(first["inputs"]))
    next_query = learner.propose()
    learner.observe(event(next_query["inputs"], failed=False, eid="new-counterevidence"))
    saved = learner.snapshot()
    assert saved["solver_version"] < saved["version"]
    restored = TemporalEngine.from_snapshot(saved)
    assert restored.snapshot() == saved
    assert learner.propose()["inputs"] == restored.propose()["inputs"]


@pytest.mark.parametrize("field,value", [
    ("native_expanded", 1), ("native_expanded", False),
    ("activation_pool_size", None), ("guidance_version", 9999), ("solver_version", 9999),
])
def test_lazy_and_cache_metadata_tampering_is_rejected(field, value):
    spec, contract, points, _ = setup()
    learner = TemporalEngine(spec, contract, pool_size=4)
    learner.admit_native(points[0]); learner.observe(event(points[0]))
    saved = learner.freeze()
    saved[field] = value
    saved["receipt"]["sha256"] = digest({k:v for k,v in saved.items() if k != "receipt"})
    with pytest.raises(ValueError):
        TemporalEngine.from_snapshot(saved)
