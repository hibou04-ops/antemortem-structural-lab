"""Public authored/provided numerical diagnostics; no private failure fixtures."""
import ast
from copy import deepcopy
from fractions import Fraction
import hashlib
import inspect
import math
from pathlib import Path

import pytest

from tomolab.discovery import numerical_source as source


def test_historical_production_function_and_result_type_keep_the_reviewed_ast():
    # AST serialization gained the empty type_params field in Python 3.12.
    # Normalize only that empty field, never executable structure.
    expected = {
        "PearsonResult": "bfff87d6438febc67ae951ed11d7d15835affde7f95f355d5d17a08016bd2591",
        "pearson_result": "03ea5e46ff3a910d716e467137d4b30cc30954e70895e767415574a429a5f95c",
    }
    tree = ast.parse(Path(source.__file__).read_text(encoding="utf-8"))
    actual = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False)
                .replace(", type_params=[]", "").encode()).hexdigest()
              for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
              and node.name in expected}
    assert actual == expected
    identity = source.source_identity()
    assert identity["revision"] == "14ff508b2974298305d74c1c90bb43d3c0c13b82"
    assert identity["production_code_modified"] is False
    identity["function_ast_sha256"].clear()
    assert source.source_identity()["function_ast_sha256"]


def test_oracle_math_functions_keep_the_previously_reviewed_helper_ast():
    helper = Path(__file__).resolve().parents[1] / "scripts/evaluate-e7.py"
    names = {"exact_centered", "rational_sqrt", "exact_correlation"}
    original = {node.name: ast.dump(node, include_attributes=False)
                for node in ast.parse(helper.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name in names}
    included = {node.name: ast.dump(node, include_attributes=False)
                for node in ast.parse(Path(source.__file__).read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name in names}
    assert original == included


@pytest.mark.parametrize("point,status,failed", [
    ({"a": [0.1] * 3, "b": [0.1] * 3}, "OK", True),
    ({"a": [0.25] * 3, "b": [0.25] * 3}, "ZERO_VARIANCE_X", False),
    ({"a": [0.1] * 3, "b": [-1.0, 0.0, 1.0]}, "OK", True),
    ({"a": [-1.0, 0.0, 1.0], "b": [0.1] * 3}, "OK", True),
    ({"a": [0.0] * 3, "b": [-1.0, 0.0, 1.0]}, "ZERO_VARIANCE_X", False),
    ({"a": [-1.0, 0.0, 1.0], "b": [0.0] * 3}, "ZERO_VARIANCE_Y", False),
    ({"a": [0.1] * 4, "b": [-1.0, 0.0, 0.0, 1.0]}, "ZERO_VARIANCE_X", False),
])
def test_source_contract_on_public_constant_diagnostics(point, status, failed):
    before = deepcopy(point)
    result = source.evaluate_point(point)
    assert result["source_status"] == status
    assert result["failed"] is failed
    assert result["expected"] == {"computable": False, "value": None}
    assert result["mechanism"] == ("CONSTANT_CENTERING_ROUNDOFF_MISCLASSIFIES_DEGENERACY"
                                   if failed else "NO_FAILURE")
    assert point == before


@pytest.mark.parametrize("sign", [-1, 1])
def test_normal_nondegenerate_control_preserves_numeric_tolerance(sign):
    point = {"a": [-1.0, 0.0, 1.0], "b": [-sign, 0.0, sign]}
    row = source.evaluate_point(point)
    assert row["source_status"] == "OK" and not row["failed"]
    assert row["expected"] == {"computable": True, "value": float(sign)}
    assert row["mechanism"] == "NO_FAILURE"


def test_exact_float_interpretation_and_centering_residual_explain_the_failure():
    values = [0.1] * 3
    assert Fraction.from_float(0.1) != Fraction(1, 10)
    centered, variance = source.exact_centered(values)
    assert variance == 0 and centered == [Fraction(0)] * 3
    rounded_mean = sum(values) / len(values)
    assert rounded_mean != values[0]
    assert sum((v - rounded_mean) ** 2 for v in values) > 0
    features = source.public_numerical_features({"a": values, "b": [0.25] * 3})
    assert features["a"]["all_equal"] and features["a"]["public_centering_residual_nonzero"]
    assert features["b"]["all_equal"] and not features["b"]["public_centering_residual_nonzero"]


def test_one_ulp_change_is_reinterpreted_as_the_actual_float_value():
    values = [0.1, 0.1, math.nextafter(0.1, math.inf)]
    _, variance = source.exact_centered(values)
    assert 0 < variance < Fraction(1, 10 ** 6)
    point = {"a": values, "b": [-1.0, 0.0, 1.0]}
    assert source.oracle_result(point)["computable"] is True
    # Such a near-constant nonconstant is outside the registered Source
    # domain. This isolated math diagnostic does not enter a recipe score.
    assert source.public_numerical_features(point)["a"]["all_equal"] is False


def test_registered_source_domain_accepts_constants_but_rejects_diagnostic_broadening():
    from tomolab.discovery.numerical_guidance import domain_guard, public_input_contract
    assert domain_guard({"a": [0.1] * 3, "b": [-1.0, 0.0, 1.0]})
    assert not domain_guard({"a": [0.1] * 3, "b": [0.0, 1.0, 2.0]})
    near = {"a": [0.1, 0.1, math.nextafter(0.1, math.inf)], "b": [-1.0, 0.0, 1.0]}
    assert not domain_guard(near)
    assert domain_guard(near, public_input_contract("NEAR_CONSTANT_DIAGNOSTIC"))


def test_existing_comparison_keeps_bool_none_and_tolerance_policy():
    assert source.comparison_policy() == {
        "kind": "FINITE_JSON", "absolute_tolerance": 1e-10,
        "relative_tolerance": 1e-8, "undefined": "EXECUTION_ERROR", "exceptions": "EXECUTION_ERROR"}
    assert source.compare_results({"computable": True, "value": 1 + 1e-12},
                                  {"computable": True, "value": 1.0})
    assert not source.compare_results({"computable": True, "value": 0.0},
                                      {"computable": False, "value": None})
    assert not source.compare_results({"computable": 1, "value": None},
                                      {"computable": True, "value": None})
    with pytest.raises(ValueError):
        source.compare_results({"computable": True, "value": float("nan")},
                               {"computable": True, "value": 1.0})
    with pytest.raises(ValueError, match="aligned nonempty"):
        source.oracle_result({"a": [], "b": []})


def test_public_input_features_do_not_run_source_or_oracle(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("output leakage")
    monkeypatch.setattr(source, "pearson_result", forbidden)
    monkeypatch.setattr(source, "exact_correlation", forbidden)
    row = source.public_numerical_features({"a": [0.1] * 3, "b": [-1.0, 0.0, 1.0]})
    assert row["a"]["count"] == 3 and row["a"]["all_equal"]
    assert not row["b"]["all_equal"]


def test_source_only_module_never_imports_original_project_or_loads_code_strings():
    tree = ast.parse(inspect.getsource(source))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith("omega_lock") for name in modules)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"eval", "exec", "compile", "__import__"}
                   for node in ast.walk(tree))
