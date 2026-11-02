"""Authored scheduler controls use real Target/Oracle/reset entries, not fake costs.

The explicit CFault/DFault mappings below identify only the reviewed synthetic
fixture mechanisms. Different failing inputs are never treated as different
defects, and this file provides no external/OOS utility evidence.
"""

from copy import deepcopy
import math
from threading import Event, Thread, current_thread

import pytest

from tomolab.discovery.call_meter import HardCallMeter, HardBudgetExhausted, ResetNotVerified
from tomolab.discovery.online_engine import OnlinePolicy, run_online
from tomolab.discovery.online_learning import learn_mold
from tomolab.discovery.recursive_policy import MixedPolicyScheduler, public_failure_phenotype


CONTRACT = dict(kind="int", low=0, high=10000)


class CFault(Exception):
    """One reviewed authored defect, regardless of its triggering input."""


class DFault(Exception):
    """A second reviewed authored defect that only D receives in the control."""


class AuthoredExecution:
    def __init__(self, mode="pass"):
        self.mode = mode
        self.actual = dict(target=0, oracle=0, reset=0)
        self.points = []
        self.point_entries = {}
        self.fail_next_oracle_reset = False

    def target(self, point):
        self.actual["target"] += 1
        self.points.append(point)
        if self.mode == "negative" and point % 2:
            raise CFault()
        if self.mode == "shared":
            raise CFault()
        if self.mode == "positive":
            if point % 2:
                raise CFault()
            raise DFault()
        if self.mode == "unknown" and not point % 2:
            return object()
        return 0

    def oracle(self, point):
        self.actual["oracle"] += 1
        return 0

    def reset(self):
        self.actual["reset"] += 1
        if self.fail_next_oracle_reset and self.actual["target"] > self.actual["oracle"]:
            self.fail_next_oracle_reset = False
            return False
        return True


def _evaluate(meter, fixture, point, policy):
    return meter.evaluate(
        fixture.target, fixture.oracle, point, CONTRACT,
        reset=fixture.reset, tracing=False, phase="authored_mixed_probe", policy_id=policy,
    )


def _assert_actual_meter_costs(meter, fixture):
    snap = meter.snapshot()
    assert snap["target_calls_used"] == fixture.actual["target"]
    assert snap["oracle_calls_used"] == fixture.actual["oracle"]
    assert snap["reset_calls_used"] == fixture.actual["reset"]
    for policy in ("C", "D"):
        rows = [row for row in snap["events"] if row.get("policy_id") == policy]
        for field, event_field in (
            ("actual_target_calls", "target_calls"), ("actual_oracle_calls", "oracle_calls"),
            ("actual_reset_calls", "reset_calls"),
        ):
            assert snap["policy_accounting"][policy][field] == sum(row[event_field] for row in rows)
    return snap


@pytest.mark.parametrize("budget", [5, 11, 12])
def test_actual_d_calls_cannot_consume_the_static_half_reservation(budget):
    fixture = AuthoredExecution()
    meter = HardCallMeter(budget, arm_id="mixed-floor", reset_per_entry=True)
    meter.configure_policy_reservation(budget=budget, epsilon_static_floor=0.5)
    c_floor, d_cap = math.ceil(budget / 2), budget // 2
    for index in range(d_cap):
        _evaluate(meter, fixture, 2 * index, "D")
    before = deepcopy(fixture.actual)
    with pytest.raises(HardBudgetExhausted):
        _evaluate(meter, fixture, 100, "D")
    assert fixture.actual == before  # quota rejection does not enter reset or either callable
    for index in range(c_floor):
        _evaluate(meter, fixture, 2 * index + 1, "C")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert fixture.actual == dict(target=budget, oracle=budget, reset=2 * budget)
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == c_floor
    assert snap["policy_accounting"]["C"]["actual_oracle_calls"] == c_floor
    assert snap["policy_accounting"]["D"]["actual_target_calls"] == d_cap


