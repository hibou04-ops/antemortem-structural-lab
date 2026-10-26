"""Executable integration contracts, not a performance superiority benchmark."""
from copy import deepcopy
import importlib.util

import pytest

from tomolab.mold import MoldEngine, default_spec, normalize_evidence, solve, transfer
from tomolab.mold.relations import holds, relation_id, universe, bounds
from tomolab.mold.schema import digest


def evidence(engine, proposal, kind="FAILURE", event_id=None):
    return {"kind": kind, "evidence_id": event_id or f"ev{engine.version}",
            "inputs": proposal["inputs"], "invariant": engine.spec["invariant"],
            "signature": "integer-mismatch"}


def learned(seed=7):
    engine = MoldEngine(default_spec(low=-4, high=4), seed=seed)
    engine.observe(evidence(engine, engine.propose()))
    return engine


def renamed(spec):
    spec = deepcopy(spec)
    spec["task_id"] = "renamed-target"
    spec["variables"][0]["name"] = "a"
    spec["variables"][1]["name"] = "b"
    return spec


def relation(family="sum", operator="eq", value=0):
    return {"family": family, "operator": operator, "value": value, "type": "int-pair-predicate"}


def test_evidence_eliminates_inconsistent_hypotheses_but_preserves_competition():
    engine = learned()
    snapshot = engine.snapshot()
    assert 1 < len(snapshot["version_space"]) < len(universe(bounds(engine.spec))[1])
    point = tuple(snapshot["evidence"][0]["inputs"][n] for n in ("x", "y"))
    assert all(holds(h["relation"], point) for h in snapshot["version_space"])
    assert snapshot["contradictions"]
    assert all(c["confidence"]["status"] == "UNCONFIRMED_HYPOTHESIS" for c in snapshot["constraints"])


def test_active_query_is_an_actual_disagreement_and_refutation_prunes_it():
    engine = learned()
    before = engine.snapshot()
    query = engine.propose()
    assert query["reason"] == "active-disagreement"
    mapping = {h["constraint_id"]: h["relation"] for h in before["version_space"]}
    point = tuple(query["inputs"][n] for n in ("x", "y"))
    a, b = [mapping[rid] for rid in query["hypothesis_ids"]]
    assert holds(a, point) != holds(b, point)
    assert query["solver_check"]["witness"] == list(point)
    result = engine.observe(evidence(engine, query, "REFUTATION"))
    assert result["eliminated"] > 0
    assert all(not holds(h["relation"], point) for h in engine.snapshot()["version_space"])


def test_diversity_keeps_multiple_families_and_a_fixed_probe_quota():
    engine = learned()
    snap = engine.snapshot()
    assert len({item["descriptor"] for item in snap["archive"]}) >= 5
    engine.propose()
    engine.propose()
    assert engine.propose()["reason"] == "diversity"


def test_conflicting_evidence_is_retained_and_does_not_invent_a_model():
    engine = learned()
    proposal = {"inputs": engine.snapshot()["evidence"][0]["inputs"]}
    engine.observe(evidence(engine, proposal, "REFUTATION"))
    snap = engine.snapshot()
    assert snap["status"] == "INCONSISTENT_EVIDENCE"
    assert not snap["version_space"] and not snap["constraints"]
    assert len(snap["evidence"]) == 2 and snap["contradictions"]


def test_out_of_grammar_does_not_promote_a_bad_hypothesis():
    engine = MoldEngine(default_spec(low=-1, high=1))
    for _ in range(9):
        proposal = engine.propose()
        # Deliberately outside the seven single-relation families.
        x, y = proposal["inputs"]["x"], proposal["inputs"]["y"]
        failure = (x, y) in {(-1, -1), (0, 1)}
        engine.observe(evidence(engine, proposal, "FAILURE" if failure else "REFUTATION"))
    assert engine.status == "OUT_OF_GRAMMAR"
    assert engine.snapshot()["constraints"] == []


def test_frozen_snapshot_rejects_feedback_but_supports_deterministic_queries():
    engine = learned()
    frozen = engine.freeze()
    original = deepcopy(frozen)
    a, b = MoldEngine.from_snapshot(frozen), MoldEngine.from_snapshot(frozen)
    assert [a.propose() for _ in range(12)] == [b.propose() for _ in range(12)]
    with pytest.raises(ValueError, match="frozen"):
        a.observe(evidence(a, a.propose()))
    assert frozen == original


def test_structural_rename_transfer_is_allowed_without_asserting_recurrence():
    engine = learned()
    frozen = engine.freeze()
    result = transfer(frozen, renamed(engine.spec), mapping={"x": "a", "y": "b"}, budget=12)
    assert result["gate"]["status"] == "APPLICABLE_FOR_PROBING"
    assert result["gate"]["failure_recurrence"] == "UNKNOWN"
    assert result["snapshot"]["evidence"] == []
    assert result["snapshot"]["prior"]
    assert all(set(p["inputs"]) == {"a", "b"} for p in result["candidates"])
    # Retains the original proof-of-origin hash without inventing target evidence.
    assert result["gate"]["source_snapshot_sha256"] == frozen["receipt"]["sha256"]
    MoldEngine.from_snapshot(result["snapshot"])


@pytest.mark.parametrize("field,value", [("operation", "integer-subtraction"), ("invariant", "other-invariant"),
                                         ("semantic_contract", "different-meaning")])
