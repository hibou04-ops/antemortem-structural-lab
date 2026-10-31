"""Opt-in paired diagnostics: public worker traces, host-only executions.

These receipts establish repeatable local comparisons, never full Hypothesis
counterfactual state or semantic claim authority.
"""
from copy import deepcopy
import math
import re
import time

from .schema import canonical, digest, identifier
from .online_schema import input_identity, validate_input

CONFIG_SCHEMA = "tomolab-paired-config-v1"
TRACE_SCHEMA = "tomolab-paired-trace-v1"
RECEIPT_SCHEMA = "tomolab-paired-receipt-v1"
MAX_SNAPSHOT_BYTES = 128 * 1024
MAX_TRACE_BYTES = 2 * 1024 * 1024
MAX_PAIRS = 12
MAX_SLOTS = 1024
IDENTITY_FIELDS = {"implementation_sha256", "oracle_sha256", "environment_sha256",
                   "reset_adapter_sha256", "purity_review_id"}
PUBLIC_FIELDS = {"schema", "mold", "experiment_contract_sha256", "source_lineage_id",
                 "project_id", "mechanism_id", "run_id", "split", "max_pairs",
                 "max_pair_calls", "max_pair_seconds"}
STATE_FIELDS = {"contract", "method", "structure", "mold", "replays", "caps", "used",
    "archive", "last_feedback", "attempts", "operator_rewards", "guidance_rejected",
    "duplicate_guidance", "guidance_lookups", "guidance_not_applicable", "guidance_matches",
    "guidance_applied", "guidance_changed_common", "guidance_invalid", "guidance_duplicates",
    "guidance_unexecutable", "guidance_lookup_seconds", "last_selection", "used_rules", "seen",
    "rng", "rule_rng"}
RESERVATION_FIELDS = {"schema", "experiment_contract_sha256", "source_lineage_id", "run_id",
    "seed", "proposal_index", "actual_calls_before", "phase", "state", "state_digest",
    "common_state_digest", "native_input", "anchor_input", "common_input", "learned_input",
    "native_digest", "anchor_digest", "common_digest", "learned_digest", "common_operator",
    "rule_id", "learned_edit_composition", "mold_digest", "input_contract_sha256",
    "structure_sha256", "context", "reservation_id", "shadow_rule_rng_before", "shadow_rule_rng_after"}