def test_manual_breaker_meter_contract_reclaims_every_remaining_d_slot_for_c():
    fixture = AuthoredExecution()
    meter = HardCallMeter(12, arm_id="mixed-reclaim", reset_per_entry=True)
    meter.configure_policy_reservation(budget=12, epsilon_static_floor=0.5)
    for policy in ("C", "D"):
        for index in range(2):
            _evaluate(meter, fixture, index, policy)
    meter.trigger_policy_circuit_breaker(reason="AUTHORED_METER_ADMISSION_CONTROL")
    before = deepcopy(fixture.actual)
    with pytest.raises(HardBudgetExhausted):
        _evaluate(meter, fixture, 100, "D")
    assert fixture.actual == before
    for index in range(8):
        _evaluate(meter, fixture, 200 + index, "C")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == 10
    assert snap["policy_accounting"]["D"]["actual_target_calls"] == 2
    assert fixture.actual == dict(target=12, oracle=12, reset=24)


@pytest.mark.parametrize("policy", [None, "UNATTRIBUTED", "OTHER"])
def test_mixed_meter_rejects_missing_or_invalid_attribution_before_any_entry(policy):
    fixture = AuthoredExecution()
    meter = HardCallMeter(8, arm_id="mixed-attribution", reset_per_entry=True)
    meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    with pytest.raises(ValueError):
        _evaluate(meter, fixture, 2, policy)
    assert fixture.actual == dict(target=0, oracle=0, reset=0)


def test_partial_oracle_reset_failure_is_charged_to_its_actual_policy():
    fixture = AuthoredExecution()
    fixture.fail_next_oracle_reset = True
    meter = HardCallMeter(8, arm_id="mixed-partial", reset_per_entry=True)
    meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    with pytest.raises(ResetNotVerified):
        _evaluate(meter, fixture, 2, "D")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert fixture.actual == dict(target=1, oracle=0, reset=2)
    assert snap["policy_accounting"]["D"]["actual_target_calls"] == 1
    assert snap["policy_accounting"]["D"]["actual_oracle_calls"] == 0
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == 0
    for index in range(4):
        _evaluate(meter, fixture, 2 * index + 1, "C")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == 4
    assert snap["policy_accounting"]["C"]["actual_oracle_calls"] == 4
    assert snap["unresolved_measurement_events"] or snap["unknown_observations"]


def test_reservation_cannot_promote_unequal_remaining_caps_to_equal_budget():
    fixture = AuthoredExecution()
    meter = HardCallMeter(8, 7, arm_id="mixed-unequal", reset_per_entry=True)
    with pytest.raises((HardBudgetExhausted, ValueError)):
        meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    assert fixture.actual == dict(target=0, oracle=0, reset=0)


@pytest.mark.parametrize("epsilon", [0.0, 0.25, 0.5, 1.0])
def test_configured_epsilon_uses_the_full_odd_total_budget(epsilon):
    fixture = AuthoredExecution()
    budget = 11
    meter = HardCallMeter(budget, arm_id="mixed-epsilon", reset_per_entry=True)
    receipt = meter.configure_policy_reservation(budget=budget, epsilon_static_floor=epsilon)
    reserved = math.ceil(epsilon * budget)
    assert receipt["reserved_static_calls"] == reserved
    assert receipt["initial_learned_cap"] == budget - reserved
    for point in range(budget - reserved):
        _evaluate(meter, fixture, point, "D")
    for point in range(reserved):
        _evaluate(meter, fixture, point, "C")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == reserved
    assert snap["policy_accounting"]["D"]["actual_target_calls"] == budget - reserved


def test_releasing_a_completed_mixed_reservation_preserves_cost_and_allows_plain_c():
    fixture = AuthoredExecution()
    meter = HardCallMeter(16, arm_id="mixed-then-c", reset_per_entry=True)
    meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    for policy in ("C", "D"):
        for point in range(4):
            _evaluate(meter, fixture, point, policy)
    before = meter.snapshot()
    closed = meter.release_policy_reservation()
    assert closed["active"] is False
    assert meter.snapshot()["target_calls_used"] == before["target_calls_used"] == 8
    assert meter.snapshot()["policy_reservation"] is None
    for point in range(8):
        _evaluate(meter, fixture, 100 + point, "C")
    snap = _assert_actual_meter_costs(meter, fixture)
    assert snap["target_calls_used"] == snap["oracle_calls_used"] == 16
    assert snap["policy_accounting"]["C"]["actual_target_calls"] == 12
    assert snap["policy_accounting"]["D"]["actual_target_calls"] == 4


