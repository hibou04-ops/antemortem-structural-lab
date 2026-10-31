"""Algorithm-frozen, target-local online search using public Hypothesis APIs.

A is native @given + target; B/C/D add the same explicit local edit policy.
C adds replay; D only replaces the structural-slot provider with learned edits.
No global policy or Hypothesis example database survives a run.
"""
from copy import deepcopy
import math
import random
import time

from .online_schema import (apply_edit, common_operators, hypothesis_strategy,
                            input_identity, validate_contract, validate_input)
from .schema import digest


class _ShrinkBudgetExhausted(BaseException):
    """Abort native shrinking without claiming an unexecuted predicate false.

    A direct BaseException is deliberately not a Hypothesis test failure, so
    its engine propagates it rather than learning or shrinking an exception.
    """


class OnlinePolicy:
    """Explicit policy state. Only limited feedback can change the next edit."""
    def __init__(self, contract, *, method, seed, budget, mold=None, replays=(), structure=None):
        self.contract, self.method = deepcopy(contract), method.removeprefix("E9_")
        self.rng, self.structure = random.Random(seed), deepcopy(structure or {})
        self.mold = deepcopy(mold) if self.method == "D" else None
        self.replays = [deepcopy(p) for p in replays if validate_input(p, contract)] if self.method in ("C", "D") else []
        self.caps = dict(replay=budget // 5, structure=3 * budget // 10)
        self.used = dict(base=0, replay=0, structure=0)
        self.archive, self.last_feedback = [], None
        self.attempts = 0
        self.operator_rewards = dict.fromkeys(common_operators(contract["kind"]), 1)
        self.guidance_rejected = self.duplicate_guidance = self.guidance_lookups = 0
        self.guidance_not_applicable = 0
        self.used_rules = []
        self.seen = set()

    def state_digest(self):
        return digest(dict(method=self.method, contract=self.contract, rng=self.rng.getstate(),
                           archive=self.archive, last_feedback=self.last_feedback, caps=self.caps,
                           used=self.used, attempts=self.attempts, operator_rewards=self.operator_rewards,
                           seen=sorted(self.seen), used_rules=self.used_rules,
                           mold_digest=self.mold.get("artifact_digest") if self.mold else None))

    def receive(self, point, feedback, *, phase="base", operator=None):
        # Reject accidental widening to evaluator-private outputs.
        allowed = {"status", "input_digest", "coverage", "branch_distance", "exception_type",
                   "exception_location", "contract_checked"}
        if set(feedback) - allowed:
            raise ValueError("policy feedback contains evaluator-private fields")
        self.last_feedback = deepcopy(feedback)
        if feedback["status"] in ("PASS", "FAILURE"):
            row = dict(input=deepcopy(point), feedback=deepcopy(feedback))
            if len(self.archive) >= 32:
                self.archive.pop(0)
            self.archive.append(row)
            if operator in self.operator_rewards:
                self.operator_rewards[operator] += int(feedback["status"] == "FAILURE") + int(bool(feedback.get("coverage")))

    def _local_operator(self):
        operators = list(common_operators(self.contract["kind"]))
        if self.last_feedback and self.last_feedback["status"] == "FAILURE":
            for op in ("delete", "trace_delete", "graph_edge_delete", "adjacent"):
                if op in operators:
                    return op
        if self.last_feedback and self.last_feedback.get("branch_distance") is not None and "boundary" in operators:
            return "boundary"
        return self.rng.choices(operators, weights=[self.operator_rewards[o] for o in operators], k=1)[0]

    def propose(self, base):
        self.attempts += 1
        slot = (self.attempts - 1) % 10
        lane, operator, rule_id, point = "base", None, None, deepcopy(base)
        if self.method in ("C", "D") and slot < 2 and self.replays and self.used["replay"] + 3 <= self.caps["replay"]:
            lane = "replay"
            index = (self.attempts - 1) // 10 * 2 + slot
            point = deepcopy(self.replays[index % len(self.replays)])
            if index >= len(self.replays):
                operator = self._local_operator()
                point = apply_edit(point, operator, self.contract, self.structure)
        elif self.method != "A" and 2 <= slot < 5 and self.used["structure"] + 3 <= self.caps["structure"]:
            lane = "structure"
            if self.archive:
                failures = [r for r in self.archive if r["feedback"]["status"] == "FAILURE"]
                point = deepcopy((failures or self.archive)[-1]["input"])
            if self.method == "D" and self.mold is not None:
                from .online_mold import select_edit
                self.guidance_lookups += 1
                selected = select_edit(self.mold, point, self.contract, self.rng)
                if selected:
                    rule_id = selected["rule_id"]
                    for operator in selected["operators"]:
                        point = apply_edit(point, operator, self.contract, self.structure)
                        if point is None:
                            break
                else:
                    # No applicable source policy: return the slot to native
                    # search rather than granting D another target call.
                    lane, point = "base", deepcopy(base)
                    self.guidance_not_applicable += 1
            else:
                operator = self._local_operator()
                point = apply_edit(point, operator, self.contract, self.structure)
        if point is None or not validate_input(point, self.contract):
            self.guidance_rejected += 1
            return deepcopy(base), "base", None, None, "INVALID_GUIDANCE_RETURNED_TO_BASE"
        if lane != "base" and input_identity(point) in self.seen:
            self.duplicate_guidance += 1
            return deepcopy(base), "base", None, None, "DUPLICATE_GUIDANCE_RETURNED_TO_BASE"
        return point, lane, operator, rule_id, "SELECTED"


def _score(feedback):
    distance = feedback.get("branch_distance")
    return float(len(feedback.get("coverage", []))) + (1 / (1 + distance) if distance is not None else 0)


def _validate_configuration(contract, method, seed, budget, shrink_budget, max_seconds, mold):
    from .online_schema import validate_online_parameters
    return validate_online_parameters(contract, method, seed, budget, shrink_budget, max_seconds, mold)


def _run_online_core(contract, structure, execute, *, method="C", seed=7, budget=48, shrink_budget=8,
                     mold=None, replays=(), max_seconds=30, _started=None):
    """Worker-only search. Its callback receives no Target or Oracle objects."""
    started = time.perf_counter() if _started is None else _started
    from hypothesis import given, target as hypothesis_target, settings, seed as hypothesis_seed
    from hypothesis import Phase, HealthCheck, find
    from hypothesis.errors import NoSuchExample, Unsatisfiable
    contract, method = _validate_configuration(contract, method, seed, budget, shrink_budget, max_seconds, mold)
    discovery_limit = budget - shrink_budget
    policy = OnlinePolicy(contract, method=method, seed=seed, budget=discovery_limit,
                          mold=mold, replays=replays, structure=structure)
    strategy = hypothesis_strategy(contract, structure)
    result = dict(schema="tomolab-online-result-v1", status="COMPLETE", method="E9_"+method,
                  seed=seed, budget=budget, shrink_budget=shrink_budget, contract=deepcopy(contract),
                  mri=structure, observations=[], events=[], private_outcomes=[],
                  target_calls=0, oracle_calls=0, invalid_inputs=0, execution_errors=0, oracle_errors=0, unknown=0,
                  duplicate_candidates=0, confirmed_failures=[], first_confirmed_failure=None,
                  feedback_scope="TARGET_LOCAL_LIMITED_CAST_NO_ORACLE_OUTPUT", allow_release=False,
                  profile="EXPERIMENTAL_PROBE_ONLINE_TARGET_LOCAL", policy_state_reused=False,
                  target_state_reset="FULL_TRACE_ADAPTER_LOCAL_STATE_OR_CALLER_RESPONSIBILITY",
                  target_state_contract="PURE_CALLABLE_OR_REVIEWED_FULL_TRACE_RESET_ADAPTER_REQUIRED",
                  cost=dict(target_seconds=0.0, oracle_seconds=0.0, instrumentation_seconds=0.0,
                            generation_seconds=0.0, matching_seconds=0.0, solver_seconds=0.0,
                            initialization_seconds=time.perf_counter()-started,
                            shrink_seconds=0.0, replay_seconds=0.0, wall_seconds=0.0),
                  shrinking=dict(status="NOT_AVAILABLE", minimality="NOT_CLAIMED", witness=None),
                  hypothesis=dict(engine="native @given + target", database=None, seed=seed,
                                  phases=["generate", "target"], max_examples=budget*4,
                                  mutable_state="EXPLICIT_TARGET_LOCAL_NO_GLOBAL_STATE",
                                  common_public_prior="AUTOMATIC_TARGET_MRI_LITERALS_AND_TYPED_ADJACENCY_SHARED_BY_ABCD",
                                  A="NATIVE_TARGETED_TESTING_WITH_SHARED_PUBLIC_PRIOR", BCD="NATIVE_BASE_WITH_EXPLICIT_ONLINE_EDIT_POLICY"))
    confirmed, seen = set(), set()
    known_replay_identities = {input_identity(p) for p in replays if validate_input(p, contract)}
    first_witness = None
    first_witness_reference = None
    def expired():
        return time.perf_counter()-started >= max_seconds
    def evaluate(point, phase, *, operator=None, rule_id=None, origin="native_hypothesis", track_policy=True, reference=None):
        if result["target_calls"] >= budget or expired():
            return None
        observation = execute(point, phase=phase, reference=reference)
        feedback = observation["feedback"]
        result["target_calls"] += observation["target_calls"]
        result["oracle_calls"] += observation["oracle_calls"]
        for key, value in observation["cost"].items():
            result["cost"][key] += value
        status = feedback["status"]
        result["invalid_inputs"] += status == "INVALID_INPUT"
        result["execution_errors"] += status == "EXECUTION_ERROR"
        result["oracle_errors"] += status == "ORACLE_ERROR"
        result["unknown"] += status == "UNKNOWN"
        row = dict(input=deepcopy(point), status=status, contract=deepcopy(contract), phase=phase,
                   origin=origin, operator=operator, rule_id=rule_id, input_digest=feedback["input_digest"])
        result["observations"].append(row)
        result["events"].append(dict(index=len(result["events"]), phase=phase, origin=origin,
                                    operator=operator, rule_id=rule_id, feedback=deepcopy(feedback),
                                    target_calls=result["target_calls"], oracle_calls=result["oracle_calls"],
                                    seconds=time.perf_counter()-started))
        result["events"][-1]["observation_id"] = observation["observation_id"]
        if track_policy:
            policy.receive(point, feedback, phase=phase, operator=operator)
        return observation
    def confirm(point, first, phase, operator, rule_id, origin):
        nonlocal first_witness, first_witness_reference
        if first["feedback"]["status"] != "FAILURE" or result["target_calls"] + 2 > discovery_limit:
            return
        tick = time.perf_counter()
        replay = [evaluate(point, "confirmation", origin=origin, track_policy=False,
                           reference=first["observation_id"]) for _ in range(2)]
        result["cost"]["replay_seconds"] += time.perf_counter()-tick
        policy.used[phase] += sum(row is not None and row["target_calls"] for row in replay)
        if all(row is not None and row["feedback"]["status"] == "FAILURE" and row["reference_match"] is True for row in replay):
            token = input_identity(point)
            if token not in confirmed:
                confirmed.add(token)
                result["confirmed_failures"].append(dict(input=deepcopy(point), input_digest=token,
                    phase=phase, operator=operator, rule_id=rule_id, origin=origin,
                    source_replay=origin == "source_replay", mechanism="NOT_AUTOMATICALLY_INFERRED"))
                result["confirmed_failures"][-1]["new_input"] = token not in known_replay_identities
            if first_witness is None:
                first_witness = deepcopy(point)
                first_witness_reference = first["observation_id"]
                result["first_confirmed_failure"] = dict(input_digest=token, target_calls=result["target_calls"],
                    oracle_calls=result["oracle_calls"], seconds=time.perf_counter()-started,
                    origin=origin, phase=phase, confirmation_calls=3)
        else:
            result.setdefault("reproduction_mismatches", 0)
            result["reproduction_mismatches"] += 1
    @hypothesis_seed(seed)
    @settings(max_examples=budget*4, database=None, deadline=None, phases=(Phase.generate, Phase.target),
              suppress_health_check=list(HealthCheck), report_multiple_bugs=False)
    @given(strategy)
    def search(base):
        if result["target_calls"] + 3 > discovery_limit or expired():
            return
        tick = time.perf_counter()
        state_before = policy.state_digest()
        point, phase, operator, rule_id, decision = policy.propose(base)
        result["cost"]["matching_seconds"] += time.perf_counter()-tick
        if not validate_input(point, contract):
            result["invalid_inputs"] += 1
            return
        token = input_identity(point)
        if token in seen:
            result["duplicate_candidates"] += 1
            return
        seen.add(token); policy.seen.add(token)
        origin = "source_replay" if phase == "replay" and operator is None else ("source_replay_mutation" if phase == "replay" else ("source_learned_policy" if rule_id else ("target_local_adaptation" if phase == "structure" else "native_hypothesis")))
        first = evaluate(point, phase, operator=operator, rule_id=rule_id, origin=origin)
        if first is None:
            return
        policy.used[phase] += first["target_calls"]
        if rule_id:
            policy.used_rules.append(rule_id)
        hypothesis_target(_score(first["feedback"]), label="public_path_and_literal_distance")
        event = result["events"][-1]
        event.update(selection_decision=decision, base_input_digest=input_identity(base),
                     policy_state_before=state_before)
        confirm(point, first, phase, operator, rule_id, origin)
        event["policy_state_after"] = policy.state_digest()
    try:
        tick = time.perf_counter()
        before = sum(result["cost"][k] for k in ("target_seconds", "oracle_seconds", "instrumentation_seconds", "matching_seconds"))
        search()
        accounted = sum(result["cost"][k] for k in ("target_seconds", "oracle_seconds", "instrumentation_seconds", "matching_seconds")) - before
        result["cost"]["generation_seconds"] += max(0.0, time.perf_counter()-tick-accounted)
    except Unsatisfiable:
        result["status"] = "INCONCLUSIVE_DOMAIN_GENERATION"
    if first_witness is not None and shrink_budget >= 3 and not expired():
        tick = time.perf_counter()
        shrink_start = result["target_calls"]
        native_cap = max(1, (shrink_budget-2)//2)
        native_calls, predicate_cache = 0, {}
        witness = deepcopy(first_witness)
        witness_reference = first_witness_reference
        last_native_failure = None
        def predicate(point):
            nonlocal native_calls, last_native_failure
            token = input_identity(point)
            if token in predicate_cache:
                return predicate_cache[token][0]
            if native_calls >= native_cap or result["target_calls"] + 2 >= budget or expired():
                raise _ShrinkBudgetExhausted()
            native_calls += 1
            row = evaluate(point, "native_shrink", track_policy=False)
            if row is None:
                raise _ShrinkBudgetExhausted()
            is_failure = row["feedback"]["status"] == "FAILURE"
            predicate_cache[token] = (is_failure, row["observation_id"])
            if is_failure:
                last_native_failure = (deepcopy(point), row["observation_id"])
            return is_failure
        native_status = "COMPLETED"
        try:
            candidate = find(strategy, predicate, random=random.Random(seed ^ 0x5A5A),
                             settings=settings(max_examples=native_cap, database=None, deadline=None,
                                               phases=(Phase.generate, Phase.shrink), suppress_health_check=list(HealthCheck)))
            if len(str(candidate)) < len(str(witness)):
                witness = deepcopy(candidate)
                witness_reference = predicate_cache[input_identity(candidate)][1]
        except _ShrinkBudgetExhausted:
            native_status = "BUDGET_EXHAUSTED_INCOMPLETE"
            if last_native_failure is not None and len(str(last_native_failure[0])) < len(str(witness)):
                witness, witness_reference = last_native_failure
        except (NoSuchExample, Unsatisfiable):
            native_status = "NO_NEW_WITNESS_WITHIN_NATIVE_EXAMPLES"
        checked, untested = [], []
        for operator in common_operators(contract["kind"]):
            if operator not in ("delete", "trace_delete", "graph_edge_delete", "boundary", "constantize"):
                continue
            if result["target_calls"] - shrink_start >= shrink_budget-2 or result["target_calls"]+2 >= budget or expired():
                untested.append(operator)
                continue
            point = apply_edit(witness, operator, contract)
            if point is None or point == witness:
                continue
            row = evaluate(point, "delta_shrink", operator=operator, track_policy=False)
            checked.append(operator)
            if row is not None and row["feedback"]["status"] == "FAILURE":
                witness = deepcopy(point)
                witness_reference = row["observation_id"]
        confirmations = [evaluate(witness, "shrink_confirmation", track_policy=False,
                                  reference=witness_reference) for _ in range(2)]
        reproduced = all(row is not None and row["feedback"]["status"] == "FAILURE" for row in confirmations)
        if reproduced:
            reproduced = all(row["reference_match"] is True for row in confirmations)
        result["shrinking"] = dict(status="REPRODUCED" if reproduced else "UNCONFIRMED", witness=witness,
            minimality="BUDGET_BOUNDED_REDUCTION_NOT_MINIMALITY_PROOF", checked_operators=checked,
            unchecked_operators=untested, native_hypothesis_calls=native_calls,
            native_status=native_status, witness_reference_event=witness_reference,
            target_calls=result["target_calls"]-shrink_start, budget=shrink_budget,
            pair_status="AVAILABLE" if any(r["status"] == "PASS" for r in result["observations"]) else "UNAVAILABLE")
        result["cost"]["shrink_seconds"] = time.perf_counter()-tick
    if expired():
        result["status"] = "WALL_LIMIT_REACHED"
    result["scheduler"] = dict(policy="COMMON_C_D_CALL_CAPS_V1", discovery_call_limit=discovery_limit,
        caps=policy.caps, actual=policy.used, guidance_rejected=policy.guidance_rejected,
        duplicate_guidance=policy.duplicate_guidance, learned_lookups=policy.guidance_lookups,
        guidance_not_applicable=policy.guidance_not_applicable,
        learned_rule_uses=policy.used_rules, rejected_slots="RETURNED_TO_NATIVE_BASE_WITHOUT_EXTRA_CALL",
        base_minimum_scope="HALF_OF_DISCOVERY_CALL_BUDGET_IF_EXHAUSTED; confirmation charged to origin lane")
    result["cost"].update(wall_seconds=time.perf_counter()-started, intervals_nested_not_additive=True,
        target_seconds_include_line_tracing=True, wall_limit="COOPERATIVE_BETWEEN_CALLS_NOT_OS_TIMEOUT")
    result["new_valid_inputs"] = len(seen - known_replay_identities)
    result["known_input_identities_observed"] = len(seen & known_replay_identities)
    result["source_replay_calls"] = sum(r["origin"] == "source_replay" for r in result["observations"])
    result["outcome"] = "CONFIRMED_FAILURE" if confirmed else ("INCONCLUSIVE" if result["status"] != "COMPLETE" or result["unknown"] or result["execution_errors"] or result["oracle_errors"] else "NO_CONFIRMED_FAILURE_WITHIN_BUDGET")
    result["receipt_sha256"] = digest(result)
    return result


def run_online(target, oracle, contract, *, method="C", seed=7, budget=48, shrink_budget=8,
               mold=None, replays=(), max_seconds=30, mode="structural"):
    """Fresh data-only search process; trusted Target/Oracle stay on the host.

    The existing reviewed process loader, allowlisted copies and sanitized
    environment prevent Hypothesis from implicitly mining evaluator modules
    for constants. This is cooperative logical isolation, not an OS sandbox.
    """
    started = time.perf_counter()
    import inspect
    from .online_boundary import OnlineBoundary
    from .online_observe import inspect_target, observe
    contract, method = _validate_configuration(contract, method, seed, budget, shrink_budget, max_seconds, mold)
    for fn in (target, oracle):
        if not callable(fn) or inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None)):
            raise ValueError("reviewed synchronous non-generator callables required")
    structure = inspect_target(target, contract, mode=mode)
    if not isinstance(replays, (list, tuple)) or len(replays) > 2048:
        raise ValueError("bounded approved replay input list required")
    approved_replays = [p for p in replays if validate_input(p, contract)] if method in ("C", "D") else []
    rejected_replays = len(replays)-len(approved_replays) if method in ("C", "D") else 0
    allowed_phases = {"base", "structure", "replay", "confirmation", "native_shrink", "delta_shrink", "shrink_confirmation"}
    host_rows, counters = [], dict(target_calls=0, oracle_calls=0)
    def execute(point, *, phase, reference):
        if phase not in allowed_phases:
            raise ValueError("unsupported evaluator request phase")
        if max(counters.values()) >= budget or time.perf_counter()-started >= max_seconds:
            raise ValueError("host independently enforces the fixed total execution budget")
        if reference is not None:
            if type(reference) is not int or not 0 <= reference < len(host_rows) or host_rows[reference]["input_digest"] != input_identity(point):
                raise ValueError("reproduction reference must be a prior evaluation of the same input")
        observation = observe(target, oracle, point, contract, structure, tracing=mode == "structural")
        for key in counters:
            counters[key] += observation[key]
        observation_id = len(host_rows)
        reference_match = (observation.get("semantic_digest") == host_rows[reference]["semantic_digest"]
                           if reference is not None else None)
        host_rows.append(dict(input=deepcopy(point), input_digest=input_identity(point), phase=phase,
            feedback=deepcopy(observation["feedback"]), private_outcome=observation["private_outcome"],
            semantic_digest=observation.get("semantic_digest"), target_calls=observation["target_calls"],
            oracle_calls=observation["oracle_calls"], cost=observation["cost"],
            reference=reference, reference_match=reference_match))
        # Output-derived hashes and raw values never enter this envelope.
        return dict(feedback=observation["feedback"], target_calls=observation["target_calls"],
                    oracle_calls=observation["oracle_calls"], cost=observation["cost"],
                    observation_id=observation_id, reference_match=reference_match)
    config = dict(contract=contract, structure=structure, method=method, seed=seed, budget=budget,
                  shrink_budget=shrink_budget, mold=mold, replays=approved_replays,
                  max_seconds=max_seconds, _started=started)
    boundary_receipt, inventory = None, None
    try:
        with OnlineBoundary(timeout=max_seconds+5) as boundary:
            boundary_receipt = boundary.receipt
            result, inventory = boundary.run(config, execute)
            boundary_receipt = boundary.receipt
            if not isinstance(result, dict) or result.get("private_outcomes") != []:
                raise ValueError("the search process cannot return private evaluator outcomes")
            if any(result.get(key) != value for key, value in counters.items()):
                raise ValueError("search result does not match actual host entry counters")
            if len(result.get("events", [])) != len(host_rows) or len(result.get("observations", [])) != len(host_rows):
                raise ValueError("online result omits actual host evaluations")
            for index, (row, event, actual) in enumerate(zip(result["observations"], result["events"], host_rows)):
                if row["input_digest"] != actual["input_digest"] or input_identity(row["input"]) != actual["input_digest"] or row["status"] != actual["feedback"]["status"] or row["contract"] != contract or row["phase"] != actual["phase"] or event["feedback"] != actual["feedback"] or event["phase"] != actual["phase"] or event.get("observation_id") != index:
                    raise ValueError("online result changed its observed input or feedback")
            verified, first_verified = set(), None
            for index, actual in enumerate(host_rows[:-2]):
                if actual["phase"] not in ("base", "structure", "replay") or actual["feedback"]["status"] != "FAILURE":
                    continue
                repeated = host_rows[index+1:index+3]
                if all(row["phase"] == "confirmation" and row["reference"] == index and row["reference_match"] is True and row["feedback"]["status"] == "FAILURE" for row in repeated):
                    verified.add(actual["input_digest"])
                    if first_verified is None:
                        first_verified = (actual["input_digest"], sum(r["target_calls"] for r in host_rows[:index+3]), sum(r["oracle_calls"] for r in host_rows[:index+3]))
            claims = result.get("confirmed_failures", [])
            if not isinstance(claims, list) or any(row["input_digest"] != input_identity(row["input"]) or row["input_digest"] not in verified for row in claims) or {row["input_digest"] for row in claims} != verified:
                raise ValueError("confirmed failure claims lack three matching actual host executions")
            first = result.get("first_confirmed_failure")
            if (first is None) != (first_verified is None) or first is not None and (first["input_digest"], first["target_calls"], first["oracle_calls"]) != first_verified:
                raise ValueError("first confirmation counters differ from the host execution ledger")
            shrinking = result.get("shrinking", {})
            if shrinking.get("status") == "REPRODUCED":
                reference = shrinking.get("witness_reference_event")
                if type(reference) is not int or not 0 <= reference < len(host_rows) or input_identity(shrinking["witness"]) != host_rows[reference]["input_digest"] or not all(row["phase"] == "shrink_confirmation" and row["reference"] == reference and row["reference_match"] is True and row["feedback"]["status"] == "FAILURE" for row in host_rows[-2:]):
                    raise ValueError("shrink reproduction lacks its original host witness and matching replays")
            shutdown_started = time.perf_counter()
        result["cost"]["process_shutdown_seconds"] = time.perf_counter()-shutdown_started
    except Exception as error:
        # No retries or unrecorded partial calls: the host remains authoritative
        # even if the protocol or generator fails after executing a candidate.
        result = dict(schema="tomolab-online-result-v1", status="INCONCLUSIVE_BOUNDARY_ERROR",
            outcome="INCONCLUSIVE", method="E9_"+method, seed=seed, budget=budget,
            shrink_budget=shrink_budget, contract=contract, mri=structure, **counters,
            error_type=type(error).__name__, observations=[dict(input=r["input"],
                input_digest=r["input_digest"], status=r["feedback"]["status"], contract=contract,
                phase=r["phase"], origin="BOUNDARY_ABORT_HOST_RETAINED", operator=None, rule_id=None) for r in host_rows],
            events=[dict(index=i, phase=r["phase"], feedback=r["feedback"], observation_id=i) for i, r in enumerate(host_rows)],
            private_outcomes=[], confirmed_failures=[], first_confirmed_failure=None,
            invalid_inputs=sum(r["feedback"]["status"] == "INVALID_INPUT" for r in host_rows),
            execution_errors=sum(r["feedback"]["status"] == "EXECUTION_ERROR" for r in host_rows),
            oracle_errors=sum(r["feedback"]["status"] == "ORACLE_ERROR" for r in host_rows),
            unknown=sum(r["feedback"]["status"] == "UNKNOWN" for r in host_rows),
            cost={key: sum(r["cost"][key] for r in host_rows) for key in ("target_seconds", "oracle_seconds", "instrumentation_seconds")},
            shrinking=dict(status="INCOMPLETE_BOUNDARY_ERROR", minimality="NOT_CLAIMED", witness=None),
            scheduler={}, new_valid_inputs=0, source_replay_calls=0, duplicate_candidates=0,
            policy_state_reused=False, target_state_reset="CALLER_RESPONSIBILITY", allow_release=False)
    result["private_outcomes"] = [dict(event=i, outcome=r["private_outcome"], semantic_digest=r["semantic_digest"])
                                    for i, r in enumerate(host_rows)]
    result["boundary"] = dict(boundary_receipt or {}, **(inventory or {}),
        transferred="PUBLIC_CONTRACT_MRI_MOLD_REPLAYS_LIMITED_CAST_AND_REPRODUCTION_BOOLEAN",
        target_code_transferred=False, oracle_code_transferred=False, oracle_values_transferred=False,
        oracle_hashes_transferred=False, full_archive_transferred=False,
        worker_lifecycle="FRESH_PER_RUN", target_execution="TRUSTED_HOST_NOT_SANDBOXED")
    result["boundary"]["transmitted_data"] = result["boundary"]["transferred"]
    result["replay_inputs_rejected_before_transport"] = rejected_replays
    result["cost"].update(wall_seconds=time.perf_counter()-started, includes_worker_startup_import_ipc_shutdown=True)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = digest(result)
    return result
