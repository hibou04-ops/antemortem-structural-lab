"""Recorded Source deltas, empirical limits, and compact execution integrity."""
from copy import deepcopy
import json
import random

import pytest

from tomolab.discovery.claim_semantics import EMPIRICAL
from tomolab.discovery.online_learning import (applicable_rules, learn_mold,
    load_mold, save_mold, select_edit, validate_mold)
from tomolab.discovery.schema import canonical, digest


SEQUENCE = dict(kind="sequence_int", low=-10, high=10, max_size=8)
INTEGER = dict(kind="int", low=-10, high=10)


def observed(point, status, contract=SEQUENCE, source="owned-source"):
    return dict(input=point, status=status, contract=contract, source_identity=source)


def constant_source():
    return [observed([1, 2], "PASS"), observed([1, 1], "FAILURE")]


def resign(mold):
    mold["artifact_digest"] = digest({key: value for key, value in mold.items() if key != "artifact_digest"})
    return mold


def test_extracts_recorded_delta_without_inventing_operator_or_causal_law():
    audit, metrics = {}, {}
    mold = learn_mold(constant_source(), metrics=metrics, audit=audit)
    rule = next(rule for rule in mold["rules"] if rule["edit_composition"] == ["constantize"])
    assert rule["provenance"] == ["COMMON_PRIOR", "SOURCE_LEARNED_SELECTION"]
    assert rule["claim_kind"] == EMPIRICAL
    assert rule["uncertainty"] == "UNKNOWN_OUTSIDE_RECORDED_SOURCE_SUPPORT"
    assert audit["deltas"][0]["x_pass"] == [1, 2]
    assert audit["deltas"][0]["x_fail"] == [1, 1]
    assert audit["deltas"][0]["global_minimum"] is False
    assert audit["deltas"][0]["causal_uniqueness"] is False
    assert metrics["source_target_calls"] == metrics["source_oracle_calls"] == 0
    assert metrics["learning_wall_seconds"] >= 0
    assert metrics["edit_applications_considered"] > 0


def test_two_edit_composition_requires_an_irreducible_recorded_difference():
    rows = [observed([1, 2], "PASS"), observed([-1, -1], "FAILURE"),
            observed([1, 1], "PASS"), observed([-1, -2], "PASS")]
    mold = learn_mold(rows, operator_grammar=["constantize", "negate"])
    composition = [rule for rule in mold["rules"] if len(rule["edit_composition"]) == 2]
    assert composition
    assert all("SOURCE_LEARNED_COMPOSITION" in rule["provenance"] for rule in composition)
    # A single existing edit is never renamed a composed discovery.
    ordinary = learn_mold(constant_source(), operator_grammar=["constantize", "identity"])
    assert all(len(rule["edit_composition"]) == 1 for rule in ordinary["rules"])


def test_counterevidence_learns_a_structural_applicability_restriction():
    rows = [observed(1, "PASS", INTEGER), observed(-1, "FAILURE", INTEGER),
            observed(-2, "PASS", INTEGER), observed(2, "PASS", INTEGER)]
    mold = learn_mold(rows, operator_grammar=["negate"])
    rule = mold["rules"][0]
    assert rule["preconditions"] == {"has_negative": False}
    assert "SOURCE_LEARNED_APPLICABILITY" in rule["provenance"]
    assert rule["selection_statistics"]["counterevidence"] > 0
    assert rule["selection_statistics"]["applicable_counterevidence"] > 0
    assert applicable_rules(mold, 4, INTEGER)
    assert applicable_rules(mold, -4, INTEGER) == []


def test_unknown_observations_do_not_become_normal_counterevidence():
    rows = constant_source() + [observed([-1, -2], "UNKNOWN"),
                              observed([-1, -1], "EXECUTION_ERROR"),
                              observed([2, 3], "ORACLE_ERROR")]
    mold = learn_mold(rows)
    assert mold["source_summary"]["unknown_observations"] == 3
    assert all(rule["selection_statistics"]["counterevidence"] == 0 for rule in mold["rules"])


def test_conflicting_repeated_observations_are_censored():
    rows = constant_source() + [observed([1, 1], "PASS")]
    mold = learn_mold(rows)
    assert mold["rules"] == []
    assert mold["source_summary"]["unknown_observations"] == 1


def test_unpaired_failures_are_retained_and_never_relabelled_pass():
    audit = {}
    mold = learn_mold([observed([1, 1], "FAILURE")], audit=audit)
    assert mold["source_summary"]["failure_observations"] == 1
    assert mold["source_summary"]["unpaired_failures"] == 1
    assert mold["rules"] == []
    assert audit["unpaired_status"] == "UNAVAILABLE"


def test_no_cross_source_or_contract_pairing():
    rows = [observed([1, 2], "PASS", source="source-a"),
            observed([1, 1], "FAILURE", source="source-b")]
    assert learn_mold(rows)["rules"] == []
    changed = dict(SEQUENCE, max_size=9)
    assert learn_mold([observed([1, 2], "PASS"), observed([1, 1], "FAILURE", changed)])["rules"] == []


def test_source_values_names_and_target_identity_are_not_execution_conditions():
    rows = [observed([7, 9], "PASS", source="private_exact_target_name"),
            observed([7, 7], "FAILURE", source="private_exact_target_name")]
    mold = learn_mold(rows)
    serialized = canonical(mold)
    assert "private_exact_target_name" not in serialized
    assert "[7,7]" not in serialized and "[7,9]" not in serialized
    assert all(rule["typed_roles"] == [{"role": "input", "kind": "sequence_int"}] for rule in mold["rules"])
    assert applicable_rules(mold, [3, 5], SEQUENCE)
    assert all(rule["kind"] != "text" for rule in applicable_rules(mold, "ab", dict(kind="text")))