def test_reconfigure_cannot_reset_an_open_d_quota_but_release_allows_a_new_run():
    fixture = AuthoredExecution()
    meter = HardCallMeter(16, arm_id="mixed-no-quota-reset", reset_per_entry=True)
    meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    for point in range(2):
        _evaluate(meter, fixture, point, "D")
    before = meter.snapshot()
    with pytest.raises(ValueError):
        meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    after = meter.snapshot()
    assert after["events"] == before["events"]
    assert after["policy_reservation"] == before["policy_reservation"]
    for point in range(2):
        _evaluate(meter, fixture, 100 + point, "D")
    with pytest.raises(HardBudgetExhausted):
        _evaluate(meter, fixture, 200, "D")
    for point in range(4):
        _evaluate(meter, fixture, 300 + point, "C")
    meter.release_policy_reservation()
    meter.configure_policy_reservation(budget=8, epsilon_static_floor=0.5)
    for policy in ("C", "D"):
        for point in range(4):
            _evaluate(meter, fixture, 400 + point, policy)
    snap = _assert_actual_meter_costs(meter, fixture)
    assert fixture.actual == dict(target=16, oracle=16, reset=32)
    assert snap["policy_reservation"]["actual_policy_calls"]["D"]["actual_target_calls"] == 4


SEQUENCE_CONTRACT = dict(kind="sequence_int", low=1, high=1000, min_size=1, max_size=2)


class AuthoredSequenceExecution(AuthoredExecution):
    def target(self, point):
        self.actual["target"] += 1
        self.points.append(deepcopy(point))
        key = tuple(point)
        self.point_entries[key] = self.point_entries.get(key, 0) + 1
        if len(point) == 1:
            if self.mode == "return_negative":
                return 1
            if self.mode == "unknown_c" and point[0] != 1:
                return object()
            raise CFault()
        if len(point) == 2 and point[0] == point[1]:
            if self.mode == "positive":
                raise DFault()
            if self.mode == "shared":
                raise CFault()
            if self.mode == "unknown":
                return object()
            if self.mode == "mismatch":
                return 1
            if self.mode == "flaky" and self.point_entries[key] == 1:
                raise DFault()
        return 0


def _frozen_authored_mold():
    """Learn one real constantize edit from separate, metered synthetic source calls."""
    source = AuthoredSequenceExecution("positive")
    preparation = HardCallMeter(2, arm_id="authored-source", scope="PREPARATION", reset_per_entry=True)
    rows = []
    for point in ([1, 2], [1, 1]):
        observation = preparation.evaluate(
            source.target, source.oracle, point, SEQUENCE_CONTRACT,
            reset=source.reset, tracing=False, phase="source_preparation",
        )
        rows.append(dict(input=point, status=observation["feedback"]["status"],
                         contract=SEQUENCE_CONTRACT, source_identity="authored-fixed-source"))
    return learn_mold(rows, operator_grammar=["constantize"]), preparation.snapshot()


