from copy import deepcopy

import pytest

from tomolab.discovery.efficient import EvidenceCache, HypothesisFirstPolicy, IncrementalIntSolver, generate_temporal_pool
from tomolab.discovery.stateful import trace_spec
from tomolab.discovery.temporal import simulate_trace


def scalar_spec():
    return {"schema":"tomolab-discovery-spec-v1","task_id":"efficient-integer",
            "inputs":[{"name":"value","role":"operand","type":{"kind":"int","min":-4,"max":4}}],
            "contract":{"id":"integer-public","operation":"identity","preconditions":[],
                        "invariants":["reference"],"state_model":"stateless","graph_signature":"UNKNOWN"}}


def stack_contract():
    spec = trace_spec(["push", "pop"], {"kind":"int","min":-1,"max":1}, max_steps=6)
    contract = {"schema":"tomolab-temporal-contract-v1",
        "state":[{"name":"count","role":"size","type":{"kind":"int","min":0,"max":6},"initial":0}],
        "actions":[
            {"name":"push","role":"insert","preconditions":[{"op":"lt","left":{"var":"pre:size"},"right":6}],
             "effects":{"size":{"op":"add","args":[{"var":"pre:size"},1]}},"postconditions":[],"dependencies":[]},
            {"name":"pop","role":"remove","preconditions":[{"op":"gt","left":{"var":"pre:size"},"right":0}],
             "effects":{"size":{"op":"sub","args":[{"var":"pre:size"},1]}},"postconditions":[],"dependencies":["insert"]}],
        "invariants":[{"id":"nonnegative","predicate":{"op":"ge","left":{"var":"post:size"},"right":0}}]}
    return spec, contract


def test_cache_key_uses_actual_input_spec_and_version_and_does_not_alias():
    spec = scalar_spec()
    cache = EvidenceCache(spec)
    cache.put({"value":0}, {"failed":True})
    assert cache.get({"value":1}) is None
    value = cache.get({"value":0})
    value["failed"] = False
    assert cache.get({"value":0}) == {"failed":True}
    changed = deepcopy(spec)
    changed["contract"]["id"] = "different-contract"
    assert cache.key({"value":0}) != EvidenceCache(changed).key({"value":0})
    before = cache.key({"value":0})
    cache.set_version(1)
    assert cache.get({"value":0}) is None and cache.key({"value":0}) != before


def test_unqualified_or_inapplicable_guidance_keeps_native_path():
    policy = HypothesisFirstPolicy(scalar_spec(), batch_size=3)
    first = policy.candidates(guidance={"qualified":False,"predicates":[]})
    assert first["source"] == "NATIVE_HYPOTHESIS" and first["candidates"]
    second = policy.candidates(guidance={"qualified":True,"applicability":"UNKNOWN","predicates":[],"evidence_ids":["dev-1"]})
    assert second["metrics"]["guided_rounds"] == 0
    assert not {str(point) for point in first["candidates"]} & {str(point) for point in second["candidates"]}


def test_qualified_disagreement_changes_actual_candidate_selection():
    guidance = {"qualified":True,"applicability":"APPLICABLE_FOR_PROBING","evidence_ids":["dev-1"],
                "predicates":[{"op":"ge","left":{"var":"operand"},"right":0},
                              {"op":"le","left":{"var":"operand"},"right":0}]}
    result = HypothesisFirstPolicy(scalar_spec()).candidates(size=3, guidance=guidance)
    assert result["source"] == "QUALIFIED_DISAGREEMENT"
    assert all(point["value"] != 0 for point in result["candidates"])


def test_incremental_solver_scopes_queries_and_reuses_context_and_cache():
    solver = IncrementalIntSolver(scalar_spec())
    positive = {"op":"gt","left":{"var":"operand"},"right":0}
    negative = {"op":"lt","left":{"var":"operand"},"right":0}
    assert solver.solve([positive, negative])["status"] == "UNSAT"
    context = solver.solver
    first = solver.solve([positive])
    assert first["status"] == "SAT" and first["witness"]["value"] > 0
    assert solver.solve([positive]) == first
    assert solver.metrics["cache_hits"] == 1 and solver.solver is context
    other = solver.solve([positive], excluded=[first["witness"]])
    assert other["witness"] != first["witness"]
    solver.solve([positive], version=1)
    assert solver.metrics["solver_calls"] == 4
    assert solver.metrics["pushes"] == solver.metrics["pops"] == 4


def test_incremental_solver_abstains_for_float_and_nonlinearity():
    spec = scalar_spec()
    spec["inputs"][0]["type"]["kind"] = "float"
    assert IncrementalIntSolver(spec).solve([])["status"] == "UNKNOWN"
    square = {"op":"gt","left":{"op":"mul","args":[{"var":"operand"},{"var":"operand"}]},"right":0}
    assert IncrementalIntSolver(scalar_spec()).solve([square])["status"] == "UNKNOWN"


def test_temporal_pool_native_composite_preserves_preconditions_and_reproducibility():
    spec, contract = stack_contract()
    first = generate_temporal_pool(spec, contract, seed=11, size=16)
    assert first == generate_temporal_pool(spec, contract, seed=11, size=16)
    assert first and all(simulate_trace(point, spec, contract)["valid"] for point in first)


def test_temporal_pool_abstains_if_minimum_length_cannot_be_satisfied():
    spec, contract = stack_contract()
    spec["inputs"][0]["type"]["min_size"] = 2
    contract["state"][0]["type"]["max"] = 0
    assert generate_temporal_pool(spec, contract, size=2) == []
