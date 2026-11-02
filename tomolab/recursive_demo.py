"""Authored functional example; no real-project or generalization evidence.

python -m tomolab recursive-demo --workspace work/recursive-example --allow-local-execution
"""
from copy import deepcopy
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .discovery.online_engine import OnlinePolicy, run_online
from .discovery.online_learning import learn_mold
from .discovery.online_observe import observe, inspect_target
from .discovery.online_schema import input_identity
from .discovery.recursive_api import (create_generation, update_generation,
    run_generation, save_private_receipt)
from .discovery.recursive_observe import (make_diagnostics, new_trace,
    observe_proposal, validate_trace, execute_pairs)
from .discovery.recursive_policy import make_development_manifest, choose_candidate
from .discovery.recursive_store import GenerationStore
from .discovery.schema import digest

CONTRACT = dict(kind="sequence_int", low=-10, high=10, min_size=0, max_size=3)
EXPERIMENT = digest(dict(name="authored-recursive-functional-v1", seed=47,
    anchor=[1, 2], common="negate", learned="constantize", real_research=False))


def reference(point):
    return sum(point)


def gain_a(point):
    return sum(point) + int(len(point) >= 2 and len(set(point)) == 1)


def gain_b(point):
    wrong = len(point) > 1 and all(value == point[0] for value in point)
    return sum(point) + int(wrong)


def loss_a(point):
    return sum(point) + int(len(point) >= 2 and min(point) < 0 and len(set(point)) > 1)


def loss_b(point):
    wrong = len(point) > 1 and any(value < 0 for value in point) and not all(value == point[0] for value in point)
    return sum(point) + int(wrong)


def reset_fixture():
    # These authored functions have no mutable state; this is their reviewed
    # fresh-call adapter, not a universal reset assertion for external code.
    return True


def _function_sha(fn):
    return hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()


def fixture_mold():
    rows = [dict(input=point, status=status, contract=CONTRACT,
                 source_identity="authored-mold-functional-only")
            for point, status in [([1, 2], "PASS"), ([1, 1], "FAILURE")]]
    mold = learn_mold(rows, operator_grammar=["constantize"])
    # The operator is authored, frozen before any observation in this example.
    assert len(mold["rules"]) == 1
    return mold


def collect_fixture(mold, fn, lineage, *, run_id):
    """Actual host calls at one explicitly authored C state, not a rollout."""
    implementation = _function_sha(fn)
    identity = dict(implementation_sha256=implementation, oracle_sha256=_function_sha(reference),
        environment_sha256=digest(dict(python=sys.version, fixture="authored-v1")),
        reset_adapter_sha256=_function_sha(reset_fixture), purity_review_id="authored-pure-v1")
    cfg = make_diagnostics(mold, experiment_contract_sha256=EXPERIMENT,
        source_lineage_id=lineage, project_id="authored-project", mechanism_id="authored-pair",
        run_id=run_id, identity=identity)
    structure = inspect_target(fn, CONTRACT, mode="black_box")
    before = OnlinePolicy(CONTRACT, method="C", seed=47, budget=63, structure=structure)
    before.attempts = 2
    actual = deepcopy(before).propose([1, 2])
    trace = new_trace(cfg["public"])
    observe_proposal(before, [1, 2], actual, config=cfg["public"], trace=trace,
        seed=47, actual_calls_before=0, shadow_rule_state=None)
    carrier = observe(fn, reference, actual[0], CONTRACT, structure, tracing=False)
    validate_trace(trace, config=cfg["public"], host_rows=[dict(input_digest=input_identity(actual[0]),
        phase=actual[1], target_calls=carrier["target_calls"])])
    paired = execute_pairs(trace, config=cfg["public"], identity=cfg["identity"],
        target=fn, oracle=reference, contract=CONTRACT, structure=structure, reset=reset_fixture, tracing=False)
    assert len(paired["receipts"]) == 1
    metadata = dict(source_lineage_id=lineage, project_id="authored-project", mechanism_id="authored-pair",
        implementation_sha256=implementation, oracle_sha256=_function_sha(reference),
        input_contract_sha256=digest(CONTRACT), independence_id=lineage, review_id="authored-review")
    return paired, metadata, dict(target_calls=carrier["target_calls"], oracle_calls=carrier["oracle_calls"])