def _exercise_real_edit_controller(monkeypatch, mode, *, budget=36, warmup=6):
    """Control only the common operator, while executing real C/D edit selection.

    This component integration isolates routing from native Hypothesis sampling:
    C really applies delete and D really selects/applies the frozen constantize
    Mold. Every observation and both confirmations enter the actual host meter.
    It is not an external target benchmark or a replacement for the RPC tests.
    """
    fixture = AuthoredSequenceExecution(mode)
    mold, preparation = _frozen_authored_mold()
    frozen = deepcopy(mold)
    policies = {
        arm: OnlinePolicy(SEQUENCE_CONTRACT, method=arm, seed=29, budget=budget,
                          mold=mold if arm == "D" else None)
        for arm in ("C", "D")
    }
    for policy in policies.values():
        monkeypatch.setattr(policy, "_local_operator", lambda: "delete")
    scheduler = MixedPolicyScheduler(budget, epsilon_static_floor=0.5, warmup_calls=warmup)
    meter = HardCallMeter(budget, arm_id="authored-mixed-controller", reset_per_entry=True)
    meter.configure_policy_reservation(budget=budget, epsilon_static_floor=0.5)
    selections, breaker_event = [], None

    def execute(point, arm):
        observation = meter.evaluate(
            fixture.target, fixture.oracle, point, SEQUENCE_CONTRACT,
            reset=fixture.reset, tracing=False, phase="authored_actual_edit", policy_id=arm,
        )
        scheduler.record_execution(arm, target_calls=observation["target_calls"],
                                   oracle_calls=observation["oracle_calls"],
                                   feedback=observation["feedback"])
        return observation

    while scheduler.can_allocate("C", 1):
        remaining = budget - max(
            sum(row[key] for row in scheduler.actual.values())
            for key in ("target_calls", "oracle_calls")
        )
        arm = scheduler.choose_policy(confirmation_credit=3 if remaining >= 3 else 1)
        policy = policies[arm]
        anchor = [2 * len(selections) + 1, 2 * len(selections) + 2]
        common = policy._common_structure_choice(anchor, anchor)
        proposal = policy._guided_structure_choice(anchor, common) if arm == "D" else common
        point, _, operator, rule, _ = proposal
        selections.append(dict(policy=arm, input=deepcopy(point), operator=operator, rule_id=rule))
        first = execute(point, arm)
        policy.seen.add(first["feedback"]["input_digest"])
        policy.receive(point, first["feedback"], operator=operator)
        if first["feedback"]["status"] == "FAILURE":
            if scheduler.can_allocate(arm, 2):
                repeats = [execute(point, arm) for _ in range(2)]
                stable = all(row["feedback"]["status"] == "FAILURE"
                             and row["semantic_digest"] == first["semantic_digest"] for row in repeats)
                if stable:
                    scheduler.confirm_failure(arm, first["feedback"])
                else:
                    scheduler.mark_unconfirmed_failure(arm)
            else:
                scheduler.mark_unconfirmed_failure(arm)
        if scheduler.checkpoint() and breaker_event is None:
            meter.trigger_policy_circuit_breaker(reason=scheduler.snapshot()["circuit_breaker"]["reason"])
            breaker_event = len(meter.snapshot()["events"])
    assert mold == frozen
    snap = _assert_actual_meter_costs(meter, fixture)
    receipt = scheduler.snapshot()
    for arm in ("C", "D"):
        assert receipt["actual"][arm]["target_calls"] == snap["policy_accounting"][arm]["actual_target_calls"]
        assert receipt["actual"][arm]["oracle_calls"] == snap["policy_accounting"][arm]["actual_oracle_calls"]
    assert fixture.actual == dict(target=budget, oracle=budget, reset=2 * budget)
    assert all(row["operator"] == "delete" and row["rule_id"] is None
               for row in selections if row["policy"] == "C")
    assert all(row["operator"] == "constantize" and row["rule_id"] is not None
               for row in selections if row["policy"] == "D")
    return receipt, snap, selections, breaker_event, preparation


def test_negative_transfer_triggers_after_actual_warmup_and_all_remaining_calls_go_to_c(monkeypatch):
    receipt, meter, selections, breaker_event, preparation = _exercise_real_edit_controller(monkeypatch, "negative")
    assert preparation["target_calls_used"] == preparation["oracle_calls_used"] == 2
    assert receipt["circuit_breaker_triggered"] is True
    assert receipt["observed_d_marginal_phenotypes"] == 0
    assert receipt["confirmed_unique_phenotypes"] == dict(C=1, D=0)
    assert receipt["circuit_breaker"]["actual"]["C"]["target_calls"] >= 6
    assert receipt["circuit_breaker"]["actual"]["D"]["target_calls"] >= 6
    assert receipt["reclaimed_d_budget"] > 0
    assert receipt["actual"]["C"]["target_calls"] >= 18
    assert breaker_event is not None
    assert all(row.get("policy_id") == "C" for row in meter["events"][breaker_event:])
    assert meter["policy_accounting"]["C"]["observed_unique_failure_inputs"] > 1
    assert receipt["input_or_output_digest_used_as_defect_identity"] is False


