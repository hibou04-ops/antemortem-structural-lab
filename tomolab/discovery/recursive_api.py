"""Explicit experimental API: development -> generation -> fresh online run.

The selector stays separate from semantic knowledge. Execution receipts are
host-private and preserve actual run costs beside the immutable generation.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from .online_engine import run_online
from .online_mold import validate_mold
from .online_schema import validate_contract
from .recursive_policy import initial_selector, update_selector
from .recursive_store import GenerationStore, make_generation
from .schema import canonical, digest, identifier


def save_private_receipt(path, payload):
    """Exclusive, fsynced local result; never overwrite an earlier execution."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("receipt path must be a regular new file")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(payload) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def create_generation(store_path, mold, contract, *, generation_id="G0"):
    mold = validate_mold(mold)
    contract = validate_contract(contract)
    store = GenerationStore(store_path)
    if store.records():
        raise ValueError("create requires a new generation store")
    selector = initial_selector(mold["artifact_digest"], input_contract_digest=digest(contract))
    generation = make_generation(generation_id, selector)
    store.append(generation)
    return generation


def update_generation(store_path, receipts, development_manifest, *, generation_id,
                      parent_id=None, candidate_validation=None, cost_ledger=None):
    """Append fixed-algorithm development update, keeping unfavorable results."""
    store = GenerationStore(store_path)
    parent = store.get(parent_id) if parent_id is not None else store.latest()
    if parent is None:
        raise ValueError("create G0 before consuming development experience")
    started = time.perf_counter()
    selector = update_selector(parent["selector"], receipts, development_manifest)
    generation = make_generation(generation_id, selector, parent=parent,
        development_manifest=development_manifest, paired_receipts=receipts, candidate_validation=candidate_validation,
        cost_ledger=cost_ledger)
    cost = deepcopy(generation["cost_ledger"])
    cost["learning_seconds"] += time.perf_counter() - started
    generation = make_generation(generation_id, selector, parent=parent,
        development_manifest=development_manifest, candidate_validation=candidate_validation,
        cost_ledger=cost, paired_receipts=receipts)
    store.append(generation)
    return generation


def run_generation(store_path, mold, target, oracle, contract, *, generation_id=None,
                   allow_local_execution=False, execution_id, output, **online_options):
    """Restore a saved selector and execute a NEW online D search.

    This resumes policy experience, not an interrupted Hypothesis engine.
    Target and Oracle must already be reviewed synchronous host callables.
    """
    if allow_local_execution is not True:
        raise PermissionError("explicit trusted local execution opt-in required")
    identifier(execution_id)
    output_path = Path(output)
    if output_path.exists():
        raise FileExistsError("preserve the earlier execution receipt")
    if set(online_options) & {"method", "mold", "selector", "diagnostics", "diagnostic_reset"}:
        raise ValueError("generation run binds the saved experimental selector")
    mold = validate_mold(mold)
    contract = validate_contract(contract)
    store = GenerationStore(store_path)
    generation = store.get(generation_id) if generation_id is not None else store.latest()
    if generation is None:
        raise ValueError("a saved generation is required")
    if generation["mold_digest"] != mold["artifact_digest"]:
        raise ValueError("the saved generation requires its exact frozen Mold")
    if generation["input_contract_digest"] != digest(contract):
        raise ValueError("the saved generation requires its exact input contract")
    # Reserve and fsync the NEW destination before executing either callable.
    # An interrupted run leaves an explicit incomplete reservation for review.
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        reservation = dict(schema="tomolab-generation-execution-reservation-v1",
            status="RESERVED_NOT_COMPLETE", execution_id=execution_id,
            generation_id=generation["generation_id"], generation_digest=generation["sha256"])
        stream.write(canonical(reservation)+"\n")
        stream.flush()
        os.fsync(stream.fileno())
        started = time.perf_counter()
        try:
            run = run_online(target, oracle, contract, method="D", mold=mold,
                selector=generation["selector"], **online_options)
            receipt = dict(schema="tomolab-generation-execution-v1", execution_id=execution_id,
                generation_id=generation["generation_id"], generation_digest=generation["sha256"],
                selector_digest=generation["selector"]["selector_digest"],
                status=run["status"], run=run, cost=dict(target_calls=run["target_calls"],
                oracle_calls=run["oracle_calls"], wall_seconds=time.perf_counter()-started),
                training_cost_ledger=deepcopy(generation["cost_ledger"]),
                policy_state_resumed="SAVED_SELECTOR_FOR_NEW_SEARCH_ONLY",
                utility_status="NOT_ESTABLISHED", default_adoption="HOLD", allow_release=False)
            receipt["sha256"] = digest(receipt)
        except BaseException as error:
            incomplete = dict(reservation, status="INCOMPLETE_EXECUTION",
                error_type=type(error).__name__, cost_status="UNKNOWN_PRESERVE_RESERVATION")
            stream.seek(0)
            stream.write(canonical(incomplete)+"\n")
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            raise
        stream.seek(0)
        stream.write(canonical(receipt)+"\n")
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    return receipt
