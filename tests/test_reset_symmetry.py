"""Reproducible first-party counterexamples for per-entry reset accounting."""
from copy import deepcopy

import pytest

from tomolab.discovery.call_meter import HardCallMeter, ResetNotVerified, MeterReentryError
from tomolab.discovery.call_meter import parity_receipt
from tomolab.structural_probe import _measure_pair

CONTRACT = dict(kind="sequence_int", low=-4, high=4, min_size=0, max_size=4)


def test_shared_reset_false_pass_is_refuted_and_replayed_with_symmetric_resets():
    state = {"value": 0}
    def reset():
        state["value"] = 0
        return True
    def target(point):
        state["value"] += 1
        return state["value"]
    def oracle(point):
        return state["value"]
    strict = HardCallMeter(3, arm_id="per-entry", reset_per_entry=True)
    rows = [strict.evaluate(target, oracle, [1], CONTRACT, reset=reset) for _ in range(3)]
    assert [row["feedback"]["status"] for row in rows] == ["FAILURE"] * 3
    assert len({row["semantic_digest"] for row in rows}) == 1
    snap = strict.snapshot()
    assert (snap["target_calls_used"], snap["oracle_calls_used"], snap["reset_calls_used"], snap["fresh_reset_count"]) == (3, 3, 6, 6)


def test_oracle_reset_failure_retains_partial_cost_and_releases_active_guard():
    actual = dict(target=0, oracle=0, reset=0)
    def target(point):
        actual["target"] += 1
        return sum(point)
    def oracle(point):
        actual["oracle"] += 1
        return sum(point)
    def reset():
        actual["reset"] += 1
        return actual["reset"] != 2
    meter = HardCallMeter(2, arm_id="partial", reset_per_entry=True)
    with pytest.raises(ResetNotVerified):
        meter.evaluate(target, oracle, [1], CONTRACT, reset=reset)
    assert actual == dict(target=1, oracle=0, reset=2)
    snap = meter.snapshot()
    assert (snap["target_calls_used"], snap["oracle_calls_used"], snap["fresh_reset_count"], snap["reset_failures"]) == (1, 0, 1, 1)
    assert snap["events"][-1]["unknown"] is True
    assert meter.evaluate(target, oracle, [2], CONTRACT, reset=reset)["feedback"]["status"] == "PASS"


@pytest.mark.parametrize("which", ["target", "oracle"])
def test_swallowed_reentry_during_either_reset_never_creates_a_pass(which):
    state = {"reset": 0, "target": 0, "oracle": 0}
    meter = HardCallMeter(1, arm_id="reentry", reset_per_entry=True)
    def target(point):
        state["target"] += 1
        return sum(point)
    def oracle(point):
        state["oracle"] += 1
        return sum(point)
    def reset():
        state["reset"] += 1
        if state["reset"] == (1 if which == "target" else 2):
            with pytest.raises(MeterReentryError):
                meter.evaluate(target, oracle, [1], CONTRACT, reset=reset)
        return True
    with pytest.raises(ResetNotVerified):
        meter.evaluate(target, oracle, [1], CONTRACT, reset=reset)
    assert state["oracle"] == 0 and state["target"] == int(which == "oracle")
    assert meter.snapshot()["reentry_rejections"] == 1


def test_per_entry_reset_is_required_and_invalid_input_does_not_spend():
    meter = HardCallMeter(1, arm_id="required", reset_per_entry=True)
    with pytest.raises(ValueError, match="explicit reviewed"):
        meter.evaluate(sum, sum, [1], CONTRACT)
    row = meter.evaluate(sum, sum, [True], CONTRACT, reset=lambda: True)
    assert row["feedback"]["status"] == "INVALID_INPUT"
    assert meter.snapshot()["reset_calls_used"] == 0


def test_pair_refuses_a_legacy_reset_policy_before_any_entry():
    meter = HardCallMeter(6, arm_id="legacy")
    with pytest.raises(ValueError, match="per-entry"):
        _measure_pair(sum, sum, [1], [2], reset=lambda: True, structure={}, contract=CONTRACT, call_meter=meter)
    assert meter.snapshot()["target_calls_used"] == meter.snapshot()["reset_calls_used"] == 0


def test_meter_events_reconcile_actual_resets_for_success_and_failure():
    meter = HardCallMeter(2, arm_id="events", reset_per_entry=True)
    meter.evaluate(sum, sum, [1], CONTRACT, reset=lambda: True)
    with pytest.raises(ResetNotVerified):
        meter.evaluate(sum, sum, [2], CONTRACT, reset=lambda: False)
    snap = meter.snapshot()
    assert sum(row["reset_calls"] for row in snap["events"]) == snap["reset_calls_used"] == 3
    assert sum(row.get("fresh_reset_count", 0) for row in snap["events"]) == snap["fresh_reset_count"] == 2


def test_comparison_cannot_mix_legacy_and_per_entry_reset_contracts():
    meters={"old":HardCallMeter(1,arm_id="old"),"new":HardCallMeter(1,arm_id="new",reset_per_entry=True)}
    with pytest.raises(ValueError,match="identical reset"):
        parity_receipt(meters,preparation_cost_ledger={"scope":"AUTHORED_CONTROL"})