def test_real_d_constantize_finds_an_additional_confirmed_phenotype_without_breaker(monkeypatch):
    receipt, meter, selections, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, "positive")
    assert receipt["circuit_breaker_triggered"] is False and breaker_event is None
    assert receipt["observed_d_marginal_phenotypes"] == 1
    assert receipt["confirmed_unique_phenotypes"] == dict(C=1, D=1)
    assert receipt["actual"]["C"]["target_calls"] >= receipt["static_c_budget_reserved"] == 18
    assert meter["policy_accounting"]["D"]["observed_unique_failure_inputs"] > 1
    assert receipt["failure_signature_scope"].endswith("NOT_UNIQUE_DEFECT_PROOF")


def test_confirmed_c_return_mismatch_and_pass_only_d_use_a_failure_lower_bound(monkeypatch):
    receipt, meter, _, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, "return_negative")
    assert receipt["circuit_breaker_triggered"] and breaker_event is not None
    assert receipt["confirmed_unique_phenotypes"] == dict(C=0, D=0)
    assert receipt["unclassified_confirmed_failures"]["C"] > 0
    assert receipt["observation_statuses"]["D"] == ["PASS"]
    trigger = receipt["circuit_breaker"]
    assert trigger["confirmed_c_failure_lower_bound"] == 1
    assert trigger["observed_d_failures"] == 0
    assert "NOT_UNIQUE_DEFECT_COUNT" in trigger["metric"]
    assert all(row.get("policy_id") == "C" for row in meter["events"][breaker_event:])


@pytest.mark.parametrize("mode", ["unknown", "mismatch"])
def test_unknown_or_unclassified_d_evidence_abstains_instead_of_imputing_zero_gain(monkeypatch, mode):
    receipt, _, _, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, mode)
    assert receipt["marginal_gain_status"] == "UNKNOWN"
    assert receipt["uncertainty"]["D"]
    assert receipt["circuit_breaker_triggered"] is False and breaker_event is None


def test_partial_c_knowledge_cannot_use_the_pass_only_d_shortcut(monkeypatch):
    receipt, _, _, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, "unknown_c")
    assert receipt["confirmed_unique_phenotypes"]["C"] == 1
    assert receipt["observation_statuses"]["D"] == ["PASS"]
    assert receipt["uncertainty"]["C"] == ["UNKNOWN_OR_PARTIAL_MEASUREMENT"]
    assert not receipt["circuit_breaker_triggered"] and breaker_event is None


def test_nonreproducing_d_failure_is_unknown_and_never_becomes_zero_gain(monkeypatch):
    receipt, _, _, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, "flaky")
    assert receipt["confirmed_unique_phenotypes"]["D"] == 0
    assert "FAILURE_NOT_CONFIRMED" in receipt["uncertainty"]["D"]
    assert "FAILURE" in receipt["observation_statuses"]["D"]
    assert not receipt["circuit_breaker_triggered"] and breaker_event is None


def test_insufficient_actual_warmup_cannot_trigger_the_breaker(monkeypatch):
    receipt, _, _, breaker_event, _ = _exercise_real_edit_controller(monkeypatch, "negative", warmup=100)
    assert min(receipt["actual"][arm]["target_calls"] for arm in ("C", "D")) < 100
    assert not receipt["circuit_breaker_triggered"] and breaker_event is None


def test_repeated_failing_inputs_do_not_create_extra_phenotypes_or_marginal_gain(monkeypatch):
    receipt, meter, _, _, _ = _exercise_real_edit_controller(monkeypatch, "shared")
    assert receipt["confirmed_unique_phenotypes"] == dict(C=1, D=1)
    assert receipt["observed_d_marginal_phenotypes"] == 0
    assert meter["policy_accounting"]["D"]["observed_unique_failure_inputs"] > 1
    assert not receipt["circuit_breaker_triggered"]  # equal actual-call yield is not inferior