def test_incompatible_contract_transfer_is_unknown_and_uniform(field, value):
    engine = learned()
    target = renamed(engine.spec)
    target[field] = value
    result = transfer(engine.freeze(), target, seed=31, budget=12)
    baseline = MoldEngine(target, strategy="uniform", seed=31)
    assert result["gate"]["status"] == "UNKNOWN"
    assert [p["inputs"] for p in result["candidates"]] == [baseline.propose()["inputs"] for _ in range(12)]


def test_wrong_role_mapping_and_domain_extrapolation_are_rejected():
    engine = learned()
    frozen = engine.freeze()
    target = renamed(engine.spec)
    assert transfer(frozen, target, {"x": "b", "y": "a"})["gate"]["status"] == "UNKNOWN"
    target["variables"][0]["high"] = 5
    assert transfer(frozen, target)["gate"]["status"] == "UNKNOWN"


def test_transfer_does_more_than_reproduce_uniform_when_applicable():
    engine = learned()
    target = renamed(engine.spec)
    result = transfer(engine.freeze(), target, seed=41, budget=16)
    baseline = MoldEngine(target, strategy="uniform", seed=41)
    assert [p["inputs"] for p in result["candidates"]] != [baseline.propose()["inputs"] for _ in range(16)]


def test_snapshot_detects_tampering_even_if_digest_is_recomputed():
    snap = learned().snapshot()
    snap["version_space"] = []
    snap["receipt"]["sha256"] = digest({k: v for k, v in snap.items() if k != "receipt"})
    with pytest.raises(ValueError, match="derived"):
        MoldEngine.from_snapshot(snap)


def test_snapshot_preserves_exact_stream_across_json_roundtrip():
    import json
    engine = learned()
    engine.propose()
    restored = MoldEngine.from_snapshot(json.loads(json.dumps(engine.snapshot())))
    assert [engine.propose() for _ in range(10)] == [restored.propose() for _ in range(10)]


def test_no_feedback_for_unqueried_point_or_reused_id():
    engine = learned()
    snap = engine.snapshot()
    with pytest.raises(ValueError, match="unique"):
        engine.observe(snap["evidence"][0])
    record = deepcopy(snap["evidence"][0])
    record["evidence_id"] = "unqueried"
    record["inputs"] = {"x": -4, "y": -4}
    with pytest.raises(ValueError, match="proposed"):
        engine.observe(record)


@pytest.mark.parametrize("mutation", ["bool", "score", "source", "bad-signature", "other-invariant"])
def test_protocol_rejects_invalid_or_excess_information(mutation):
    engine = learned()
    record = evidence(engine, engine.propose())
    if mutation == "bool":
        record["inputs"]["x"] = True
    elif mutation == "score":
        record["score"] = 1
    elif mutation == "source":
        record["source"] = "def hidden(): pass"
    elif mutation == "bad-signature":
        record["signature"] = "opaque-success-praise"
    else:
        record["invariant"] = "unrelated"
    with pytest.raises(ValueError):
        normalize_evidence(record, engine.spec)


def test_solver_satisfiability_and_disagreement_are_bounded():
    spec = default_spec(low=-2, high=2)
    a, b = relation(), relation("difference")
    found = solve(spec, a, b)
    assert found["status"] == "SAT"
    assert holds(a, found["witness"]) != holds(b, found["witness"])
    assert solve(spec, relation(value=100))["status"] == "UNSAT"
    assert solve(spec, a, a)["status"] == "UNSAT"


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="optional Z3 extra not installed")
def test_z3_agrees_with_independent_bounded_enumeration_and_is_used_for_queries():
    spec = default_spec(low=-2, high=2)
    relations = [relation(), relation("difference", "ge", 1), relation("abs_difference", "le", 2),
                 relation("abs_sum", "eq", 3), relation("sum_mod3", "eq", 1), relation(value=100)]
    for a in relations:
        assert solve(spec, a, backend="z3")["status"] == solve(spec, a)["status"]
        for b in relations:
            z3 = solve(spec, a, b, backend="z3")
            assert z3["status"] == solve(spec, a, b)["status"]
            if z3["witness"]:
                assert holds(a, z3["witness"]) != holds(b, z3["witness"])
    engine = MoldEngine(spec, solver="z3")
    engine.observe(evidence(engine, engine.propose()))
    query = engine.propose()
    assert query["solver_check"]["backend"] == "z3"


def test_bounds_and_unique_exhaustion_enforce_cost_limit():
    engine = MoldEngine(default_spec(low=0, high=2), strategy="uniform")
    points = [tuple(engine.propose()["inputs"].values()) for _ in range(9)]
    assert len(set(points)) == 9
    with pytest.raises(ValueError, match="exhausted"):
        engine.propose()
    with pytest.raises(ValueError):
        default_spec(low=0, high=65)
    with pytest.raises(ValueError):
        default_spec(low=1000000, high=1000001)


def test_extreme_supported_values_roundtrip_and_role_order_is_irrelevant():
    spec = default_spec(low=999998, high=1000000)
    spec["variables"].reverse()
    engine = MoldEngine(spec)
    engine.observe(evidence(engine, engine.propose()))
    assert MoldEngine.from_snapshot(engine.freeze()).snapshot() == engine.snapshot()


def test_requested_z3_backend_fails_at_initialization_when_dependency_is_missing(monkeypatch):
    import builtins
    original_import = builtins.__import__

    def missing_z3(name, *args, **kwargs):
        if name == "z3":
            raise ImportError("simulated environment without optional solver")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_z3)
    with pytest.raises(ValueError, match="requires"):
        MoldEngine(default_spec(), solver="z3")
    # Dependency-free enumeration remains available without weakening a Z3 request.
    assert MoldEngine(default_spec(low=-1, high=1)).propose()["sequence"] == 1
