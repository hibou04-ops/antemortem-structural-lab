"""Authored response/proof tests; no statistics/SciPy numeric function calls.

Real implementation integration is a separate registered CORR functional check.
These tests deliberately exercise malformed, nonfinite and misleading results
through private authored fixtures instead of consuming the research subjects.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import statistics
import sys
from types import SimpleNamespace

import pytest

from tomolab.discovery import corroboration_adapters as adapters
from tomolab.discovery import numerical_source
from tomolab.discovery.numerical_guidance import public_input_contract
from tomolab.discovery.schema import canonical

CONSTANT = {"a":[0.1, 0.1, 0.1], "b":[-1.0, 0.0, 1.0]}
NORMAL = {"a":[-1.0, 0.0, 1.0], "b":[-1.0, 0.0, 1.0]}
CONSTANT_WARNING = {"type":"scipy.stats._warnings_errors.ConstantInputWarning",
    "name":"ConstantInputWarning", "message":"authored constant warning", "source_filename":"authored.py", "source_line":1}
NEAR_WARNING = {"type":"scipy.stats._warnings_errors.NearConstantInputWarning",
    "name":"NearConstantInputWarning", "message":"authored near warning", "source_filename":"authored.py", "source_line":2}


def normalize(implementation_id, result=None, exception=None, point=CONSTANT, warning_rows=()):
    return adapters._normalise(implementation_id, result, exception, list(warning_rows), deepcopy(point))


def test_fixed_allowlist_and_identity_are_input_free(monkeypatch):
    def never(*args):
        raise AssertionError("metadata must not execute numerical inputs")
    monkeypatch.setattr(adapters, "_invoke_target", never)
    identity = adapters.implementation_identity("python-statistics-correlation")
    assert adapters.reviewed_implementation_ids() == ("python-statistics-correlation", "scipy-stats-pearsonr")
    assert identity["public_import_path"] == "statistics.correlation"
    assert all(re.fullmatch("[0-9a-f]{64}", value) for value in identity["usage_identity"].values())
    assert "Users" not in json.dumps(identity)
    assert adapters.oracle_identity()["multiple_independent_oracles"] is False
    for invalid in ("os.system", "omega_lock.pearson_result", adapters.ORACLE_ID, "scipy.stats.spearmanr"):
        with pytest.raises(ValueError, match="allowlist"):
            adapters.implementation_identity(invalid)


def test_documented_statistics_error_requires_actual_constant_input():
    for point, expected in ((CONSTANT, "UNDEFINED_AS_DOCUMENTED"), (NORMAL, "UNEXPECTED_EXCEPTION")):
        result, raw = normalize("python-statistics-correlation",
            exception=statistics.StatisticsError("authored error"), point=point)
        assert result["computability"] == expected
        assert result["numeric_value"] is None
        assert raw["exception_message"] == "authored error"


@pytest.mark.parametrize("exception", [ValueError("unrelated"), RuntimeError("unrelated"), ZeroDivisionError("unrelated")])
def test_other_exceptions_are_not_normalized_as_documented_undefined(exception):
    for implementation_id in adapters.reviewed_implementation_ids():
        result, _ = normalize(implementation_id, exception=exception)
        assert result["computability"] == "UNEXPECTED_EXCEPTION"


@pytest.mark.parametrize("value", [0.0, 1.0, 1.0000000000000002, -2.0])
def test_finite_values_for_constant_inputs_are_preserved_without_clipping(value):
    plain, raw = normalize("python-statistics-correlation", value)
    assert plain["computability"] == "DEFINED" and plain["numeric_value"] == value
    assert raw["statistic"] == {"kind":"FINITE", "value":value}
    scipy, raw = normalize("scipy-stats-pearsonr", SimpleNamespace(statistic=value,pvalue=0.5), warning_rows=[CONSTANT_WARNING])
    assert scipy["computability"] == "DEFINED" and scipy["numeric_value"] == value
    assert raw["pvalue"] == {"kind":"FINITE", "value":0.5}


def test_scipy_documented_constant_nan_needs_correct_warning_and_constant_input():
    raw = SimpleNamespace(statistic=float("nan"),pvalue=float("nan"))
    result, preserved = normalize("scipy-stats-pearsonr", raw, warning_rows=[CONSTANT_WARNING])
    assert result["computability"] == "UNDEFINED_AS_DOCUMENTED"
    assert preserved["statistic"] == preserved["pvalue"] == {"kind":"NAN"}
    canonical(result); canonical(preserved)
    for point, warnings in ((CONSTANT, []), (NORMAL,[CONSTANT_WARNING]), (CONSTANT,[NEAR_WARNING])):
        result, _ = normalize("scipy-stats-pearsonr", raw, point=point, warning_rows=warnings)
        assert result["computability"] == "UNEXPECTED_NONFINITE"
    spoof = dict(CONSTANT_WARNING, type="authored.ConstantInputWarning")
    result, _ = normalize("scipy-stats-pearsonr", raw, warning_rows=[spoof])
    assert result["computability"] == "UNEXPECTED_NONFINITE"


@pytest.mark.parametrize("value,kind", [(float("nan"),"NAN"), (float("inf"),"POSITIVE_INFINITY"), (-float("inf"),"NEGATIVE_INFINITY")])
def test_nondegenerate_nonfinite_results_never_become_normal_undefined(value, kind):
    for implementation_id, raw in (("python-statistics-correlation",value),
            ("scipy-stats-pearsonr",SimpleNamespace(statistic=value,pvalue=0.25))):
        result, record = normalize(implementation_id, raw, point=NORMAL, warning_rows=[NEAR_WARNING])
        assert result["computability"] == "UNEXPECTED_NONFINITE"
        assert record["statistic"] == {"kind":kind}
        assert result["numeric_value"] is None
        assert "NaN" not in canonical(record)


def test_unknown_return_structures_are_not_normal_negative_evidence():
    for implementation_id, raw in (("python-statistics-correlation",True),
            ("python-statistics-correlation",object()), ("scipy-stats-pearsonr",(0.5, 0.2))):
        result, record = normalize(implementation_id, raw, point=NORMAL)
        assert result["computability"] == "NOT_COMPARABLE"
        canonical(result); canonical(record)


def test_call_entry_proof_detects_a_fake_adapter_without_calling_real_target(monkeypatch):
    identity = adapters.implementation_identity("python-statistics-correlation")
    adapter = adapters.create_reviewed_adapter("python-statistics-correlation", expected_identity=identity)
    monkeypatch.setattr(adapters, "_invoke_target", lambda *args:0.0)
    with pytest.raises(PermissionError, match="adapter component changed"):
        adapter.evaluate(CONSTANT)
    assert adapter.call_counters == {"target_calls":0,"oracle_calls":0,"actual_target_function_entries":0}


def test_entry_proof_counts_authored_calls_and_restores_previous_profile(monkeypatch):
    seen = []
    def authored(a,b):
        return len(a)+len(b)
    def profile(frame,event,value):
        if event == "call" and frame.f_code is authored.__code__:
            seen.append("entered")
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        raw, error, entries = adapters._call_with_entry_proof(authored,NORMAL)
        assert raw == 6 and error is None and entries == 1
        assert sys.getprofile() is profile and seen == ["entered"]
    finally:
        sys.setprofile(previous)
    monkeypatch.setattr(adapters,"_invoke_target",lambda function,point:(function(point["a"],point["b"]),function(point["a"],point["b"]))[1])
    with pytest.raises(PermissionError,match="exactly once"):
        adapters._call_with_entry_proof(authored,NORMAL)


def test_domain_rejection_happens_before_any_target_or_oracle_call(monkeypatch):
    def denied(*args):
        raise AssertionError("out-of-domain input reached target")
    monkeypatch.setattr(adapters,"_invoke_target",denied)
    identity = adapters.implementation_identity("python-statistics-correlation")
    adapter = adapters.create_reviewed_adapter("python-statistics-correlation", expected_identity=identity)
    for point in ({"a":[0.0]*2,"b":[0.0]*2}, {"a":[2.0]*3,"b":[0.0]*3},
                  {"a":[0.0,1e-20,0.0],"b":[-1.0,0.0,1.0]}):
        with pytest.raises(ValueError,match="domain"):
            adapter.evaluate(point)
    with pytest.raises(ValueError,match="SOURCE_DOMAIN"):
        adapter.evaluate(CONSTANT,contract=public_input_contract("NEAR_CONSTANT_DIAGNOSTIC"))


def test_approved_identity_and_live_function_substitution_fail_closed(monkeypatch):
    identity = adapters.implementation_identity("python-statistics-correlation")
    altered = deepcopy(identity)
    altered["version"] = "unreviewed"
    with pytest.raises(PermissionError,match="approved identity"):
        adapters.create_reviewed_adapter("python-statistics-correlation",expected_identity=altered)
    adapter = adapters.create_reviewed_adapter("python-statistics-correlation",expected_identity=identity)
    monkeypatch.setattr(statistics,"correlation",lambda a,b:1.0)
    with pytest.raises(PermissionError,match="binding or source"):
        adapter.evaluate(CONSTANT)


def test_target_and_oracle_same_function_is_rejected_before_execution(monkeypatch):
    monkeypatch.setattr(numerical_source,"oracle_result",statistics.correlation)
    with pytest.raises(PermissionError,match="same implementation"):
        adapters.implementation_identity("python-statistics-correlation")


def test_oracle_changed_after_construction_is_rejected_before_target(monkeypatch):
    identity = adapters.implementation_identity("python-statistics-correlation")
    adapter = adapters.create_reviewed_adapter("python-statistics-correlation",expected_identity=identity)
    monkeypatch.setattr(numerical_source,"oracle_result",lambda point:{"computable":False,"value":None})
    with pytest.raises(PermissionError,match="Oracle or comparison binding"):
        adapter.evaluate(CONSTANT)


def test_public_factory_does_not_accept_arbitrary_callbacks():
    with pytest.raises(TypeError):
        adapters.create_reviewed_adapter("python-statistics-correlation",expected_identity={},target=lambda *args:0.0)


def authored_adapter(monkeypatch, value, expected, *, raises=None, warning=None, scipy=False, oracle_raises=None):
    """Only private unit seams; production factory has no callback parameter."""
    counts = {"target":0,"oracle":0}
    def target(a,b):
        counts["target"] += 1
        if warning:
            import warnings
            warnings.warn("authored warning",warning)
        if raises:
            raise raises
        return SimpleNamespace(statistic=value,pvalue=0.1) if scipy else value
    def oracle(point):
        counts["oracle"] += 1
        if oracle_raises:
            raise oracle_raises
        return deepcopy(expected)
    monkeypatch.setattr(adapters,"_resolve",lambda identifier:(SimpleNamespace(__file__=__file__),target))
    monkeypatch.setattr(adapters,"implementation_identity",lambda identifier:{"authored_identity":identifier})
    monkeypatch.setattr(numerical_source,"oracle_result",oracle)
    identifier = "scipy-stats-pearsonr" if scipy else "python-statistics-correlation"
    return adapters.create_reviewed_adapter(identifier,expected_identity={"authored_identity":identifier}),counts


def test_finite_constant_value_is_a_mismatch_after_one_real_authored_call(monkeypatch):
    adapter,counts = authored_adapter(monkeypatch,1.0000000000000002,{"computable":False,"value":None})
    result = adapter.evaluate(CONSTANT)
    assert counts == {"target":1,"oracle":1}
    assert result["actual_target_function_entries"] == 1
    assert result["comparison"]["status"] == "MISMATCH"
    assert result["comparison"]["violation_category"] == "FINITE_VALUE_FOR_EXACT_CONSTANT_INPUT"
    assert result["normalized"]["numeric_value"] == 1.0000000000000002
    assert result["comparison"]["confirmed"] is False
    assert adapter.call_counters == {"target_calls":1,"oracle_calls":1,"actual_target_function_entries":1}
    snapshot = adapter.call_counters
    snapshot["target_calls"] = 0
    assert adapter.call_counters["target_calls"] == 1


def test_normal_warning_is_not_automatically_a_defect_and_bad_nan_is_not_hidden(monkeypatch):
    warning = type("NearConstantInputWarning",(RuntimeWarning,),{"__module__":"scipy.stats._warnings_errors"})
    adapter, counts = authored_adapter(monkeypatch,1.0,{"computable":True,"value":1.0},warning=warning,scipy=True)
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "MATCH" and counts == {"target":1,"oracle":1}
    adapter, counts = authored_adapter(monkeypatch,float("nan"),{"computable":True,"value":1.0},warning=warning,scipy=True)
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "MISMATCH"
    assert result["normalized"]["computability"] == "UNEXPECTED_NONFINITE"


def test_unexpected_exception_is_violation_but_oracle_failure_is_infrastructure_error(monkeypatch):
    adapter, counts = authored_adapter(monkeypatch,None,{"computable":True,"value":1.0},raises=statistics.StatisticsError("authored"))
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "MISMATCH"
    assert result["normalized"]["computability"] == "UNEXPECTED_EXCEPTION"
    adapter, counts = authored_adapter(monkeypatch,1.0,{},oracle_raises=RuntimeError("authored oracle error"))
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "EXECUTION_ERROR"
    assert result["comparison"]["component"] == "ORACLE"
    assert counts == {"target":1,"oracle":1}


def test_fixed_old_tolerance_used_without_output_clipping(monkeypatch):
    adapter,counts = authored_adapter(monkeypatch,1.0+5e-11,{"computable":True,"value":1.0})
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "MATCH"
    assert result["normalized"]["numeric_value"] == 1.0+5e-11
    assert result["comparison"]["contract"]["absolute_tolerance"] == 1e-10
    assert result["comparison"]["contract"]["relative_tolerance"] == 1e-8


def test_unknown_warning_preserves_uncertainty_without_hiding_a_value_mismatch(monkeypatch):
    adapter,counts = authored_adapter(monkeypatch,1.0,{"computable":True,"value":1.0},warning=UserWarning)
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "NOT_COMPARABLE"
    adapter,counts = authored_adapter(monkeypatch,0.0,{"computable":True,"value":1.0},warning=UserWarning)
    result = adapter.evaluate(NORMAL)
    assert result["comparison"]["status"] == "MISMATCH"


def test_actual_target_counts_survive_normalization_failure(monkeypatch):
    class BadFloat(float):
        def __float__(self):
            raise ValueError("authored normalization failure")
    adapter, counts = authored_adapter(monkeypatch,BadFloat(1.0),{"computable":True,"value":1.0})
    with pytest.raises(ValueError,match="normalization failure"):
        adapter.evaluate(NORMAL)
    assert counts == {"target":1,"oracle":0}
    assert adapter.call_counters == {"target_calls":1,"oracle_calls":0,"actual_target_function_entries":1}


def test_helper_in_memory_substitution_changes_approval_identity(monkeypatch):
    before = adapters.adapter_identity()
    monkeypatch.setattr(adapters,"_normalise",lambda *args:{"computability":"UNDEFINED_AS_DOCUMENTED"})
    after = adapters.adapter_identity()
    assert before["code_sha256"] == after["code_sha256"]
    assert before["runtime_callable_code_sha256"] != after["runtime_callable_code_sha256"]


def test_callable_identity_remains_stable_after_its_own_metadata_execution():
    before = adapters.adapter_identity()
    for _ in range(5):
        adapters.oracle_identity()
        assert adapters.adapter_identity() == before


def test_oracle_attempt_count_survives_oracle_error(monkeypatch):
    adapter, counts = authored_adapter(monkeypatch,1.0,{},oracle_raises=RuntimeError("authored Oracle failure"))
    receipt = adapter.evaluate(NORMAL)
    assert receipt["comparison"]["status"] == "EXECUTION_ERROR"
    assert adapter.call_counters == {"target_calls":1,"oracle_calls":1,"actual_target_function_entries":1}


@pytest.mark.parametrize("error", [MemoryError("authored resource failure"), ImportError("authored missing library"), OSError("authored host error")])
def test_environment_failures_are_not_contract_violation_evidence(monkeypatch,error):
    adapter, counts = authored_adapter(monkeypatch,None,{},raises=error)
    receipt = adapter.evaluate(NORMAL)
    assert receipt["comparison"]["status"] == "EXECUTION_ERROR"
    assert receipt["comparison"]["component"] == "TARGET_ENVIRONMENT"
    assert receipt["comparison"]["violation_category"] is None
    assert counts == {"target":1,"oracle":0}
    assert adapter.call_counters == {"target_calls":1,"oracle_calls":0,"actual_target_function_entries":1}