def test_phenotype_identity_uses_neither_input_digest_nor_private_output_digest():
    fixture = AuthoredSequenceExecution("negative")
    meter = HardCallMeter(2, arm_id="authored-phenotype", reset_per_entry=True)

    def varying_oracle(point):
        fixture.actual["oracle"] += 1
        return point[0]

    rows = [meter.evaluate(
        fixture.target, varying_oracle, point, SEQUENCE_CONTRACT,
        reset=fixture.reset, tracing=False, phase="authored_phenotype", policy_id="C",
    ) for point in ([1], [2])]
    assert all(row["feedback"]["status"] == "FAILURE" for row in rows)
    assert rows[0]["feedback"]["input_digest"] != rows[1]["feedback"]["input_digest"]
    assert rows[0]["semantic_digest"] != rows[1]["semantic_digest"]
    assert public_failure_phenotype(rows[0]["feedback"]) == public_failure_phenotype(rows[1]["feedback"])
    _assert_actual_meter_costs(meter, fixture)


@pytest.mark.parametrize("epsilon", [0.0, 0.25, 0.5, 1.0])
def test_scheduler_reservation_matches_the_configured_full_budget_fraction(epsilon):
    scheduler = MixedPolicyScheduler(11, epsilon_static_floor=epsilon)
    receipt = scheduler.snapshot()
    assert receipt["static_c_budget_reserved"] == math.ceil(epsilon * 11)
    assert receipt["initial_d_budget_cap"] == 11 - math.ceil(epsilon * 11)


def test_real_rpc_mixed_run_has_host_authoritative_costs_and_releases_shared_meter():
    """No policy monkeypatch: exercise native Hypothesis, actual worker RPC and host."""
    fixture = AuthoredExecution()
    meter = HardCallMeter(48, arm_id="rpc-mixed-then-c", reset_per_entry=True)
    mixed = run_online(
        fixture.target, fixture.oracle, CONTRACT, method="D", seed=29,
        budget=24, shrink_budget=0, max_seconds=20, mode="black_box",
        call_meter=meter, fresh_reset=fixture.reset, hard_budget=True,
        epsilon_static_floor=0.5, circuit_breaker_warmup=6,
    )
    assert mixed["status"] == "COMPLETE", mixed.get("error_type")
    assert mixed["target_calls"] == mixed["oracle_calls"] == 24
    assert mixed["reset_calls"] == mixed["fresh_reset_count"] == 48
    receipt = mixed["scheduler"]["mixed_policy"]
    assert mixed["scheduler"]["host_accounting_authoritative"] is True
    assert receipt["total_budget"] == 24 and receipt["static_c_budget_reserved"] == 12
    assert receipt["actual"]["C"]["target_calls"] >= 12
    assert receipt["actual"]["D"]["target_calls"] <= 12
    assert all(event["policy_id"] in ("C", "D") for event in mixed["events"])
    assert sum(row["target_calls"] for row in receipt["actual"].values()) == 24
    assert mixed["boundary"]["target_code_transferred"] is False
    assert mixed["boundary"]["oracle_code_transferred"] is False
    assert mixed["boundary"]["oracle_hashes_transferred"] is False
    assert meter.snapshot()["policy_reservation"] is None
    static = run_online(
        fixture.target, fixture.oracle, CONTRACT, method="C", seed=29,
        budget=24, shrink_budget=0, max_seconds=20, mode="black_box",
        call_meter=meter, fresh_reset=fixture.reset, hard_budget=True,
    )
    assert static["status"] == "COMPLETE"
    assert static["target_calls"] == static["oracle_calls"] == 24
    assert static["metered_run_actual"]["target_calls_used"] == 24
    assert fixture.actual == dict(target=48, oracle=48, reset=96)
    assert meter.snapshot()["target_calls_used"] == meter.snapshot()["oracle_calls_used"] == 48


def test_real_rpc_floor_denominator_includes_confirmation_and_shrink_calls():
    fixture = AuthoredExecution("shared")
    meter = HardCallMeter(30, arm_id="rpc-all-phases", reset_per_entry=True)
    result = run_online(
        fixture.target, fixture.oracle, CONTRACT, method="D", seed=31,
        budget=30, shrink_budget=6, max_seconds=20, mode="black_box",
        call_meter=meter, fresh_reset=fixture.reset, hard_budget=True,
        epsilon_static_floor=0.5, circuit_breaker_warmup=6,
    )
    assert result["status"] == "COMPLETE", result.get("error_type")
    receipt = result["scheduler"]["mixed_policy"]
    assert receipt["static_c_budget_reserved"] == 15  # full 30, not discovery 24
    assert receipt["initial_d_budget_cap"] == 15
    assert receipt["actual"]["D"]["target_calls"] <= 15
    assert result["target_calls"] == result["oracle_calls"] == fixture.actual["target"] <= 30
    assert fixture.actual["reset"] == 2 * result["target_calls"]
    assert any(event["phase"] == "confirmation" for event in result["events"])
    assert any("shrink" in event["phase"] for event in result["events"])
    assert sum(row["target_calls"] for row in receipt["actual"].values()) == result["target_calls"]
    _assert_actual_meter_costs(meter, fixture)