def _hash(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("explicit SHA256 identity required")
    return value


def _fields(value, fields, what):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("unsupported "+what+" fields")


def validate_public_diagnostics(config):
    from .online_mold import validate_mold
    _fields(config, PUBLIC_FIELDS, "paired configuration")
    if config["schema"] != CONFIG_SCHEMA or config["split"] != "development":
        raise PermissionError("only explicit development paired diagnostics are accepted")
    validate_mold(config["mold"])
    _hash(config["experiment_contract_sha256"])
    for name in ("source_lineage_id", "project_id", "mechanism_id", "run_id"):
        identifier(config[name])
    if type(config["max_pairs"]) is not int or not 1 <= config["max_pairs"] <= MAX_PAIRS:
        raise ValueError("at most twelve paired reservations")
    if type(config["max_pair_calls"]) is not int or not 0 <= config["max_pair_calls"] <= 72:
        raise ValueError("independent diagnostic call ceiling is at most 72 per branch resource")
    if type(config["max_pair_seconds"]) not in (int, float) or not math.isfinite(config["max_pair_seconds"]) or not 0 < config["max_pair_seconds"] <= 90:
        raise ValueError("paired cooperative wall ceiling is at most ninety seconds")
    return deepcopy(config)


def validate_identity(identity):
    _fields(identity, IDENTITY_FIELDS, "host identity")
    for name in IDENTITY_FIELDS - {"purity_review_id"}:
        _hash(identity[name])
    identifier(identity["purity_review_id"])
    return deepcopy(identity)


def make_diagnostics(mold, *, experiment_contract_sha256, source_lineage_id,
                     project_id, mechanism_id, run_id, identity):
    public = dict(schema=CONFIG_SCHEMA, mold=deepcopy(mold),
        experiment_contract_sha256=experiment_contract_sha256,
        source_lineage_id=source_lineage_id, project_id=project_id,
        mechanism_id=mechanism_id, run_id=run_id, split="development",
        max_pairs=12, max_pair_calls=72, max_pair_seconds=90)
    return dict(schema="tomolab-paired-diagnostics-v1", public=validate_public_diagnostics(public),
                identity=validate_identity(identity))


def validate_diagnostics(config):
    _fields(config, {"schema", "public", "identity"}, "host diagnostics")
    if config["schema"] != "tomolab-paired-diagnostics-v1":
        raise ValueError("unsupported host diagnostic schema")
    validate_public_diagnostics(config["public"])
    validate_identity(config["identity"])
    return deepcopy(config)


def policy_snapshot(policy):
    state = {name: deepcopy(getattr(policy, name)) for name in STATE_FIELDS - {"rng", "rule_rng", "seen"}}
    state.update(rng=policy.rng.getstate(), rule_rng=policy.rule_rng.getstate(), seen=sorted(policy.seen))
    # JSON normalization is intentional: RNG tuples and lists have one identity.
    import json
    state = json.loads(canonical(state))
    if len(canonical(state).encode()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("policy snapshot exceeds 128KiB")
    return state


def _tuple(value):
    return tuple(_tuple(v) for v in value) if isinstance(value, list) else value


def restore_policy(state):
    from .online_engine import OnlinePolicy
    _fields(state, STATE_FIELDS, "public policy snapshot")
    if len(canonical(state).encode()) > MAX_SNAPSHOT_BYTES or state["method"] != "C" or state["mold"] is not None:
        raise ValueError("bounded C policy state required")
    from .online_schema import validate_online_config, validate_online_observation
    validate_online_config(dict(contract=state["contract"], structure=state["structure"], method="C",
        seed=0, budget=3, shrink_budget=0, mold=None, replays=state["replays"], max_seconds=1, _started=0))
    for name, fields in (("caps", {"replay", "structure"}), ("used", {"base", "replay", "structure"})):
        _fields(state[name], fields, "snapshot budget")
        if any(type(v) is not int or not 0 <= v <= 10000 for v in state[name].values()):
            raise ValueError("bounded snapshot budgets required")
    counters = {"attempts", "guidance_rejected", "duplicate_guidance", "guidance_lookups",
        "guidance_not_applicable", "guidance_matches", "guidance_applied", "guidance_changed_common",
        "guidance_invalid", "guidance_duplicates", "guidance_unexecutable"}
    if any(type(state[n]) is not int or not 0 <= state[n] <= 100000 for n in counters):
        raise ValueError("bounded public policy counters required")
    if type(state["guidance_lookup_seconds"]) not in (int, float) or not math.isfinite(state["guidance_lookup_seconds"]) or state["guidance_lookup_seconds"] < 0:
        raise ValueError("bounded lookup cost required")
    from .online_schema import common_operators
    if set(state["operator_rewards"]) != set(common_operators(state["contract"]["kind"])) or any(type(v) is not int or not 1 <= v <= 100000 for v in state["operator_rewards"].values()):
        raise ValueError("bounded operator rewards required")
    if type(state["seen"]) is not list or len(state["seen"]) > 10000 or len(set(state["seen"])) != len(state["seen"]):
        raise ValueError("bounded distinct seen identities required")
    for value in state["seen"]:
        _hash(value)
    if type(state["used_rules"]) is not list or state["used_rules"]:
        raise ValueError("C snapshot has no learned rule executions")
    if type(state["last_selection"]) is not dict or set(state["last_selection"])-{"source_state", "source_changed_common", "common_candidate_digest", "common_operator"}:
        raise ValueError("unsupported C selection state")
    selection = state["last_selection"]
    if selection:
        _fields(selection, {"source_state", "source_changed_common", "common_candidate_digest", "common_operator"}, "C selection state")
        if selection["source_state"] != "NOT_A_SOURCE_SLOT" or selection["source_changed_common"] is not False or selection["common_operator"] is not None and selection["common_operator"] not in common_operators(state["contract"]["kind"]):
            raise ValueError("invalid C selection fields")
        if selection["common_candidate_digest"] is not None:
            _hash(selection["common_candidate_digest"])
    def validate_feedback(feedback, point):
        validate_online_observation(dict(feedback=feedback, target_calls=1, oracle_calls=1,
            cost=dict(target_seconds=0.0,oracle_seconds=0.0,instrumentation_seconds=0.0),
            observation_id=0,reference_match=None),request_id=0,point=point,contract=state["contract"])
    if type(state["archive"]) is not list or len(state["archive"]) > 32:
        raise ValueError("bounded public archive required")
    for row in state["archive"]:
        _fields(row, {"input", "feedback"}, "archive entry")
        if not validate_input(row["input"], state["contract"]):
            raise ValueError("invalid public archive input")
        validate_feedback(row["feedback"], row["input"])
    if state["last_feedback"] is not None:
        # Its public input digest must name a previously archived/seen input;
        # errors need not be archived, so validate the exact feedback keys here.
        fields={"status","input_digest","coverage","branch_distance","contract_checked"}
        if type(state["last_feedback"]) is not dict or not fields <= set(state["last_feedback"]) or set(state["last_feedback"])-fields-{"exception_type","exception_location"}:
            raise ValueError("unsupported last feedback fields")
        feedback = state["last_feedback"]
        _hash(feedback["input_digest"])
        if feedback["status"] not in ("PASS", "FAILURE", "UNKNOWN", "INVALID_INPUT", "EXECUTION_ERROR", "ORACLE_ERROR") or type(feedback["coverage"]) is not list or len(feedback["coverage"]) > 100000 or any(type(v) is not int or not 0 <= v <= 10**8 for v in feedback["coverage"]):
            raise ValueError("invalid public feedback status or locations")
        if feedback["branch_distance"] is not None and (type(feedback["branch_distance"]) not in (int,float) or not math.isfinite(feedback["branch_distance"]) or feedback["branch_distance"] < 0):
            raise ValueError("invalid public branch distance")
        if feedback.get("exception_type") is not None and (type(feedback["exception_type"]) is not str or len(feedback["exception_type"]) > 256):
            raise ValueError("invalid public exception identity")
        if feedback.get("exception_location") is not None and (type(feedback["exception_location"]) is not int or not 0 <= feedback["exception_location"] <= 10**8):
            raise ValueError("invalid public exception location")
        if state["last_feedback"]["contract_checked"] != digest(state["contract"]):
            raise ValueError("last feedback contract identity mismatch")
    policy = OnlinePolicy(state["contract"], method="C", seed=0, budget=0,
                          replays=state["replays"], structure=state["structure"])
    for name in STATE_FIELDS - {"rng", "rule_rng", "seen"}:
        setattr(policy, name, deepcopy(state[name]))
    policy.rng.setstate(_tuple(state["rng"]))
    policy.rule_rng.setstate(_tuple(state["rule_rng"]))
    policy.seen = set(state["seen"])
    return policy


def new_trace(config):
    validate_public_diagnostics(config)
    return dict(schema=TRACE_SCHEMA, status="COMPLETE", reservations=[], slots=[],
                cost=dict(snapshot_seconds=0.0, shadow_seconds=0.0, shadow_proposals=0, common_validation_proposals=0, mold_lookups=0),
                unknown_reasons=[], limitations=["HYPOTHESIS_INTERNAL_STATE_NOT_CAPTURED",
                "CONDITIONAL_C_STATE_NOT_FULL_COUNTERFACTUAL_ROLLOUT"])


def observe_proposal(policy_before, native, actual, *, config, trace, seed,
                     actual_calls_before, shadow_rule_state):
    """Only clones are mutated; the actual C policy and its RNG stay untouched."""
    from .recursive_policy import make_context
    tick = time.perf_counter()
    before = policy_before
    slot = before.attempts % 10
    if not (2 <= slot < 5 and before.used["structure"] + 3 <= before.caps["structure"]):
        return shadow_rule_state
    shadow = deepcopy(before)
    shadow.method, shadow.mold = "D", deepcopy(config["mold"])
    if shadow_rule_state is not None:
        shadow.rule_rng.setstate(_tuple(shadow_rule_state))
    shadow_rule_rng_before = shadow.rule_rng.getstate()
    native = deepcopy(native)
    anchor = deepcopy(native)
    if before.archive:
        failures = [r for r in before.archive if r["feedback"]["status"] == "FAILURE"]
        anchor = deepcopy((failures or before.archive)[-1]["input"])
    trace["cost"]["shadow_proposals"] += 1
    trace["cost"]["mold_lookups"] += 1
    learned = shadow.propose(native)
    selection = shadow.last_selection
    trace["cost"]["common_validation_proposals"] += 1
    common = deepcopy(before).propose(native)
    if input_identity(common[0]) != input_identity(actual[0]) or selection.get("common_candidate_digest") != input_identity(actual[0]):
        raise ValueError("actual C candidate differs from same-anchor shadow common")
    reason = selection.get("source_state", "UNKNOWN")
    if reason == "APPLIED":
        reason = "CANDIDATE_SAME" if input_identity(learned[0]) == input_identity(common[0]) else "ELIGIBLE"
    if reason == "ELIGIBLE" and input_identity(actual[0]) in before.seen:
        reason = "ACTUAL_C_DUPLICATE_NOT_EXECUTED"
    if reason == "ELIGIBLE" and len(trace["reservations"]) >= config["max_pairs"]:
        reason = "PAIR_CAP_REACHED"
    summary = dict(proposal_index=before.attempts+1, common_digest=input_identity(common[0]),
                   learned_digest=input_identity(learned[0]), source_state=selection.get("source_state"), reason=reason)
    trace["slots"].append(summary)
    if len(trace["slots"]) > MAX_SLOTS:
        raise ValueError("diagnostic slot count exceeded")
    if reason == "ELIGIBLE":
        state = policy_snapshot(before)
        rule = next(rule for rule in config["mold"]["rules"] if rule["rule_id"] == learned[3])
        reservation = dict(schema="tomolab-paired-reservation-v1",
            experiment_contract_sha256=config["experiment_contract_sha256"],
            source_lineage_id=config["source_lineage_id"], run_id=config["run_id"], seed=seed,
            proposal_index=before.attempts+1, actual_calls_before=actual_calls_before,
            phase=common[1], state=state, state_digest=digest(state),
            common_state_digest=before.common_state_digest(), native_input=native, anchor_input=anchor,
            common_input=deepcopy(common[0]), learned_input=deepcopy(learned[0]),
            native_digest=input_identity(native), anchor_digest=input_identity(anchor),
            common_digest=input_identity(common[0]), learned_digest=input_identity(learned[0]),
            common_operator=common[2], rule_id=learned[3],
            learned_edit_composition=deepcopy(rule["edit_composition"]),
            mold_digest=config["mold"]["artifact_digest"], input_contract_sha256=digest(before.contract),
            structure_sha256=digest(before.structure),
            context=make_context(anchor, before.contract, common[2], rule["edit_composition"]),
            shadow_rule_rng_before=shadow_rule_rng_before, shadow_rule_rng_after=shadow.rule_rng.getstate())
        reservation["reservation_id"] = digest(reservation)
        if any(r["reservation_id"] == reservation["reservation_id"] for r in trace["reservations"]):
            raise ValueError("duplicate paired reservation")
        trace["reservations"].append(reservation)
    if len(canonical(trace).encode()) > MAX_TRACE_BYTES:
        raise ValueError("diagnostic trace exceeds 2MiB")
    trace["cost"]["shadow_seconds"] += time.perf_counter()-tick
    return shadow.rule_rng.getstate()


def validate_reservation(reservation, *, config=None):
    from .recursive_policy import make_context
    from .online_schema import apply_edit
    _fields(reservation, RESERVATION_FIELDS, "paired reservation")
    r = reservation
    for name in ("source_lineage_id", "run_id"):
        identifier(r[name])
    for name in ("rule_id", "reservation_id"):
        _hash(r[name])
    if type(r["seed"]) is not int or not 0 <= r["seed"] < 2**32 or r["phase"] not in ("structure", "base"):
        raise ValueError("invalid paired seed or phase")
    if r["schema"] != "tomolab-paired-reservation-v1" or r["reservation_id"] != digest({k:v for k,v in r.items() if k != "reservation_id"}):
        raise ValueError("reservation digest or schema mismatch")
    for name in ("experiment_contract_sha256", "mold_digest", "input_contract_sha256", "structure_sha256", "state_digest", "common_state_digest"):
        _hash(r[name])
    if digest(r["state"]) != r["state_digest"]:
        raise ValueError("snapshot digest mismatch")
    # Random.setstate validates shape/ranges without changing the C state.
    import random
    for name in ("shadow_rule_rng_before", "shadow_rule_rng_after"):
        random.Random().setstate(_tuple(r[name]))
    policy = restore_policy(r["state"])
    if not (2 <= policy.attempts % 10 < 5 and policy.used["structure"]+3 <= policy.caps["structure"]):
        raise ValueError("reservation is outside an eligible C structural slot")
    if policy.common_state_digest() != r["common_state_digest"] or digest(policy.contract) != r["input_contract_sha256"] or digest(policy.structure) != r["structure_sha256"]:
        raise ValueError("snapshot context identity mismatch")
    if type(r["proposal_index"]) is not int or r["proposal_index"] != policy.attempts + 1 or type(r["actual_calls_before"]) is not int or not 0 <= r["actual_calls_before"] <= 10000:
        raise ValueError("reservation position mismatch")
    for role in ("native", "anchor", "common", "learned"):
        if not validate_input(r[role+"_input"], policy.contract) or input_identity(r[role+"_input"]) != r[role+"_digest"]:
            raise ValueError("reservation candidate identity mismatch")
    anchor = deepcopy(r["native_input"])
    if policy.archive:
        failures = [row for row in policy.archive if row["feedback"]["status"] == "FAILURE"]
        anchor = deepcopy((failures or policy.archive)[-1]["input"])
    common = policy.propose(r["native_input"])
    if anchor != r["anchor_input"] or common[0] != r["common_input"] or common[1] != r["phase"] or common[2] != r["common_operator"]:
        raise ValueError("same-anchor common reconstruction mismatch")
    operators = r["learned_edit_composition"]
    if type(operators) is not list or not 1 <= len(operators) <= 2:
        raise ValueError("bounded frozen edit composition required")
    learned = deepcopy(anchor)
    for operator in operators:
        learned = apply_edit(learned, operator, policy.contract, policy.structure)
    if learned != r["learned_input"] or r["learned_digest"] == r["common_digest"] or r["learned_digest"] in policy.seen:
        raise ValueError("same-anchor learned reconstruction mismatch")
    if r["context"] != make_context(anchor, policy.contract, r["common_operator"], operators):
        raise ValueError("selector context differs from observed structure")
    if config is not None:
        validate_public_diagnostics(config)
        for key in ("experiment_contract_sha256", "source_lineage_id", "run_id"):
            if r[key] != config[key]:
                raise ValueError("reservation run identity mismatch")
        if r["mold_digest"] != config["mold"]["artifact_digest"]:
            raise ValueError("reservation Mold identity mismatch")
        rule = next((rule for rule in config["mold"]["rules"] if rule["rule_id"] == r["rule_id"]), None)
        from .online_mold import _matches
        if rule is None or rule["edit_composition"] != operators or rule["kind"] != policy.contract["kind"] or _matches(anchor, rule["preconditions"]) is not True:
            raise ValueError("reservation not bound to frozen rule")
        shadow = restore_policy(r["state"])
        shadow.method, shadow.mold = "D", deepcopy(config["mold"])
        shadow.rule_rng.setstate(_tuple(r["shadow_rule_rng_before"]))
        selected = shadow.propose(r["native_input"])
        if selected[0] != r["learned_input"] or selected[3] != r["rule_id"] or digest(shadow.rule_rng.getstate()) != digest(r["shadow_rule_rng_after"]):
            raise ValueError("shadow rule RNG selection reconstruction mismatch")
    return deepcopy(r)


def validate_trace(trace, *, config, host_rows=None):
    _fields(trace, {"schema", "status", "reservations", "slots", "unknown_reasons", "limitations", "cost"}, "diagnostic trace")
    if trace["schema"] != TRACE_SCHEMA or trace["status"] not in ("COMPLETE", "HOLD_MEASUREMENT") or len(canonical(trace).encode()) > MAX_TRACE_BYTES:
        raise ValueError("invalid trace schema, status or size")
    if type(trace["reservations"]) is not list or len(trace["reservations"]) > config["max_pairs"] or type(trace["slots"]) is not list or len(trace["slots"]) > MAX_SLOTS:
        raise ValueError("trace reservation or slot cap exceeded")
    validate_public_diagnostics(config)
    _fields(trace["cost"], {"snapshot_seconds", "shadow_seconds", "shadow_proposals", "common_validation_proposals", "mold_lookups"}, "worker diagnostic cost")
    for name in ("snapshot_seconds", "shadow_seconds"):
        if type(trace["cost"][name]) not in (int,float) or not math.isfinite(trace["cost"][name]) or trace["cost"][name] < 0:
            raise ValueError("invalid worker diagnostic time")
    for name in ("shadow_proposals", "common_validation_proposals", "mold_lookups"):
        if type(trace["cost"][name]) is not int or not 0 <= trace["cost"][name] <= MAX_SLOTS:
            raise ValueError("invalid worker generation count")
    if trace["status"] == "COMPLETE" and any(trace["cost"][name] != len(trace["slots"]) for name in ("shadow_proposals", "common_validation_proposals", "mold_lookups")):
        raise ValueError("worker generation counts differ from structural slots")
    reasons = {"APPLIED", "NO_MOLD", "NOT_APPLICABLE", "UNEXECUTABLE", "INVALID_RESULT", "DUPLICATE_RESULT", "UNKNOWN", "CANDIDATE_SAME", "ELIGIBLE", "PAIR_CAP_REACHED", "ACTUAL_C_DUPLICATE_NOT_EXECUTED"}
    for row in trace["slots"]:
        _fields(row, {"proposal_index", "common_digest", "learned_digest", "source_state", "reason"}, "trace slot")
        if type(row["proposal_index"]) is not int or not 1 <= row["proposal_index"] <= 100000 or row["source_state"] not in reasons or row["reason"] not in reasons:
            raise ValueError("invalid diagnostic slot metadata")
        _hash(row["common_digest"])
        _hash(row["learned_digest"])
    if type(trace["unknown_reasons"]) is not list or len(trace["unknown_reasons"]) > 16 or any(type(v) is not str or len(v) > 200 for v in trace["unknown_reasons"]):
        raise ValueError("bounded trace uncertainty reasons required")
    if trace["limitations"] != ["HYPOTHESIS_INTERNAL_STATE_NOT_CAPTURED", "CONDITIONAL_C_STATE_NOT_FULL_COUNTERFACTUAL_ROLLOUT"]:
        raise ValueError("diagnostic reconstruction scope cannot be widened")
    if trace["status"] == "HOLD_MEASUREMENT" and not trace["unknown_reasons"]:
        raise ValueError("measurement hold needs an explicit reason")
    ids = set()
    for r in trace["reservations"]:
        validate_reservation(r, config=config)
        if r["reservation_id"] in ids:
            raise ValueError("duplicate reservation")
        ids.add(r["reservation_id"])
        # Some valid proposals are duplicates in the actual stream. They may
        # have no host execution; paired replay cannot invent that execution.
        if host_rows is None:
            continue
        at = r["actual_calls_before"]
        calls = 0
        actual = None
        for row in host_rows:
            if calls == at:
                actual = row
                break
            calls += row["target_calls"]
        if actual is None or actual["input_digest"] != r["common_digest"] or actual["phase"] != r["phase"]:
            raise ValueError("reservation does not match actual C execution boundary")
    return deepcopy(trace)


def _resolved(branch):
    if len(branch) != 3:
        return None
    if not all(row["reset_success"] is True and row["status"] in ("PASS", "FAILURE")
               and type(row["semantic_digest"]) is str for row in branch):
        return None
    if len({row["status"] for row in branch}) != 1 or len({row["semantic_digest"] for row in branch}) != 1:
        return None
    return branch[0]["status"]


def derive_label(branches):
    common, learned = (_resolved(branches[name]) for name in ("common", "learned"))
    if common is None or learned is None:
        return "UNKNOWN"
    return {("PASS", "FAILURE"): "gain", ("FAILURE", "PASS"): "loss",
            ("PASS", "PASS"): "neutral_pass", ("FAILURE", "FAILURE"): "neutral_failure"}[(common, learned)]


def validate_pair_receipt(receipt):
    fields = {"schema", "split", "context", "source_lineage_id", "project_id", "mechanism_id",
        "mold_digest", "input_contract_sha256", "reservation_id", "pair_receipt_sha256",
        "experiment_contract_sha256", "identity", "branches", "label", "unknown_reasons", "cost", "reservation"}
    _fields(receipt, fields, "paired receipt")
    if len(canonical(receipt).encode()) > 256 * 1024:
        raise ValueError("paired receipt exceeds 256KiB")
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["split"] != "development":
        raise PermissionError("final feedback cannot be consumed as development evidence")
    if receipt["pair_receipt_sha256"] != digest({k:v for k,v in receipt.items() if k != "pair_receipt_sha256"}):
        raise ValueError("paired receipt digest mismatch")
    validate_identity(receipt["identity"])
    reservation = validate_reservation(receipt["reservation"])
    for name in ("reservation_id", "context", "source_lineage_id", "mold_digest", "input_contract_sha256", "experiment_contract_sha256"):
        if receipt[name] != reservation[name]:
            raise ValueError("receipt identity differs from reservation")
    for name in ("project_id", "mechanism_id", "source_lineage_id"):
        identifier(receipt[name])
    _fields(receipt["branches"], {"common", "learned"}, "paired branches")
    for name, branch in receipt["branches"].items():
        if type(branch) is not list or len(branch) > 3:
            raise ValueError("bounded branch repeats required")
        for index, row in enumerate(branch):
            _fields(row, {"observation_id", "repeat", "status", "semantic_digest", "feedback_digest", "reset_success", "target_calls", "oracle_calls", "error_type"}, "host repetition")
            _hash(row["observation_id"])
            if row["error_type"] is not None and (type(row["error_type"]) is not str or not 1 <= len(row["error_type"]) <= 200):
                raise ValueError("bounded host error identity required")
            if type(row["repeat"]) is not int or row["repeat"] != index or type(row["reset_success"]) is not bool or row["status"] not in ("PASS", "FAILURE", "UNKNOWN", "INVALID_INPUT", "EXECUTION_ERROR", "ORACLE_ERROR"):
                raise ValueError("invalid host repetition")
            if row["semantic_digest"] is not None:
                _hash(row["semantic_digest"])
            if row["feedback_digest"] is not None:
                _hash(row["feedback_digest"])
            for key in ("target_calls", "oracle_calls"):
                if type(row[key]) is not int or not 0 <= row[key] <= 1:
                    raise ValueError("actual call increments required")
            if row["status"] in ("PASS", "FAILURE") and (row["target_calls"] != 1 or row["oracle_calls"] != 1):
                raise ValueError("resolved repetition requires actual Target and Oracle calls")
    if receipt["label"] != derive_label(receipt["branches"]):
        raise ValueError("paired label differs from actual repetitions")
    if type(receipt["unknown_reasons"]) is not list or len(receipt["unknown_reasons"]) > 16 or any(type(v) is not str or len(v) > 200 for v in receipt["unknown_reasons"]):
        raise ValueError("bounded uncertainty reasons required")
    if receipt["label"] == "UNKNOWN" and not receipt["unknown_reasons"]:
        raise ValueError("unresolved receipt needs an explicit reason")
    _fields(receipt["cost"], {"target_calls", "oracle_calls", "reset_calls", "wall_seconds"}, "paired cost")
    rows = receipt["branches"]["common"] + receipt["branches"]["learned"]
    for key in ("target_calls", "oracle_calls"):
        if receipt["cost"][key] != sum(row[key] for row in rows):
            raise ValueError("paired cost differs from actual call increments")
    if type(receipt["cost"]["reset_calls"]) is not int or not 0 <= receipt["cost"]["reset_calls"] <= 6 or type(receipt["cost"]["wall_seconds"]) not in (int, float) or not math.isfinite(receipt["cost"]["wall_seconds"]) or receipt["cost"]["wall_seconds"] < 0:
        raise ValueError("invalid reset or wall cost")
    return deepcopy(receipt)


def execute_pairs(trace, *, config, identity, target, oracle, contract, structure,
                  reset=None, tracing=True, trace_target=None):
    """Host-only post-worker replay. No observation returns to the worker."""
    from .online_observe import observe
    validate_identity(identity)
    validate_trace(trace, config=config)
    if trace["status"] != "COMPLETE":
        raise ValueError("incomplete worker measurement cannot execute pairs")
    for reservation in trace["reservations"]:
        if reservation["input_contract_sha256"] != digest(contract) or reservation["structure_sha256"] != digest(structure):
            raise ValueError("host pair contract or structure differs from reservation")
    started = time.perf_counter()
    totals = dict(target_calls=0, oracle_calls=0, reset_calls=0, wall_seconds=0.0)
    receipts = []
    for reservation in trace["reservations"]:
        tick = time.perf_counter()
        branches, reasons = dict(common=[], learned=[]), []
        local = dict(target_calls=0, oracle_calls=0, reset_calls=0, wall_seconds=0.0)
        order = ("common", "learned") if int(reservation["reservation_id"], 16) % 2 == 0 else ("learned", "common")
        for name in order:
            for repeat in range(3):
                if max(totals["target_calls"], totals["oracle_calls"]) >= config["max_pair_calls"] or time.perf_counter()-started >= config["max_pair_seconds"]:
                    reasons.append("DIAGNOSTIC_RESOURCE_LIMIT")
                    break
                reset_success, error_type = False, None
                if reset is not None:
                    totals["reset_calls"] += 1
                    local["reset_calls"] += 1
                    try:
                        reset_success = reset() is True
                    except Exception as error:
                        error_type = type(error).__name__
                if not reset_success:
                    row = dict(observation_id=digest(dict(reservation=reservation["reservation_id"], branch=name, repeat=repeat)), repeat=repeat, status="UNKNOWN", semantic_digest=None,
                        feedback_digest=None, reset_success=False, target_calls=0, oracle_calls=0, error_type=error_type or "RESET_NOT_VERIFIED")
                    reasons.append("RESET_NOT_VERIFIED")
                else:
                    observation = observe(target, oracle, reservation[name+"_input"], contract,
                        structure, tracing=tracing, trace_target=trace_target)
                    row = dict(observation_id=digest(dict(reservation=reservation["reservation_id"], branch=name, repeat=repeat)), repeat=repeat,
                        status=observation["feedback"]["status"], semantic_digest=observation.get("semantic_digest"),
                        feedback_digest=digest(observation["feedback"]), reset_success=True,
                        target_calls=observation["target_calls"], oracle_calls=observation["oracle_calls"], error_type=None)
                    for key in ("target_calls", "oracle_calls"):
                        totals[key] += row[key]
                        local[key] += row[key]
                branches[name].append(row)
        label = derive_label(branches)
        if label == "UNKNOWN" and not reasons:
            reasons.append("REPETITION_STATUS_OR_SEMANTICS_UNRESOLVED")
        local["wall_seconds"] = time.perf_counter()-tick
        receipt = dict(schema=RECEIPT_SCHEMA, split="development", context=deepcopy(reservation["context"]),
            source_lineage_id=config["source_lineage_id"], project_id=config["project_id"], mechanism_id=config["mechanism_id"],
            mold_digest=reservation["mold_digest"], input_contract_sha256=digest(contract),
            reservation_id=reservation["reservation_id"], experiment_contract_sha256=config["experiment_contract_sha256"],
            identity=deepcopy(identity), branches=branches, label=label, unknown_reasons=sorted(set(reasons)),
            cost=local, reservation=deepcopy(reservation))
        receipt["pair_receipt_sha256"] = digest(receipt)
        receipts.append(validate_pair_receipt(receipt))
    totals["wall_seconds"] = time.perf_counter()-started
    return dict(schema="tomolab-paired-host-result-v1", status="COMPLETE" if receipts and trace["status"] == "COMPLETE" and all(r["label"] != "UNKNOWN" for r in receipts) else "HOLD_MEASUREMENT",
                receipts=receipts, cost=totals, slots=deepcopy(trace["slots"]),
                worker_instrumentation_cost=deepcopy(trace["cost"]),
                unknown_reasons=[] if receipts else ["NO_ELIGIBLE_RESERVATIONS"],
                transport_calls_not_in_diagnostic_cost=True,
                scope="CONDITIONAL_LOCAL_PAIRS_NOT_POLICY_UTILITY_OR_GENERALIZATION")
