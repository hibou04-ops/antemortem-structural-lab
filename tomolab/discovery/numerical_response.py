"""Strict host-only checks for immutable numerical worker responses.

These checks authenticate consistency with a host-approved request, not the
truth of a numerical Oracle or the correctness of the generation algorithm.
This module is deliberately outside the worker's five-module allowlist.
"""
from copy import deepcopy
import math

from .schema import canonical, digest, integer, keys
from .numerical_guidance import (FAMILIES, domain_guard, input_features,
    numerical_input_digest)

GENERATION_FIELDS = ("schema", "method", "candidates", "attempts",
    "domain_rejections", "duplicate_rejections", "existing_input_rejections",
    "mechanism_filter_rejections", "explicit_replays", "oracle_calls",
    "target_calls", "wall_seconds", "cpu_seconds", "stop")
PLAN_FIELDS = ("schema", "artifact_digest", "source_archive_digest",
    "candidate_digest", "generation", "execution_contract_digest", "frozen",
    "learning_allowed", "final_feedback_allowed")
FREEZE_FIELDS = ("candidate_digest", "frozen", "learning_allowed",
    "final_feedback_allowed", "request_digest")


def _bounded_json(value):
    if len(canonical(value).encode("utf-8"))+1 > 8_000_000:
        raise ValueError("numerical worker response exceeds 8000000 bytes")


def _frozen(value):
    if (value["frozen"] is not True or value["learning_allowed"] is not False or
            value["final_feedback_allowed"] is not False):
        raise ValueError("numerical response is not frozen with learning prohibited")


def validate_generation(generation, request):
    """Validate received data without generating replacement candidates."""
    keys(generation, GENERATION_FIELDS)
    _bounded_json(generation)
    method = "D" if request["action"] == "plan" else request["method"]
    if generation["schema"] != "tomolab-numerical-candidates-v1" or generation["method"] != method:
        raise ValueError("generation schema or requested method differs")
    candidates = generation["candidates"]
    if not isinstance(candidates, list) or len(candidates) > request["size"]:
        raise ValueError("invalid numerical candidate count")
    integer(generation["attempts"], 0, request["max_examples"])
    for field in ("domain_rejections", "duplicate_rejections", "existing_input_rejections",
                  "mechanism_filter_rejections", "explicit_replays"):
        integer(generation[field], 0, request["max_examples"]+64)
    if generation["oracle_calls"] != 0 or type(generation["oracle_calls"]) is not int or generation["target_calls"] != 0 or type(generation["target_calls"]) is not int:
        raise ValueError("generator may not invoke Target or Oracle")
    for field in ("wall_seconds", "cpu_seconds"):
        value = generation[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid generation timing")
    expected_stop = "REQUESTED_CANDIDATES" if len(candidates) == request["size"] else "DRAW_BUDGET_OR_DOMAIN_EXHAUSTED"
    if generation["stop"] != expected_stop:
        raise ValueError("partial numerical generation lacks an explicit bounded stop")
    contract = request.get("contract") or request["artifact"]["public_input_contract"]
    excluded = set(request["excluded_digests"])
    replay_digests = {numerical_input_digest(point) for point in request.get("replay_inputs", [])}
    seen = set()
    explicit_replays = 0
    for candidate in candidates:
        keys(candidate, ("inputs", "origin", "recipe_id", "transform", "features"))
        point = candidate["inputs"]
        if not domain_guard(point, contract):
            raise ValueError("received numerical candidate violates input domain")
        token = numerical_input_digest(point)
        if token in seen:
            raise ValueError("duplicate numerical candidate")
        seen.add(token)
        if canonical(candidate["features"]) != canonical(input_features(point)):
            raise ValueError("candidate public input features differ")
        transform, origin = candidate["transform"], candidate["origin"]
        if method == "D":
            recipe = request["artifact"]["bounded_recipe_parameters"][0]
            allowed = (transform in FAMILIES and origin == "SOURCE_CALIBRATED_GUIDANCE" and
                       candidate["recipe_id"] == recipe["recipe_id"])
        elif method == "B":
            allowed = transform in FAMILIES and origin == "HAND_SPECIFIED_PRIOR" and candidate["recipe_id"] is None
        elif method == "A":
            allowed = transform == origin == "NATIVE_TYPED_STRATEGY" and candidate["recipe_id"] is None
        else:
            allowed = candidate["recipe_id"] is None and (
                (transform == "GENERIC_REPLAY_TRANSFORM" and origin == "SOURCE_REPLAY_GENERIC_TRANSFORMATION") or
                (transform == "EXPLICIT_COUNTEREXAMPLE_REPLAY" and origin == "KNOWN_INPUT_REPLAY" and token in replay_digests))
        if not allowed:
            raise ValueError("unapproved numerical candidate provenance or transformation")
        is_replay = method == "C" and origin == "KNOWN_INPUT_REPLAY"
        explicit_replays += int(is_replay)
        if token in excluded and not is_replay:
            raise ValueError("received numerical candidate was explicitly excluded")
    if generation["explicit_replays"] != explicit_replays:
        raise ValueError("explicit replay accounting differs from candidates")
    return deepcopy(generation)


def validate_worker_response(response, request, *, snapshot=None):
    """Bind the actual received rows, frozen state and request identities."""
    _bounded_json(response)
    if request["action"] == "plan":
        keys(response, PLAN_FIELDS)
        _frozen(response)
        if (response["schema"] != "tomolab-compact-candidate-plan-v1" or
                response["artifact_digest"] != request["expected_digest"] or
                response["source_archive_digest"] != request["artifact"]["source_archive_digest"] or
                response["execution_contract_digest"] != digest(request.get("contract") or request["artifact"]["public_input_contract"])):
            raise ValueError("numerical plan artifact or contract identity differs")
        generation = validate_generation(response["generation"], request)
        if response["candidate_digest"] != digest(generation["candidates"]):
            raise ValueError("received candidate digest differs from actual rows")
        snapshot_fields = tuple(name for name in PLAN_FIELDS if name != "generation")+("request_digest",)
        keys(snapshot, snapshot_fields)
        if any(snapshot[name] != response[name] for name in snapshot_fields if name != "request_digest"):
            raise ValueError("frozen plan snapshot differs from received response")
    elif request["action"] == "baseline":
        generation = validate_generation(response, request)
        keys(snapshot, FREEZE_FIELDS)
        _bounded_json(snapshot)
        _frozen(snapshot)
        if snapshot["candidate_digest"] != digest(generation["candidates"]):
            raise ValueError("baseline snapshot digest differs from actual rows")
    else:
        raise ValueError("response validation requires a generation request")
    _bounded_json(snapshot)
    _frozen(snapshot)
    # The worker removes action before dispatch and pins these exact fields.
    if snapshot["request_digest"] != digest({k:v for k,v in request.items() if k != "action"}):
        raise ValueError("execution contract or request identity differs")
    return generation


def meaningful_plan(response):
    """All deterministic plan semantics; timing and transport are separate."""
    result = {name: deepcopy(response[name]) for name in PLAN_FIELDS}
    result["generation"] = {name: deepcopy(value) for name, value in result["generation"].items()
                            if name not in ("wall_seconds", "cpu_seconds")}
    return result


def assert_equivalent_plans(primary, reference):
    if meaningful_plan(primary) != meaningful_plan(reference):
        raise ValueError("primary and reference numerical plan semantics differ")
    return digest(meaningful_plan(primary))