@pytest.mark.parametrize("mode,expected_calls", [
    ("confirmation_mismatch", 7), ("unconfirmed_abort", 1),
])
def test_host_confirmation_uncertainty_survives_abort_without_false_reallocation(monkeypatch, mode, expected_calls):
    """Host-control fault injection; actual callables/meter, no worker RPC claim."""
    import tomolab.discovery.online_boundary as boundary_module

    actual = dict(target=0, oracle=0, reset=0)
    d_entries = 0
    meter = HardCallMeter(18, arm_id="host-uncertainty-" + mode, reset_per_entry=True)

    def target(point):
        nonlocal d_entries
        actual["target"] += 1
        if point == 1:
            raise CFault()
        if point == 2:
            d_entries += 1
            if d_entries == 1:
                raise DFault()
        return 0

    def oracle(point):
        actual["oracle"] += 1
        return 0

    def reset():
        actual["reset"] += 1
        return True

    class AuthoredBoundary:
        receipt = dict(scope="AUTHORED_HOST_CONTROL_NOT_RPC_OR_OOS")
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def run(self, config, execute):
            if mode == "unconfirmed_abort":
                execute(2, phase="base", reference=None, policy_id="D")
                raise RuntimeError("AUTHORED_ABORT_AFTER_UNCONFIRMED_FAILURE")
            first = execute(1, phase="base", reference=None, policy_id="C")
            for _ in range(2):
                execute(1, phase="confirmation", reference=first["observation_id"], policy_id="C")
            first = execute(2, phase="base", reference=None, policy_id="D")
            for _ in range(2):
                execute(2, phase="confirmation", reference=first["observation_id"], policy_id="D")
            execute(4, phase="base", reference=None, policy_id="C")
            assert meter.snapshot()["policy_reservation"]["circuit_breaker_triggered"] is False
            raise RuntimeError("AUTHORED_STOP_AFTER_COMPLETED_TRANSACTIONS")

    monkeypatch.setattr(boundary_module, "OnlineBoundary", AuthoredBoundary)
    result = run_online(
        target, oracle, dict(kind="int", low=0, high=10), method="D",
        budget=18, shrink_budget=0, max_seconds=10, mode="black_box",
        call_meter=meter, fresh_reset=reset, circuit_breaker_warmup=3,
    )
    receipt = result["scheduler"]["mixed_policy"]
    assert result["status"] == "INCONCLUSIVE_BOUNDARY_ERROR"
    assert receipt["circuit_breaker_triggered"] is False
    assert receipt["marginal_gain_status"] == "UNKNOWN"
    assert receipt["observed_d_marginal_phenotypes"] is None
    assert "FAILURE_NOT_CONFIRMED" in receipt["uncertainty"]["D"]
    assert actual == dict(target=expected_calls, oracle=expected_calls, reset=2 * expected_calls)
    assert result["target_calls"] == result["oracle_calls"] == expected_calls
    assert result["reset_calls"] == 2 * expected_calls
    assert meter.snapshot()["policy_reservation_active"] is False
    assert sum(row["actual_target_calls"] for row in meter.snapshot()["policy_accounting"].values()) == expected_calls


