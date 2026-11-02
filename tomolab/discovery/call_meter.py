"""Hard, per-arm limits on designated Target/Oracle callable entries.

This host-only meter is shared by evaluation phases, not by competing arms.
It counts actual entries before invocation, including captured exceptions.
It is not an OS sandbox, a wall-time interrupt, or a measurement of internal
recursive calls made inside an already-entered reviewed callable.
"""
from copy import deepcopy
import re
import inspect
import math
import threading
import time

from .online_schema import input_identity, validate_input
from .schema import digest


class HardBudgetExhausted(RuntimeError):
    """No Target, Oracle or reset was entered for this rejected request."""


class ResetNotVerified(RuntimeError):
    """The reset was attempted; the Target and Oracle were not entered."""


class MeterReentryError(RuntimeError):
    """An active meter cannot recursively admit another evaluation."""


class PolicyBudgetExhausted(HardBudgetExhausted):
    """A policy reservation rejected a request before reset or callable entry."""


class HardCallMeter:
    def __init__(self, target_budget, oracle_budget=None, *, arm_id, scope="EVALUATION_ALL_PHASES", reset_per_entry=False):
        if oracle_budget is None: oracle_budget=target_budget
        if any(type(v) is not int or not 0 <= v <= 10000 for v in (target_budget,oracle_budget)):
            raise ValueError("bounded exact integer Target/Oracle budgets required")
        if type(arm_id) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}",arm_id) is None:
            raise ValueError("explicit bounded arm identity required")
        if scope not in ("EVALUATION_ALL_PHASES","PREPARATION","DEVELOPMENT_DIAGNOSTIC"):
            raise ValueError("explicit accounting scope required")
        if type(reset_per_entry) is not bool:
            raise ValueError("reset policy must be an exact boolean")
        self.reset_per_entry=reset_per_entry
        self.target_budget,self.oracle_budget=target_budget,oracle_budget
        self.arm_id,self.scope=arm_id,scope
        self.target_calls_used=self.oracle_calls_used=0
        self.reset_calls_used=self.fresh_reset_count=self.reset_failures=0
        self.budget_blocked_requests=self.unknown_observations=0
        self.unresolved_measurement_events=0
        self.reentry_rejections=0
        self.observation_wall_seconds=0.0
        self.events=[]
        self._lock=threading.RLock()
        self._active=False
        self._active_policy=None
        self._policy_counts={name:dict(actual_target_calls=0,actual_oracle_calls=0,
            actual_reset_calls=0,actual_fresh_reset_count=0,reset_failures=0)
            for name in ("C","D","UNATTRIBUTED")}
        self._policy_reservation=None
        self._last_completed_policy_reservation=None
        self.policy_budget_blocked_requests=0
        self._started=time.perf_counter()

    @staticmethod
    def _policy_identity(policy_id):
        value="UNATTRIBUTED" if policy_id is None else policy_id
        if type(value) is not str or value not in ("C","D","UNATTRIBUTED"):
            raise ValueError("explicit policy identity must be C, D or UNATTRIBUTED")
        return value

    def configure_policy_reservation(self,*,budget,epsilon_static_floor=0.5):
        """Reserve C capacity for one run, including confirmations and shrinking.

        The floor preserves available capacity; it does not promise that an
        early-stopped or finite-domain run actually enters that many calls.
        Existing totals are retained and become this run's accounting offsets.
        """
        if type(budget) is not int or not 0<=budget<=10000:
            raise ValueError("bounded exact per-run policy budget required")
        if (type(epsilon_static_floor) not in (int,float) or not math.isfinite(epsilon_static_floor)
            or not 0<=epsilon_static_floor<=1):
            raise ValueError("epsilon_static_floor must be finite and in [0,1]")
        with self._lock:
            self._reject_active_policy_change("policy_reservation")
            if self._policy_reservation is not None:
                raise ValueError("release the existing policy reservation before configuring another run")
            self.require_capacity(budget,budget,phase="policy_reservation_admission")
            static=math.ceil(epsilon_static_floor*budget)
            learned=budget-static
            self._policy_reservation=dict(budget=budget,epsilon_static_floor=float(epsilon_static_floor),
                reserved_static_calls=static,initial_learned_cap=learned,
                learned_target_cap=learned,learned_oracle_cap=learned,
                baseline_target_calls=self.target_calls_used,baseline_oracle_calls=self.oracle_calls_used,
                baseline_policy_counts=deepcopy(self._policy_counts),
                circuit_breaker_triggered=False,circuit_breaker_reason=None,
                reclaimed_learned_target_calls=0,reclaimed_learned_oracle_calls=0,
                scope="ALL_RUN_PHASES_INCLUDING_CONFIRMATION_AND_SHRINK",
                floor_semantics="CAPACITY_RESERVED_NOT_ACTUAL_MINIMUM_EXECUTION_GUARANTEE")
            return self._policy_reservation_snapshot()

    def _reject_active_policy_change(self,phase):
        if self._active:
            self.reentry_rejections+=1
            self.note_unresolved(phase=phase,reason="REENTRANT_POLICY_MUTATION_REJECTED_BEFORE_ENTRY")
            raise MeterReentryError("REENTRANT_POLICY_MUTATION_REJECTED_NO_EXECUTION")

    def _policy_run_counts(self,policy_id):
        reservation=self._policy_reservation
        if reservation is None:
            return deepcopy(self._policy_counts[policy_id])
        return {key:value-reservation["baseline_policy_counts"][policy_id][key]
            for key,value in self._policy_counts[policy_id].items()}

    def _policy_capacity(self,policy_id,target_calls,oracle_calls):
        reservation=self._policy_reservation
        if reservation is None:
            return True
        if policy_id=="UNATTRIBUTED":
            raise ValueError("configured mixed policy reservations require C or D attribution")
        if (self.target_calls_used-reservation["baseline_target_calls"]+target_calls>reservation["budget"]
            or self.oracle_calls_used-reservation["baseline_oracle_calls"]+oracle_calls>reservation["budget"]):
            return False
        if policy_id=="D":
            used=self._policy_run_counts("D")
            if (used["actual_target_calls"]+target_calls>reservation["learned_target_cap"]
                or used["actual_oracle_calls"]+oracle_calls>reservation["learned_oracle_cap"]):
                return False
        return True

    def can_afford_policy(self,policy_id,target_calls=1,oracle_calls=1):
        """Read current admission capacity without charging a proposal as a call."""
        policy_id=self._policy_identity(policy_id)
        with self._lock:
            return (self.can_afford(target_calls,oracle_calls)
                    and self._policy_capacity(policy_id,target_calls,oracle_calls))

    def _require_policy_capacity(self,policy_id,target_calls=1,oracle_calls=1,*,phase):
        self.require_capacity(target_calls,oracle_calls,phase=phase)
        if not self._policy_capacity(policy_id,target_calls,oracle_calls):
            self.budget_blocked_requests+=1
            self.policy_budget_blocked_requests+=1
            self.events.append(dict(kind="NO_EXECUTION_POLICY_RESERVATION",phase=phase,policy_id=policy_id,
                target_calls=0,oracle_calls=0,reset_calls=0,unknown=False))
            raise PolicyBudgetExhausted("POLICY_RESERVATION_NO_RESET_OR_CALLABLE_ENTRY")

    def trigger_policy_circuit_breaker(self,*,reason):
        """Freeze new D entries; unspent learned capacity is now available to C.

        The host scheduler owns the evidence-based trigger condition. This
        method enforces its decision and records actual unspent capacity.
        """
        if type(reason) is not str or not 1<=len(reason)<=160:
            raise ValueError("bounded explicit circuit breaker reason required")
        with self._lock:
            self._reject_active_policy_change("policy_circuit_breaker")
            reservation=self._policy_reservation
            if reservation is None:
                raise ValueError("configure a policy reservation before triggering its breaker")
            if not reservation["circuit_breaker_triggered"]:
                used=self._policy_run_counts("D")
                reservation["reclaimed_learned_target_calls"]=max(0,reservation["learned_target_cap"]-used["actual_target_calls"])
                reservation["reclaimed_learned_oracle_calls"]=max(0,reservation["learned_oracle_cap"]-used["actual_oracle_calls"])
                reservation["learned_target_cap"]=used["actual_target_calls"]
                reservation["learned_oracle_cap"]=used["actual_oracle_calls"]
                reservation["circuit_breaker_triggered"]=True
                reservation["circuit_breaker_reason"]=reason
            return self._policy_reservation_snapshot()

    def _policy_reservation_snapshot(self):
        if self._policy_reservation is None:
            return None
        value=deepcopy(self._policy_reservation)
        value["active"]=True
        value["actual_policy_calls"]={name:self._policy_run_counts(name) for name in ("C","D","UNATTRIBUTED")}
        value["remaining_target_calls"]=max(0,value["budget"]-(self.target_calls_used-value["baseline_target_calls"]))
        value["remaining_oracle_calls"]=max(0,value["budget"]-(self.oracle_calls_used-value["baseline_oracle_calls"]))
        value["remaining_budget_policy"]="C" if value["circuit_breaker_triggered"] else "MIXED_WITH_STATIC_RESERVATION"
        return value

    def release_policy_reservation(self):
        """Close one run's reservation without erasing entries or its receipt.

        The host captures its run snapshot before releasing enforcement. A
        closed receipt remains available when this meter is reused later.
        """
        with self._lock:
            self._reject_active_policy_change("policy_reservation_release")
            if self._policy_reservation is None:
                return None
            receipt=self._policy_reservation_snapshot()
            receipt["active"]=False
            self._last_completed_policy_reservation=deepcopy(receipt)
            self._policy_reservation=None
            return receipt

    def _policy_accounting_snapshot(self):
        value=deepcopy(self._policy_counts)
        failures={name:set() for name in value}
        for name,row in value.items():
            row.update(complete_observations=0,unknown_observations=0,unresolved_measurement_events=0)
        for event in self.events:
            name=event.get("policy_id","UNATTRIBUTED")
            row=value[name]
            if event["kind"]=="ACTUAL_OBSERVATION":
                row["unknown_observations"]+=int(event["unknown"])
                complete=(event["target_calls"]==1 and event["oracle_calls"]==1 and not event["unknown"])
                row["complete_observations"]+=int(complete)
                if complete and event.get("status")=="FAILURE":
                    failures[name].add(event["input_digest"])
            elif event["kind"]=="UNRESOLVED_MEASUREMENT_NO_NEW_EXECUTION":
                row["unresolved_measurement_events"]+=1
        for name,row in value.items():
            row["observed_failure_input_digests"]=sorted(failures[name])
            row["observed_unique_failure_inputs"]=len(failures[name])
            row["failure_identity_scope"]="VALIDATED_OBSERVED_INPUTS_NOT_CONFIRMED_DEFECT_PHENOTYPES"
        return value

    def can_afford(self,target_calls=1,oracle_calls=1):
        if any(type(v) is not int or v<0 for v in (target_calls,oracle_calls)):
            raise ValueError("nonnegative exact requested costs required")
        with self._lock:
            return (self.target_calls_used+target_calls<=self.target_budget
                    and self.oracle_calls_used+oracle_calls<=self.oracle_budget)

    def require_capacity(self,target_calls=1,oracle_calls=1,*,phase="evaluation"):
        with self._lock:
            if not self.can_afford(target_calls,oracle_calls):
                self.budget_blocked_requests+=1
                self.events.append(dict(kind="NO_EXECUTION_BUDGET_EXHAUSTED",phase=phase,
                    target_calls=0,oracle_calls=0,reset_calls=0,unknown=False,
                    policy_id=self._active_policy or "UNATTRIBUTED"))
                raise HardBudgetExhausted("NO_EXECUTION_BUDGET_EXHAUSTED")

    def evaluate(self,target,oracle,point,contract,structure=None,*,reset=None,
                 tracing=True,trace_target=None,phase="evaluation",policy_id=None):
        """One serial observed pair with atomic admission before any entry.

        Invalid inputs do not spend a reset or callable entry. A failed reset
        remains an unresolved event, and never becomes a PASS observation.
        """
        from .online_observe import observe
        if type(phase) is not str or not 1 <= len(phase) <= 128:
            raise ValueError("bounded phase identity required")
        policy_id=self._policy_identity(policy_id)
        if reset is not None and not callable(reset):
            raise ValueError("reviewed reset must be a host callable")
        for fn in (target,oracle):
            if (not callable(fn) or inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn)
                or inspect.isasyncgenfunction(fn) or inspect.iscoroutinefunction(getattr(fn,"__call__",None))):
                raise ValueError("reviewed synchronous non-generator callables required")
        if not validate_input(point,contract):
            return observe(target,oracle,point,contract,structure,tracing=tracing,trace_target=trace_target)
        if not callable(target) or not callable(oracle):
            raise ValueError("reviewed Target and Oracle callables required")
        if self.reset_per_entry:
            if reset is None:
                raise ValueError("per-entry reset requires an explicit reviewed callback")
            return self._evaluate_per_entry(target,oracle,point,contract,structure,reset=reset,
                tracing=tracing,trace_target=trace_target,phase=phase,policy_id=policy_id)
        token=input_identity(point)
        with self._lock:
            if self._active:
                self.reentry_rejections+=1
                self.note_unresolved(phase=phase,reason="REENTRANT_EVALUATION_REJECTED_BEFORE_ENTRY")
                raise MeterReentryError("REENTRANT_EVALUATION_REJECTED_NO_EXECUTION")
            self._require_policy_capacity(policy_id,phase=phase)
            self._active=True
            self._active_policy=policy_id
            tick=time.perf_counter()
            before=(self.target_calls_used,self.oracle_calls_used)
            reentries_before=self.reentry_rejections
            unresolved_before=self.unresolved_measurement_events
            try:
                if reset is not None:
                    self.reset_calls_used+=1
                    self._policy_counts[policy_id]["actual_reset_calls"]+=1
                    interrupted=None
                    try:
                        okay=reset() is True
                    except BaseException as error:
                        okay=False
                        if not isinstance(error,Exception): interrupted=error
                    # Even a callback swallowing the rejection cannot make a
                    # violated measurement contract into a verified reset.
                    okay=(okay and self.reentry_rejections==reentries_before
                          and self.unresolved_measurement_events==unresolved_before)
                    if not okay:
                        self.reset_failures+=1
                        self._policy_counts[policy_id]["reset_failures"]+=1
                        self.events.append(dict(kind="UNKNOWN_RESET_NOT_VERIFIED",phase=phase,input_digest=token,
                            target_calls=0,oracle_calls=0,reset_calls=1,fresh_reset_count=0,unknown=True,policy_id=policy_id))
                        if interrupted is not None: raise interrupted
                        raise ResetNotVerified("RESET_NOT_VERIFIED_NO_TARGET_OR_ORACLE_ENTRY")
                    self.fresh_reset_count+=1
                    self._policy_counts[policy_id]["actual_fresh_reset_count"]+=1
                entered={"target_calls":0,"oracle_calls":0}
                def target_entry(value):
                    if entered["target_calls"]:
                        self.note_unresolved(phase=phase,reason="OBSERVER_DUPLICATE_TARGET_ENTRY_REJECTED")
                        raise ValueError("OBSERVER_SINGLE_ENTRY_CONTRACT_VIOLATED")
                    self._require_policy_capacity(policy_id,1,0,phase=phase)
                    self.target_calls_used+=1;entered["target_calls"]+=1
                    self._policy_counts[policy_id]["actual_target_calls"]+=1
                    return target(value)
                def oracle_entry(value):
                    if entered["oracle_calls"]:
                        self.note_unresolved(phase=phase,reason="OBSERVER_DUPLICATE_ORACLE_ENTRY_REJECTED")
                        raise ValueError("OBSERVER_SINGLE_ENTRY_CONTRACT_VIOLATED")
                    self._require_policy_capacity(policy_id,0,1,phase=phase)
                    self.oracle_calls_used+=1;entered["oracle_calls"]+=1
                    self._policy_counts[policy_id]["actual_oracle_calls"]+=1
                    return oracle(value)
                observation=None
                validated=False
                try:
                    inspected=target if trace_target is None else trace_target
                    observation=observe(target_entry,oracle_entry,point,contract,structure,
                                        tracing=tracing,trace_target=inspected)
                    if any(entered[name]!=1 or type(observation[name]) is not int or observation[name]!=entered[name] for name in entered):
                        raise ValueError("observed increments differ from actual metered entries")
                    if self.reentry_rejections!=reentries_before or self.unresolved_measurement_events!=unresolved_before:
                        observation["feedback"]["status"]="EXECUTION_ERROR"
                    validated=True
                    self.unknown_observations+=int(observation["feedback"]["status"] in ("UNKNOWN","ORACLE_ERROR","EXECUTION_ERROR"))
                    return observation
                finally:
                    status=observation["feedback"]["status"] if validated else "UNKNOWN_MEASUREMENT_ERROR"
                    if not validated: self.unknown_observations+=1
                    self.events.append(dict(kind="ACTUAL_OBSERVATION",phase=phase,input_digest=token,
                        target_calls=self.target_calls_used-before[0],oracle_calls=self.oracle_calls_used-before[1],
                        reset_calls=int(reset is not None),fresh_reset_count=int(reset is not None),
                        status=status,unknown=status in ("UNKNOWN","ORACLE_ERROR","EXECUTION_ERROR","UNKNOWN_MEASUREMENT_ERROR"),policy_id=policy_id))
            finally:
                self.observation_wall_seconds+=time.perf_counter()-tick
                self._active=False
                self._active_policy=None

    def _evaluate_per_entry(self,target,oracle,point,contract,structure,*,reset,tracing,trace_target,phase,policy_id):
        """Reset separately before each actual Target and Oracle entry.

        A partial pair is retained as unresolved. A failed Oracle reset never
        fabricates an Oracle entry or rewrites an already executed Target.
        """
        from .online_observe import observe
        token=input_identity(point)
        with self._lock:
            if self._active:
                self.reentry_rejections+=1
                self.note_unresolved(phase=phase,reason="REENTRANT_EVALUATION_REJECTED_BEFORE_ENTRY")
                raise MeterReentryError("REENTRANT_EVALUATION_REJECTED_NO_EXECUTION")
            self._require_policy_capacity(policy_id,phase=phase)
            self._active=True
            self._active_policy=policy_id
            tick=time.perf_counter()
            before=(self.target_calls_used,self.oracle_calls_used,self.reset_calls_used,self.fresh_reset_count)
            reentries_before=self.reentry_rejections
            unresolved_before=self.unresolved_measurement_events
            entered={"target_calls":0,"oracle_calls":0}
            reset_failed=False
            validated=False
            observation=None

            def fresh_reset():
                nonlocal reset_failed
                if reset_failed:
                    raise ResetNotVerified("PREVIOUS_ENTRY_RESET_FAILED")
                self.reset_calls_used+=1
                self._policy_counts[policy_id]["actual_reset_calls"]+=1
                interrupted=None
                try:
                    okay=reset() is True
                except BaseException as error:
                    okay=False
                    if not isinstance(error,Exception):interrupted=error
                okay=(okay and self.reentry_rejections==reentries_before
                      and self.unresolved_measurement_events==unresolved_before)
                if not okay:
                    reset_failed=True
                    self.reset_failures+=1
                    self._policy_counts[policy_id]["reset_failures"]+=1
                    if interrupted is not None:raise interrupted
                    raise ResetNotVerified("ENTRY_RESET_NOT_VERIFIED_NO_CALLABLE_ENTRY")
                self.fresh_reset_count+=1
                self._policy_counts[policy_id]["actual_fresh_reset_count"]+=1

            def entry(fn,key,value):
                if entered[key]:
                    self.note_unresolved(phase=phase,reason="OBSERVER_DUPLICATE_ENTRY_REJECTED")
                    raise ValueError("OBSERVER_SINGLE_ENTRY_CONTRACT_VIOLATED")
                self._require_policy_capacity(policy_id,int(key=="target_calls"),int(key=="oracle_calls"),phase=phase)
                fresh_reset()
                entered[key]+=1
                if key=="target_calls":
                    self.target_calls_used+=1
                    self._policy_counts[policy_id]["actual_target_calls"]+=1
                else:
                    self.oracle_calls_used+=1
                    self._policy_counts[policy_id]["actual_oracle_calls"]+=1
                return fn(value)

            try:
                inspected=target if trace_target is None else trace_target
                observation=observe(lambda value:entry(target,"target_calls",value),
                    lambda value:entry(oracle,"oracle_calls",value),point,contract,structure,
                    tracing=tracing,trace_target=inspected)
                if reset_failed:
                    raise ResetNotVerified("PAIR_INCOMPLETE_AFTER_ENTRY_RESET_FAILURE")
                if any(entered[name]!=1 or type(observation[name]) is not int or observation[name]!=entered[name] for name in entered):
                    raise ValueError("observed increments differ from actual metered entries")
                if self.reentry_rejections!=reentries_before or self.unresolved_measurement_events!=unresolved_before:
                    observation["feedback"]["status"]="EXECUTION_ERROR"
                validated=True
                return observation
            finally:
                status=observation["feedback"]["status"] if validated else "UNKNOWN_MEASUREMENT_ERROR"
                unknown=status in ("UNKNOWN","ORACLE_ERROR","EXECUTION_ERROR","UNKNOWN_MEASUREMENT_ERROR")
                self.unknown_observations+=int(unknown)
                self.events.append(dict(kind="ACTUAL_OBSERVATION",phase=phase,input_digest=token,
                    target_calls=self.target_calls_used-before[0],oracle_calls=self.oracle_calls_used-before[1],
                    reset_calls=self.reset_calls_used-before[2],fresh_reset_count=self.fresh_reset_count-before[3],
                    status=status,unknown=unknown,reset_per_entry=True,policy_id=policy_id))
                self.observation_wall_seconds+=time.perf_counter()-tick
                self._active=False
                self._active_policy=None

    def note_unresolved(self,*,phase,reason):
        if type(phase) is not str or type(reason) is not str or not 1<=len(phase)<=128 or not 1<=len(reason)<=160:
            raise ValueError("bounded unresolved event identity required")
        with self._lock:
            self.unresolved_measurement_events+=1
            self.events.append(dict(kind="UNRESOLVED_MEASUREMENT_NO_NEW_EXECUTION",phase=phase,reason=reason,
                                    target_calls=0,oracle_calls=0,reset_calls=0,unknown=True,
                                    policy_id=self._active_policy or "UNATTRIBUTED"))

    def snapshot(self):
        with self._lock:
            phases={}
            for row in self.events:
                phase=phases.setdefault(row["phase"],dict(target_calls_used=0,oracle_calls_used=0,
                    reset_calls_used=0,fresh_reset_count=0,no_execution_budget_requests=0,unresolved_events=0))
                phase["target_calls_used"]+=row["target_calls"]
                phase["oracle_calls_used"]+=row["oracle_calls"]
                phase["reset_calls_used"]+=row["reset_calls"]
                phase["fresh_reset_count"]+=row.get("fresh_reset_count",0)
                phase["no_execution_budget_requests"]+=row["kind"]=="NO_EXECUTION_BUDGET_EXHAUSTED"
                phase["unresolved_events"]+=row["unknown"]
            value=dict(schema="tomolab-hard-call-meter-v1",arm_id=self.arm_id,scope=self.scope,
                target_budget=self.target_budget,oracle_budget=self.oracle_budget,
                target_calls_used=self.target_calls_used,oracle_calls_used=self.oracle_calls_used,
                reset_calls_used=self.reset_calls_used,fresh_reset_count=self.fresh_reset_count,
                reset_failures=self.reset_failures,unknown_observations=self.unknown_observations,
                unresolved_measurement_events=self.unresolved_measurement_events,
                reentry_rejections=self.reentry_rejections,
                budget_blocked_requests=self.budget_blocked_requests,
                unused_target_calls=self.target_budget-self.target_calls_used,
                unused_oracle_calls=self.oracle_budget-self.oracle_calls_used,
                phases=phases,events=deepcopy(self.events),observation_wall_seconds=self.observation_wall_seconds,
                meter_lifetime_wall_seconds=time.perf_counter()-self._started,
                count_scope="DESIGNATED_HOST_CALLABLE_ENTRIES_NOT_INTERNAL_RECURSION",
                reset_per_entry=self.reset_per_entry,
                reset_scope="ACTUAL_REVIEWED_CALLBACK_ATTEMPTS_AND_TRUE_RETURNS_NOT_UNIVERSAL_RESET_PROOF")
            value["policy_accounting"]=self._policy_accounting_snapshot()
            value["policy_reservation"]=self._policy_reservation_snapshot()
            value["policy_reservation_active"]=self._policy_reservation is not None
            value["last_completed_policy_reservation"]=deepcopy(self._last_completed_policy_reservation)
            value["policy_budget_blocked_requests"]=self.policy_budget_blocked_requests
            value["policy_attribution_scope"]="EXPLICIT_HOST_TAGGED_ACTUAL_CALLABLE_ENTRIES_NOT_SCHEDULED_PROPOSALS"
            value["meter_sha256"]=digest(value)
            return value


