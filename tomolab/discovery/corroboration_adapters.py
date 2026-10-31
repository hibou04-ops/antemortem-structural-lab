"""Reviewed host-only correlation adapters and the unchanged exact-input Oracle.

These adapters call the selected implementation before interpreting its result.
No implementation, output, exception or Oracle value is sent to a generator.
An implementation identity is evidence for a separate CORR execution permit;
it is neither FINAL_TARGET readiness nor proof that a guide is useful.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib
from importlib.metadata import distribution, version
import inspect
import math
from numbers import Real
from pathlib import Path
import platform
import sys
import time
from types import CodeType
import warnings

from .numerical_guidance import domain_guard, public_input_contract, validate_input_contract
from .schema import canonical, digest

SCHEMA = "tomolab-corroboration-adapter-v1"
ORACLE_ID = "reviewed-exact-binary-input-correlation-v1"
_IMPLEMENTATIONS = {
    "python-statistics-correlation": ("statistics", "correlation", "PSF-2.0",
        "https://docs.python.org/3.12/library/statistics.html#statistics.correlation"),
    "scipy-stats-pearsonr": ("scipy.stats._stats_py", "pearsonr", "BSD-3-Clause",
        "https://github.com/scipy/scipy/blob/v1.18.1/scipy/stats/_stats_py.py"),
}


def reviewed_implementation_ids():
    return tuple(_IMPLEMENTATIONS)


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ast_sha(function):
    tree = ast.parse(inspect.getsource(function))
    # Python 3.13 omits empty fields by default. Explicit display and omission
    # of the empty type_params field preserve the prior structural convention.
    options = {"show_empty":True} if "show_empty" in inspect.signature(ast.dump).parameters else {}
    text = ast.dump(tree, include_attributes=False, **options).replace(", type_params=[]", "")
    return hashlib.sha256(text.encode()).hexdigest()


def _constant_payload(value):
    """Structural constants, independent of marshal reference/intern flags."""
    if value is None:
        return {"kind":"NONE"}
    if value is Ellipsis:
        return {"kind":"ELLIPSIS"}
    if type(value) in (bool, int, str):
        return {"kind":type(value).__name__, "value":value}
    if type(value) is float:
        return {"kind":"float", "hex":value.hex()}
    if type(value) is complex:
        return {"kind":"complex", "real":value.real.hex(), "imaginary":value.imag.hex()}
    if type(value) is bytes:
        return {"kind":"bytes", "hex":value.hex()}
    if type(value) is tuple:
        return {"kind":"tuple", "items":[_constant_payload(item) for item in value]}
    if type(value) is frozenset:
        return {"kind":"frozenset", "items":sorted((_constant_payload(item) for item in value),key=canonical)}
    if isinstance(value, CodeType):
        return {"kind":"code", "value":_code_payload(value)}
    raise ValueError("unreviewed code constant in callable identity")


def _code_payload(code):
    return dict(bytecode=code.co_code.hex(), constants=[_constant_payload(value) for value in code.co_consts],
        names=list(code.co_names), varnames=list(code.co_varnames), freevars=list(code.co_freevars),
        cellvars=list(code.co_cellvars), flags=code.co_flags, argcount=code.co_argcount,
        posonlyargcount=code.co_posonlyargcount, kwonlyargcount=code.co_kwonlyargcount,
        stacksize=code.co_stacksize, name=code.co_name, qualname=code.co_qualname,
        firstlineno=code.co_firstlineno, source_path_sha256=hashlib.sha256(code.co_filename.encode()).hexdigest(),
        line_table=code.co_linetable.hex(), exception_table=code.co_exceptiontable.hex())


def _code_sha(function):
    return digest(_code_payload(function.__code__))


def _resolve(implementation_id):
    if implementation_id not in _IMPLEMENTATIONS:
        raise ValueError("implementation is not in the reviewed fixed allowlist")
    module_name, name, _, _ = _IMPLEMENTATIONS[implementation_id]
    module = importlib.import_module(module_name)
    function = getattr(module, name)
    if (not inspect.isfunction(function) or function.__module__ != module_name
            or function.__name__ != name
            or Path(inspect.getsourcefile(inspect.unwrap(function))).resolve() != Path(module.__file__).resolve()):
        raise PermissionError("reviewed implementation binding or source identity was replaced")
    # The allowlist must never silently resolve to the Oracle/Source helper.
    from . import numerical_source as source
    if function in (source.oracle_result, source.exact_correlation,
                    source.pearson_result, source.target_result):
        raise PermissionError("target and Oracle must not use the same implementation")
    return module, function


def _binary_identity(module_name):
    module = importlib.import_module(module_name)
    path = getattr(module, "__file__", None)
    return dict(module=module_name, filename=Path(path).name,
                sha256=_sha_file(path)) if path else dict(module=module_name, kind="BUILTIN")


def implementation_identity(implementation_id):
    """Capture actual installed code and dependencies without executing inputs.

    Absolute import locations are intentionally excluded from this portable
    identity. ``implementation_location`` provides them to local audit only.
    """
    module, function = _resolve(implementation_id)
    module_name, name, license_id, documentation = _IMPLEMENTATIONS[implementation_id]
    project = "CPython" if implementation_id.startswith("python-") else "scipy"
    package_version = platform.python_version() if project == "CPython" else version("scipy")
    source_sha = _sha_file(module.__file__)
    ast_sha = _ast_sha(function)
    identifier = project.lower()+":"+module_name+":"+name
    result = dict(schema=SCHEMA, implementation_id=implementation_id, project=project,
        version=package_version, revision="INSTALLED_DISTRIBUTION_CONTENT_HASHES",
        import_path=module_name+"."+name, license=license_id,
        public_import_path="statistics.correlation" if project == "CPython" else "scipy.stats.pearsonr",
        function_source_sha256=hashlib.sha256(inspect.getsource(function).encode()).hexdigest(),
        module_source_sha256=source_sha, normalized_ast_sha256=ast_sha,
        loaded_function_code_sha256=_code_sha(function),
        python_implementation=platform.python_implementation(), python_version=platform.python_version(),
        implementation_contract_id=implementation_id+":documented-correlation-v1",
        documentation=documentation, adapter_required=True,
        oracle_lineage="SHARED_REVIEWED_EXACT_MATH_ORACLE_NOT_MULTIPLE_ORACLES",
        canonical_function_label=identifier,
        usage_identity=dict(canonical_function_identity=digest(identifier),
            cross_revision_function_key=digest({"project":project.lower(), "function":module_name+"."+name}),
            normalized_ast_clone_sha256=ast_sha, implementation_sha256=source_sha),
        shared_dependencies_with_source=["CPython floating point runtime"],
        shared_dependencies_with_oracle=["CPython runtime; no common correlation helper"],
        dependency_identities=[])
    if project == "CPython":
        result["core_call_path"] = "statistics.correlation -> math.fsum/sumprod/sqrt (version-specific installed code)"
        result["dependency_identities"] = [_binary_identity("math")]
    else:
        import numpy
        # Imported public API and actual implementation must be identical.
        from scipy import stats
        if stats.pearsonr is not function:
            raise PermissionError("public SciPy binding differs from reviewed implementation")
        array_core = "numpy._core._multiarray_umath" if int(numpy.__version__.split(".")[0]) >= 2 else "numpy.core._multiarray_umath"
        result["core_call_path"] = "scipy.stats.pearsonr -> NumPy array mean/vector norm/array arithmetic"
        result["dependency_identities"] = [dict(project="numpy", version=version("numpy"),
            core_binary=_binary_identity(array_core))]
        result["distribution_metadata_sha256"] = hashlib.sha256(
            (distribution("scipy").read_text("METADATA") or "").encode()).hexdigest()
    result["identity_digest"] = digest(result)
    return result


def implementation_location(implementation_id):
    """Local-only physical import provenance; never transmit to a generator."""
    module, function = _resolve(implementation_id)
    return dict(module_path=str(Path(module.__file__).resolve()),
                function_path=str(Path(inspect.getsourcefile(function)).resolve()))


def adapter_identity():
    return dict(schema=SCHEMA, module="tomolab.discovery.corroboration_adapters",
        code_sha256=_sha_file(__file__), normalization_policy="CALL_FIRST_DOCUMENTED_UNDEFINED_ONLY_V1",
        runtime_callable_code_sha256={name:_code_sha(function)
            for name,function in _component_functions().items()},
        evaluator_side_only=True, final_evaluation_authorized=False)


def oracle_identity():
    from . import numerical_source as source
    helpers = {name:_ast_sha(getattr(source, name))
               for name in ("exact_centered", "rational_sqrt", "exact_correlation", "oracle_result")}
    result = dict(oracle_id=ORACLE_ID, module="tomolab.discovery.numerical_source",
        source_file_sha256=_sha_file(source.__file__), helper_ast_sha256=helpers,
        comparison_policy=source.comparison_policy(),
        exact_binary_inputs=True, degeneracy_epsilon="EXACT_ZERO_UNCHANGED",
        dependency_identities=[_binary_identity("_decimal")],
        lineage="EXISTING_E7_R1_REVIEWED_HELPERS_SHARED_ACROSS_CORR_IMPLEMENTATIONS",
        multiple_independent_oracles=False, target_implementation_called=False)
    result["identity_digest"] = digest(result)
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return dict(kind="NON_NUMERIC", type=type(value).__module__+"."+type(value).__qualname__)
    number = float(value)
    if math.isnan(number):
        return {"kind":"NAN"}
    if math.isinf(number):
        return {"kind":"POSITIVE_INFINITY" if number > 0 else "NEGATIVE_INFINITY"}
    return dict(kind="FINITE", value=number)


def _qualified_type(value):
    cls = value if isinstance(value, type) else type(value)
    return cls.__module__+"."+cls.__qualname__


def _invoke_target(function, point):
    """One actual library invocation; a private test seam, never an API callback."""
    return function(deepcopy(point["a"]), deepcopy(point["b"]))


def _call_with_entry_proof(function, point, *, record_entries=None):
    """Verify one actual public-function entry, including documented raises.

    The profiler observes calls only and forwards any existing callable profile
    hook. It does not mutate inputs, return values, exceptions or warnings.
    Its measured cost is inside every method's target-call interval.
    """
    entries = 0
    previous = sys.getprofile()
    if previous is not None and not callable(previous):
        raise RuntimeError("existing non-callable profiler cannot be composed safely")
    def observe(frame, event, value):
        nonlocal entries
        if event == "call" and frame.f_code is function.__code__:
            entries += 1
        if previous is not None:
            previous(frame, event, value)
    raw, error = None, None
    sys.setprofile(observe)
    try:
        try:
            raw = _invoke_target(function, point)
        except Exception as exc:
            error = exc
    finally:
        sys.setprofile(previous)
        if record_entries is not None:
            record_entries(entries)
    if entries != 1:
        raise PermissionError("adapter must enter the actual approved target exactly once")
    return raw, error, entries


def _component_functions():
    return {"resolve":_resolve, "implementation_identity":implementation_identity,
        "oracle_identity":oracle_identity, "adapter_identity":adapter_identity,
        "number":_number, "normalise":_normalise, "invoke_target":_invoke_target,
        "call_with_entry_proof":_call_with_entry_proof, "component_registry":_component_functions,
        "code_identity":_code_sha, "code_payload":_code_payload, "constant_payload":_constant_payload,
        "constructor":ReviewedCorrelationAdapter.__init__, "evaluate":ReviewedCorrelationAdapter.evaluate,
        "check_oracle":ReviewedCorrelationAdapter._check_oracle_binding,
        "check_components":ReviewedCorrelationAdapter._check_component_bindings}


def _normalise(implementation_id, raw, error, warning_rows, point):
    constant = any(all(value == point[name][0] for value in point[name]) for name in ("a", "b"))
    result = dict(computability="NOT_COMPARABLE", numeric_value=None,
        raw_result_kind="EXCEPTION" if error is not None else _qualified_type(raw),
        exception_type=None if error is None else _qualified_type(error),
        warning_types=[row["type"] for row in warning_rows],
        implementation_contract_id=implementation_id+":documented-correlation-v1")
    if error is not None:
        import statistics
        result["computability"] = ("UNDEFINED_AS_DOCUMENTED" if implementation_id == "python-statistics-correlation"
            and constant and isinstance(error, statistics.StatisticsError) else "UNEXPECTED_EXCEPTION")
        return result, {"exception_type":_qualified_type(error), "exception_message":str(error),
                        "warnings":warning_rows}
    statistic = raw
    raw_record = {"result_type":_qualified_type(raw), "warnings":warning_rows}
    if implementation_id == "scipy-stats-pearsonr":
        if not hasattr(raw, "statistic"):
            raw_record["result_kind"] = "MISSING_DOCUMENTED_STATISTIC"
            return result, raw_record
        statistic = raw.statistic
        raw_record["pvalue"] = _number(getattr(raw, "pvalue", None))
    numeric = _number(statistic)
    raw_record["statistic"] = numeric
    if numeric["kind"] == "FINITE":
        result.update(computability="DEFINED", numeric_value=numeric["value"])
    if numeric["kind"] in ("NAN", "POSITIVE_INFINITY", "NEGATIVE_INFINITY"):
        documented_nan = (implementation_id == "scipy-stats-pearsonr" and constant
            and numeric["kind"] == "NAN" and any(
                row["type"] == "scipy.stats._warnings_errors.ConstantInputWarning" for row in warning_rows))
        result["computability"] = "UNDEFINED_AS_DOCUMENTED" if documented_nan else "UNEXPECTED_NONFINITE"
    return result, raw_record


class ReviewedCorrelationAdapter:
    """Immutable selected implementation; no generic import or callable option."""
    def __init__(self, implementation_id, *, expected_identity):
        actual = implementation_identity(implementation_id)
        if not isinstance(expected_identity, dict) or canonical(actual) != canonical(expected_identity):
            raise PermissionError("installed implementation differs from the approved identity")
        self._implementation_id = implementation_id
        self._identity = deepcopy(actual)
        self._module, self._function = _resolve(implementation_id)
        self._function_code = _code_sha(self._function)
        self._call_counters = dict(target_calls=0, oracle_calls=0, actual_target_function_entries=0)
        from . import numerical_source as source
        self._oracle_functions = {name:(getattr(source, name), _code_sha(getattr(source, name)))
            for name in ("oracle_result", "exact_correlation", "exact_centered",
                         "rational_sqrt", "compare_results", "comparison_policy")}
        self._component_bindings = {name:(function, _code_sha(function))
            for name,function in _component_functions().items()}

    def _check_component_bindings(self):
        current = _component_functions()
        for name, (function, code_sha) in self._component_bindings.items():
            if current.get(name) is not function or _code_sha(function) != code_sha:
                raise PermissionError("reviewed adapter component changed after approval")

    def _check_oracle_binding(self):
        from . import numerical_source as source
        for name, (function, code_sha) in self._oracle_functions.items():
            if getattr(source, name) is not function or _code_sha(function) != code_sha:
                raise PermissionError("reviewed Oracle or comparison binding changed during execution")

    @property
    def identity(self):
        return deepcopy(self._identity)

    @property
    def call_counters(self):
        """Monotonic actual/attempted counts survive partial evaluation errors."""
        return deepcopy(self._call_counters)

    def _record_target_entries(self, entries):
        self._call_counters["target_calls"] += entries
        self._call_counters["actual_target_function_entries"] += entries

    def evaluate(self, point, *, contract=None):
        """One target/Oracle pair; confirmation belongs to the CORR runner."""
        started = time.perf_counter()
        self._check_component_bindings()
        contract = public_input_contract() if contract is None else validate_input_contract(contract)
        if contract["profile"] != "SOURCE_DOMAIN":
            raise ValueError("CORR requires the unchanged reviewed SOURCE_DOMAIN")
        if not domain_guard(point, contract):
            raise ValueError("CORR input is outside the existing reviewed domain")
        _, live = _resolve(self._implementation_id)
        if live is not self._function or _code_sha(live) != self._function_code:
            raise PermissionError("approved target binding changed after adapter construction")
        self._check_oracle_binding()
        raw, error = None, None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tick = time.perf_counter()
            raw, error, entries = _call_with_entry_proof(self._function, point,
                record_entries=self._record_target_entries)
            target_seconds = time.perf_counter()-tick
        tick = time.perf_counter()
        warning_rows = [dict(type=_qualified_type(item.category), name=item.category.__name__,
            message=str(item.message), source_filename=Path(item.filename).name, source_line=item.lineno)
            for item in caught]
        normalized, raw_record = _normalise(self._implementation_id, raw, error, warning_rows, point)
        normalization_seconds = time.perf_counter()-tick
        result = dict(schema=SCHEMA, implementation_id=self._implementation_id,
            target_calls=1, oracle_calls=0, normalized=normalized, raw_outcome=raw_record,
            actual_target_function_entries=entries,
            expected=None, comparison=None,
            timings=dict(target_call_seconds=target_seconds, normalization_seconds=normalization_seconds,
                         oracle_seconds=None, comparison_seconds=None, adapter_total_seconds=None))
        if isinstance(error, (MemoryError, ImportError, OSError, RecursionError)):
            result["comparison"] = dict(status="EXECUTION_ERROR", component="TARGET_ENVIRONMENT",
                violation_category=None, confirmed=False)
            result["timings"]["adapter_total_seconds"] = time.perf_counter()-started
            canonical(result)
            return result
        from . import numerical_source as source
        self._check_oracle_binding()
        tick = time.perf_counter()
        try:
            result["oracle_calls"] = 1
            self._call_counters["oracle_calls"] += 1
            expected = source.oracle_result(deepcopy(point))
            canonical(expected)
            result["expected"] = expected
        except Exception as exc:
            result["oracle_error"] = {"type":_qualified_type(exc), "message":str(exc)}
            result["comparison"] = {"status":"EXECUTION_ERROR", "component":"ORACLE", "violation_category":None}
        finally:
            result["timings"]["oracle_seconds"] = time.perf_counter()-tick
        if result["comparison"] is None:
            tick = time.perf_counter()
            state = normalized["computability"]
            violation = None
            if state == "NOT_COMPARABLE":
                status = "NOT_COMPARABLE"
            elif state == "UNEXPECTED_EXCEPTION":
                status, violation = "MISMATCH", "UNDOCUMENTED_EXCEPTION"
            elif state == "UNEXPECTED_NONFINITE":
                status, violation = "MISMATCH", "UNDOCUMENTED_NONFINITE_RESULT"
            else:
                actual = {"computable":state == "DEFINED", "value":normalized["numeric_value"]}
                matches = source.compare_results(actual, result["expected"])
                status = "MATCH" if matches else "MISMATCH"
                if not matches:
                    violation = "FINITE_VALUE_FOR_EXACT_CONSTANT_INPUT" if result["expected"]["computable"] is False else "NUMERIC_VALUE_DISAGREEMENT_REQUIRES_REVIEW"
                else:
                    accepted_warnings = ({"scipy.stats._warnings_errors.ConstantInputWarning",
                        "scipy.stats._warnings_errors.NearConstantInputWarning"}
                        if self._implementation_id == "scipy-stats-pearsonr" else set())
                    constant = any(all(value == point[name][0] for value in point[name]) for name in ("a", "b"))
                    if not constant:
                        accepted_warnings.discard("scipy.stats._warnings_errors.ConstantInputWarning")
                    if any(row["type"] not in accepted_warnings for row in warning_rows):
                        status = "NOT_COMPARABLE"
            result["comparison"] = dict(status=status, violation_category=violation,
                contract=source.comparison_policy(), confirmed=False)
            result["timings"]["comparison_seconds"] = time.perf_counter()-tick
        result["timings"]["adapter_total_seconds"] = time.perf_counter()-started
        canonical(result)
        return result


def create_reviewed_adapter(implementation_id, *, expected_identity):
    return ReviewedCorrelationAdapter(implementation_id, expected_identity=expected_identity)


def evaluate_implementation(implementation_id, point, *, contract=None, expected_identity):
    return create_reviewed_adapter(implementation_id, expected_identity=expected_identity).evaluate(point, contract=contract)