def test_postprocessing_failure_releases_reservation_and_preserves_actual_entries(monkeypatch):
    """Fault the host snapshot after one real pair; cleanup must run in finally."""
    import tomolab.discovery.online_boundary as boundary_module

    actual = dict(target=0, oracle=0, reset=0)
    meter = HardCallMeter(24, arm_id="host-postprocess-cleanup", reset_per_entry=True)
    original_snapshot = meter.snapshot
    fault = False

    def target(point):
        actual["target"] += 1
        return point

    def oracle(point):
        actual["oracle"] += 1
        return point

    def reset():
        actual["reset"] += 1
        return True

    def faulted_snapshot():
        if fault:
            raise RuntimeError("AUTHORED_POSTPROCESS_SNAPSHOT_ERROR")
        return original_snapshot()

    class AuthoredBoundary:
        receipt = dict(scope="AUTHORED_HOST_CONTROL_NOT_RPC_OR_OOS")
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def run(self, config, execute):
            nonlocal fault
            execute(1, phase="base", reference=None, policy_id="C")
            fault = True
            raise ValueError("AUTHORED_BOUNDARY_STOP")

    monkeypatch.setattr(meter, "snapshot", faulted_snapshot)
    monkeypatch.setattr(boundary_module, "OnlineBoundary", AuthoredBoundary)
    with pytest.raises(RuntimeError, match="AUTHORED_POSTPROCESS_SNAPSHOT_ERROR"):
        run_online(
            target, oracle, dict(kind="int", low=0, high=10), method="D",
            budget=12, shrink_budget=0, max_seconds=10, mode="black_box",
            call_meter=meter, fresh_reset=reset,
        )
    snapshot = original_snapshot()
    assert snapshot["policy_reservation_active"] is False
    assert actual == dict(target=1, oracle=1, reset=2)
    assert snapshot["target_calls_used"] == snapshot["oracle_calls_used"] == 1
    assert snapshot["reset_calls_used"] == 2


def test_failed_concurrent_admission_cannot_release_the_other_runs_reservation(monkeypatch):
    """Coordinate two real host admissions; boundary is a labelled test control."""
    import tomolab.discovery.online_boundary as boundary_module
    import tomolab.discovery.online_engine as engine

    actual = dict(target=0, oracle=0, reset=0)
    meter = HardCallMeter(24, arm_id="host-concurrent-owner", reset_per_entry=True)
    b_started, a_configured, b_finished = Event(), Event(), Event()
    errors, returned = {}, {}
    original_host = engine._run_online_host

    def target(point):
        actual["target"] += 1
        return point

    def oracle(point):
        actual["oracle"] += 1
        return point

    def reset():
        actual["reset"] += 1
        return True

    def gated_host(*args, **kwargs):
        if current_thread().name == "authored-B":
            b_started.set()
            assert a_configured.wait(5)
        return original_host(*args, **kwargs)

    class AuthoredBoundary:
        receipt = dict(scope="AUTHORED_HOST_CONTROL_NOT_RPC_OR_OOS")
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            a_configured.set()
            return self
        def __exit__(self, *args):
            return False
        def run(self, config, execute):
            assert b_finished.wait(5)
            assert meter.snapshot()["policy_reservation_active"] is True
            execute(1, phase="base", reference=None, policy_id="C")
            raise ValueError("AUTHORED_OWNER_A_STOP")

    monkeypatch.setattr(engine, "_run_online_host", gated_host)
    monkeypatch.setattr(boundary_module, "OnlineBoundary", AuthoredBoundary)

    def invoke(label):
        try:
            returned[label] = engine.run_online(
                target, oracle, dict(kind="int", low=0, high=10), method="D",
                budget=12, shrink_budget=0, max_seconds=10, mode="black_box",
                call_meter=meter, fresh_reset=reset,
            )
        except Exception as error:
            errors[label] = type(error).__name__
        finally:
            if label == "B":
                b_finished.set()

    b = Thread(target=invoke, args=("B",), name="authored-B")
    a = Thread(target=invoke, args=("A",), name="authored-A")
    b.start()
    try:
        assert b_started.wait(5)
        a.start()
        a.join(8)
        b.join(8)
        assert not a.is_alive() and not b.is_alive()
    finally:
        # Release a blocked test thread before the fixture restores monkeypatches.
        a_configured.set()
        b_finished.set()
        if a.ident is not None:
            a.join(6)
        b.join(6)
    assert errors == {"B": "ValueError"}
    assert returned["A"]["target_calls"] == returned["A"]["oracle_calls"] == 1
    assert meter.snapshot()["policy_reservation_active"] is False
    assert actual == dict(target=1, oracle=1, reset=2)