def independent_arm_meters(arm_ids,*,target_budget,oracle_budget=None,reset_per_entry=False):
    if type(arm_ids) not in (list,tuple) or not 1 <= len(arm_ids) <= 32 or len(set(arm_ids))!=len(arm_ids):
        raise ValueError("bounded distinct comparison arm IDs required")
    return {arm:HardCallMeter(target_budget,oracle_budget,arm_id=arm,reset_per_entry=reset_per_entry) for arm in arm_ids}


def parity_receipt(meters,*,preparation_cost_ledger):
    """Budget parity and observed spending, with no dummy-fill guarantee."""
    if type(meters) is not dict or not 2 <= len(meters) <= 32 or any(type(v) is not HardCallMeter for v in meters.values()):
        raise ValueError("at least two concrete independent arm meters required")
    if len({id(meter) for meter in meters.values()})!=len(meters):
        raise ValueError("competing arms must not consume one shared instance")
    if any(key!=meter.arm_id for key,meter in meters.items()):
        raise ValueError("arm ledger identity mismatch")
    budgets={(m.target_budget,m.oracle_budget) for m in meters.values()}
    if len(budgets)!=1: raise ValueError("all comparison arms require identical hard budgets")
    if len({m.reset_per_entry for m in meters.values()})!=1:
        raise ValueError("comparison arms require identical reset policies")
    if type(preparation_cost_ledger) is not dict or not preparation_cost_ledger:
        raise ValueError("explicit separate preparation cost ledger required")
    rows={name:m.snapshot() for name,m in meters.items()}
    unresolved=sum(row["reset_failures"]+row["unknown_observations"]+row["unresolved_measurement_events"] for row in rows.values())
    actual_equal=len({(r["target_calls_used"],r["oracle_calls_used"]) for r in rows.values()})==1
    measurements_present=all(r["target_calls_used"]>0 and r["oracle_calls_used"]>0 for r in rows.values())
    status="HOLD_UNRESOLVED_OBSERVATION" if unresolved else "PASS" if measurements_present else "HOLD_NO_EVALUATIONS"
    value=dict(schema="tomolab-hard-call-parity-v1",status=status,
        independent_per_arm_budget=True,identical_hard_caps=True,actual_calls_equal=actual_equal,
        measurements_present_in_all_arms=measurements_present,
        arms=rows,unresolved_events=unresolved,preparation_cost_ledger=deepcopy(preparation_cost_ledger),
        budget_exhaustion="NO_EXECUTION_REQUEST_NOT_A_PASS_OR_AN_UNKNOWN_OUTCOME",
        early_stopping="UNUSED_BUDGET_RETAINED_NO_DUMMY_CALLS",utility="NOT_ESTABLISHED",no_regression_guaranteed=False)
    value["parity_sha256"]=digest(value)
    return value