def _resume(workspace, generation_id):
    mold = json.loads((workspace / "mold.json").read_text(encoding="utf-8"))
    generation = GenerationStore(workspace / "generations.jsonl").get(generation_id)
    policy = OnlinePolicy(CONTRACT, method="D", seed=47, budget=63,
        mold=mold, selector=generation["selector"])
    policy.attempts = 2
    point, phase, operator, rule_id, decision = policy.propose([1, 2])
    observation = observe(gain_a, reference, point, CONTRACT, {}, tracing=False)
    run = run_generation(workspace / "generations.jsonl", mold, gain_a, reference, CONTRACT,
        generation_id=generation_id, execution_id="new-search-"+generation_id,
        output=workspace / (generation_id+"-online.json"), allow_local_execution=True,
        seed=47, budget=72, shrink_budget=9, mode="black_box", replays=[[1,2],[2,3]])
    row = dict(schema="tomolab-authored-resume-v1", generation_id=generation_id,
        process_id=os.getpid(), generation_digest=generation["sha256"], input=point,
        rule_id=rule_id, decision=decision, status=observation["feedback"]["status"],
        fixed_slot_actual_calls=dict(target_calls=observation["target_calls"], oracle_calls=observation["oracle_calls"]),
        full_new_search_status=run["status"],
        full_new_search_changed_common=run["run"]["scheduler"]["learned_changed_common_executions"],
        full_new_search_allocation_policy=run["run"]["scheduler"]["allocation_policy"],
        full_new_search_epsilon_static_floor=run["run"]["scheduler"]["epsilon_static_floor"],
        full_new_search_policy_calls=run["run"]["scheduler"]["mixed_policy"]["actual"],
        full_new_search_receipt_sha256=run["sha256"], selector_digest=run["selector_digest"],
        full_new_search_cost=run["cost"], evidence_class="AUTHORED_SYNTHETIC_FIXTURE")
    save_private_receipt(workspace / (generation_id+"-resumed.json"), row)
    return row


def _validate_resumed_mixed_run(workspace, row):
    """Check authored restart receipts without requiring a favorable search gain.

    The controlled slot demonstrates selector persistence. A new mixed search
    may correctly abstain or reject duplicates, so its executed guidance count
    is an observation rather than a promised consequence of that slot result.
    """
    workspace = Path(workspace)
    generation = GenerationStore(workspace/"generations.jsonl").get(row["generation_id"])
    receipt = json.loads((workspace/(row["generation_id"]+"-online.json")).read_text(encoding="utf-8"))
    assert receipt["sha256"] == digest({k:v for k,v in receipt.items() if k != "sha256"})
    assert row["full_new_search_receipt_sha256"] == receipt["sha256"]
    assert receipt["generation_digest"] == row["generation_digest"] == generation["sha256"]
    assert receipt["selector_digest"] == row["selector_digest"] == generation["selector"]["selector_digest"]
    run, costs = receipt["run"], row["full_new_search_cost"]
    scheduler = run["scheduler"]
    assert run["status"] == row["full_new_search_status"] == "COMPLETE"
    assert scheduler["allocation_policy"] == row["full_new_search_allocation_policy"] == "STATIC_C_FLOOR_D_CIRCUIT_BREAKER_V3"
    assert scheduler["epsilon_static_floor"] == row["full_new_search_epsilon_static_floor"] == 0.5
    actual = scheduler["mixed_policy"]["actual"]
    assert row["full_new_search_policy_calls"] == actual
    reservation = run["hard_call_meter"]["policy_reservation"]
    assert reservation["reserved_static_calls"] == (run["budget"]+1)//2
    for kind in ("target_calls", "oracle_calls"):
        assert costs[kind] == run[kind] == sum(actual[arm][kind] for arm in ("C", "D"))
        assert actual["C"][kind] >= reservation["reserved_static_calls"]
        assert actual["D"][kind] <= reservation["initial_learned_cap"]
        assert run[kind] <= run["budget"]
        assert all(actual[arm][kind] == reservation["actual_policy_calls"][arm]["actual_"+kind]
                   for arm in ("C", "D"))
    observed_changes = sum(bool(event.get("rule_id")) and
        event.get("source_selection", {}).get("source_changed_common", False) for event in run["events"])
    assert row["full_new_search_changed_common"] == scheduler["learned_changed_common_executions"] == observed_changes
    assert all(scheduler["actual"][lane] <= cap for lane, cap in scheduler["caps"].items())