def test_learning_is_deterministic_and_does_not_mutate_source_or_mold():
    rows = constant_source()
    before = deepcopy(rows)
    mold = learn_mold(rows)
    assert rows == before
    assert learn_mold(list(reversed(rows))) == mold
    selection = select_edit(mold, [3, 4], SEQUENCE, random.Random(1))
    selection["operators"].append("identity")
    assert mold["rules"][0]["edit_composition"] == ["constantize"]
    assert select_edit(mold, [3, 4], SEQUENCE, random.Random(1))["operators"] == ["constantize"]


def test_compact_mold_size_cap_and_omission_are_explicit():
    rows = [observed([1, 2], "PASS"), observed([1, 1], "FAILURE"),
            observed([-1, -2], "FAILURE"), observed([], "FAILURE")]
    full = learn_mold(rows)
    compact = learn_mold(rows, max_bytes=800)
    assert len(canonical(compact).encode())+1 <= 800
    assert compact["rules"] == [] and compact["omitted_rules"] > 0
    assert len(canonical(full).encode())+1 <= 10240
    assert compact["source_summary"] == full["source_summary"]


def test_mold_persistence_requires_expected_digest_and_exclusive_creation(tmp_path):
    mold = learn_mold(constant_source())
    path = tmp_path/"guide.json"
    saved = save_mold(path, mold)
    assert saved["serialized_bytes"] <= 10240
    assert load_mold(path, expected_digest=mold["artifact_digest"]) == mold
    with pytest.raises(FileExistsError):
        save_mold(path, mold)
    with pytest.raises(ValueError, match="expected digest"):
        load_mold(path, expected_digest="0"*64)
    changed = json.loads(path.read_text())
    changed["rules"][0]["selection_statistics"]["support"] += 1
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        load_mold(path, expected_digest=mold["artifact_digest"])


def test_rehashing_does_not_grant_final_or_publication_authority():
    mold = learn_mold(constant_source())
    mold["final_target_authorized"] = True
    resign(mold)
    with pytest.raises(PermissionError):
        validate_mold(mold)


def test_unsupported_operator_or_hidden_execution_field_is_rejected():
    with pytest.raises(ValueError, match="COMMON_PRIOR"):
        learn_mold(constant_source(), operator_grammar=["eval_source_patch"])
    mold = learn_mold(constant_source())
    mold["oracle_answer"] = [1, 1]
    resign(mold)
    with pytest.raises(ValueError, match="fields"):
        validate_mold(mold)


def test_invalid_domain_label_and_oversized_observation_list_are_rejected():
    with pytest.raises(ValueError, match="in-domain"):
        learn_mold([observed([999], "FAILURE")])
    with pytest.raises(ValueError, match="bounded Source"):
        learn_mold(constant_source()*513)


def test_source_budget_and_no_applicable_rule_fallback():
    mold = learn_mold([], metrics={})
    assert mold["rules"] == []
    assert select_edit(mold, [1], SEQUENCE, random.Random(0)) is None
    with pytest.raises(ValueError, match="10KiB"):
        learn_mold([], max_bytes=20000)
    with pytest.raises(ValueError, match="rules"):
        learn_mold([], max_rules=0)


def test_data_only_runtime_pins_existing_semantics_and_reexports_same_functions():
    from tomolab.discovery import claim_semantics, online_learning, online_mold
    assert online_mold.EMPIRICAL == claim_semantics.EMPIRICAL
    assert online_mold.SEMANTIC_VERSION == claim_semantics.SEMANTIC_VERSION
    for name in ("validate_mold", "applicable_rules", "select_edit", "save_mold", "load_mold"):
        assert getattr(online_learning, name) is getattr(online_mold, name)
    # An unobservable feature never authorizes application or becomes evidence.
    assert online_mold._matches({}, {"all_equal": True}) is None
    assert online_mold._matches({}, {"size_class": "MANY", "all_equal": True}) is False
    assert online_mold._matches([1, 1], {"all_equal": True}) is True


@pytest.mark.parametrize("second_status", ["PASS", "FAILURE"])
def test_mapping_insertion_orders_remain_distinct_source_observations(second_status):
    contract = dict(kind="mapping", low=-10, high=10, max_size=8, alphabet="ab")
    first, second = {"a": 1, "b": 2}, {"b": 2, "a": 1}
    assert first == second and list(first) != list(second)
    rows = [observed(first, "PASS", contract), observed(second, second_status, contract)]
    mold = learn_mold(rows, operator_grammar=["identity"])
    # Distinct ordered inputs are neither conflicting duplicate labels nor
    # evidence that an identity edit explains an observed failure.
    assert mold["source_summary"]["unknown_observations"] == 0
    assert mold["source_summary"]["unpaired_failures"] == int(second_status == "FAILURE")
    assert mold["rules"] == []
    left = learn_mold([observed(first, "PASS", contract)])
    right = learn_mold([observed(second, "PASS", contract)])
    assert left["source_observation_digest"] != right["source_observation_digest"]


def test_explicit_source_input_digest_detects_order_tampering():
    from tomolab.discovery.online_schema import input_identity
    contract = dict(kind="mapping", low=-10, high=10, max_size=8, alphabet="ab")
    row = observed({"a": 1, "b": 2}, "PASS", contract)
    row["input_digest"] = input_identity(row["input"])
    learn_mold([row])
    row["input"] = {"b": 2, "a": 1}
    with pytest.raises(ValueError, match="ordered input"):
        learn_mold([row])