def run_demo(workspace):
    started = time.perf_counter()
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    mold = fixture_mold()
    save_private_receipt(workspace / "mold.json", mold)
    # Frozen functional registration is written before Target/Oracle calls.
    save_private_receipt(workspace / "functional-contract.json", dict(experiment=EXPERIMENT,
        evidence_class="AUTHORED_SYNTHETIC_FIXTURE", seed=47, contract=CONTRACT,
        mold_digest=mold["artifact_digest"], updates=2,
        authored_implementations={fn.__name__:_function_sha(fn) for fn in (gain_a,gain_b,loss_a,loss_b)},
        oracle_sha256=_function_sha(reference), reset_adapter_sha256=_function_sha(reset_fixture),
        fixed_state_scope="AUTHORED_C_SLOT_NOT_HYPOTHESIS_STATE_RECONSTRUCTION",
        expected_choices=["common", "learned", "common"], real_research=False))
    store_path = workspace / "generations.jsonl"
    create_generation(store_path, mold, CONTRACT)
    carrier_cost = dict(target_calls=0, oracle_calls=0)
    paired_cost = dict(target_calls=0, oracle_calls=0)
    paired_receipt_count = 0
    for generation_id, wave in [("G1", [(gain_a,"gain-a"),(gain_b,"gain-b")]),
                                ("G2", [(loss_a,"loss-a"),(loss_b,"loss-b")])]:
        receipts, lineages = [], []
        wave_carrier = dict(target_calls=0, oracle_calls=0)
        for fn, lineage in wave:
            paired, metadata, carrier = collect_fixture(mold, fn, lineage, run_id=generation_id+"-"+lineage)
            receipts.extend(paired["receipts"])
            # Distinct authored labels exercise the voting mechanism; they are
            # explicitly not independent real implementation/defect evidence.
            lineages.append(metadata)
            for key in carrier_cost:
                carrier_cost[key] += carrier[key]
                wave_carrier[key] += carrier[key]
                paired_cost[key] += paired["cost"][key]
        paired_receipt_count += len(receipts)
        manifest = make_development_manifest(lineages, EXPERIMENT)
        save_private_receipt(workspace / (generation_id+"-development.json"), dict(manifest=manifest, receipts=receipts))
        parent = GenerationStore(store_path).latest()
        cost = deepcopy(parent["cost_ledger"])
        for key in ("target_calls", "oracle_calls", "reset_calls"):
            cost[key] += sum(row["cost"][key] for row in receipts)
        for key in wave_carrier:
            cost[key] += wave_carrier[key]
        cost["observation_wall_seconds"] += sum(row["cost"]["wall_seconds"] for row in receipts)
        update_generation(store_path, receipts, manifest, generation_id=generation_id, cost_ledger=cost)
    # Verify actual caller process termination by running each generation in a
    # distinct child process that reads only persisted files.
    resumed = []
    for generation_id in ("G0", "G1", "G2"):
        completed = subprocess.run([sys.executable, "-m", "tomolab.recursive_demo",
            "--resume", str(workspace), "--generation", generation_id],
            capture_output=True, text=True, timeout=90)
        if completed.returncode:
            raise RuntimeError("authored generation resume failed: " + completed.stderr[-3000:])
        resumed.append(json.loads((workspace / (generation_id+"-resumed.json")).read_text(encoding="utf-8")))
    actual = [row["input"] for row in resumed]
    assert actual == [[-1,-2], [1,1], [-1,-2]], actual
    for row in resumed:
        _validate_resumed_mixed_run(workspace, row)
    assert len({row["process_id"] for row in resumed}) == 3
    assert all(row["full_new_search_status"] == "COMPLETE" for row in resumed)
    summary = dict(schema="tomolab-recursive-functional-summary-v1", status="COMPLETE",
        evidence_class="AUTHORED_SYNTHETIC_FIXTURE", choices=["common","learned","common"],
        executed_candidates=actual, restart_processes=3, generations=3,
        paired_receipts=paired_receipt_count, paired_target_calls=paired_cost["target_calls"],
        paired_oracle_calls=paired_cost["oracle_calls"],
        carrier_cost=carrier_cost, resumed=resumed,
        wall_seconds=time.perf_counter()-started,
        feature_status="FUNCTIONALLY_VERIFIED", real_utility="NOT_ESTABLISHED",
        fixed_slot_learning_effect="COMMON_LEARNED_COMMON_ACTUAL_EXECUTIONS",
        full_new_search_guidance_scope="OBSERVED_EXECUTED_GUIDANCE_NOT_GUARANTEED_BY_FIXED_SLOT",
        generalization="NOT_ESTABLISHED", generation_performance_improvement="NOT_ESTABLISHED",
        real_pilot="HOLD_INSUFFICIENT_REVIEWED_NEW_DEVELOPMENT_MATERIAL",
        default_adoption="HOLD", allow_release=False)
    save_private_receipt(workspace / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    options = parser.parse_args()
    _resume(options.resume, options.generation)
