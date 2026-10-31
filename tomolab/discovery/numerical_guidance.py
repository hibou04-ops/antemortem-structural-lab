"""Input-only numerical recipes and native Hypothesis generation.

Recipes are executable data for a reviewed numeric profile, not failure
predicates. Only ``calibrate_recipe`` sees DEVELOPMENT membership labels;
generation and worker paths receive bounded aggregates, never Oracle output.
The public constant/centering prior is identical for B, C and D.
"""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import math
import random
import re
import time

from .schema import canonical, digest, integer, keys

CONTRACT_SCHEMA = "tomolab-numerical-input-contract-v1"
RECIPE_SCHEMA = "tomolab-failure-guidance-recipe-v1"
ORIGINS = ("HAND_SPECIFIED_PRIOR", "SOURCE_CALIBRATED_GUIDANCE", "OBSERVED_VALIDATION_RESULT")
FAMILIES = ("BOTH_CONSTANT_RESIDUAL", "X_CONSTANT_RESIDUAL", "Y_CONSTANT_RESIDUAL",
            "CONSTANT_EXACT_CENTERING", "PATTERNED_NONDEGENERATE", "NATIVE_NONDEGENERATE")
TRANSFORMATIONS = ("VALUE_AND_LENGTH", "ONE_CONSTANT_AXIS", "BINARY_DECIMAL_CONTRAST",
                   "SIGN_SCALE_EXPONENT", "ADJACENT_FLOAT", "PERMUTE_AND_REPEAT", "NORMAL_CONTROL")
PUBLIC_PRIOR = {
    "origin_type": "HAND_SPECIFIED_PRIOR",
    "knowledge": "Constant Pearson inputs are degenerate; rounded centering can leave a nonzero residual.",
    "source": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html",
    "limits": "Public mathematical and source-arithmetic knowledge; not learned or a universal float invariant.",
}
COMPARISON_CONTRACT = {"kind": "FINITE_JSON", "absolute_tolerance": 1e-10,
                       "relative_tolerance": 1e-8, "undefined": "EXECUTION_ERROR",
                       "exceptions": "EXECUTION_ERROR"}


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("pinned SHA-256 required")
    return value


def public_input_contract(profile="SOURCE_DOMAIN", *, lengths=None):
    """The original source domain; near-constant exploration is explicit."""
    result = {"schema": CONTRACT_SCHEMA, "profile": profile,
              "lengths": [3, 4, 5, 6] if lengths is None else list(lengths),
              "minimum": -1.0, "maximum": 1.0,
              "nonconstant_centered_ss_min": "1/1000000" if profile == "SOURCE_DOMAIN" else "0"}
    return validate_input_contract(result)


def validate_input_contract(value):
    keys(value, ("schema", "profile", "lengths", "minimum", "maximum", "nonconstant_centered_ss_min"))
    if value["schema"] != CONTRACT_SCHEMA or value["profile"] not in ("SOURCE_DOMAIN", "NEAR_CONSTANT_DIAGNOSTIC"):
        raise ValueError("unsupported numerical input profile")
    lengths = value["lengths"]
    if not isinstance(lengths, list) or not lengths or lengths != sorted(set(lengths)):
        raise ValueError("ordered nonempty length subset required")
    for n in lengths:
        integer(n, 3, 6)
    expected_floor = "1/1000000" if value["profile"] == "SOURCE_DOMAIN" else "0"
    if (type(value["minimum"]) not in (int, float) or type(value["maximum"]) not in (int, float)
            or value["minimum"] != -1 or value["maximum"] != 1
            or value["nonconstant_centered_ss_min"] != expected_floor):
        raise ValueError("the reviewed numeric range and variance domain cannot be broadened implicitly")
    canonical(value)
    return deepcopy(value)


def _exact_ss(values):
    exact = [Fraction.from_float(float(v)) for v in values]
    mean = sum(exact) / len(exact)
    return sum((v - mean)**2 for v in exact)


def domain_guard(inputs, contract=None):
    """Reject out-of-domain inputs before labels; exact float values matter."""
    contract = public_input_contract() if contract is None else validate_input_contract(contract)
    if not isinstance(inputs, dict) or set(inputs) != {"a", "b"}:
        return False
    xs, ys = inputs["a"], inputs["b"]
    if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys) or len(xs) not in contract["lengths"]:
        return False
    floor = Fraction(contract["nonconstant_centered_ss_min"])
    for values in (xs, ys):
        if any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in values):
            return False
        ss = _exact_ss(values)
        if ss != 0 and ss < floor:
            return False
    return True


def input_features(inputs):
    """Features use inputs and the published source arithmetic, never labels."""
    if not domain_guard(inputs, public_input_contract("NEAR_CONSTANT_DIAGNOSTIC")):
        raise ValueError("finite paired reviewed numerical inputs required")
    result = {"origin_type": "HAND_SPECIFIED_PRIOR", "length": len(inputs["a"])}
    for name in ("a", "b"):
        values = [float(x) for x in inputs[name]]
        mean = sum(values)/len(values)
        centered = [x-mean for x in values]
        result[name] = {"all_identical": all(x == values[0] for x in values),
                        "spread": max(values)-min(values), "scale": max(abs(x) for x in values),
                        "max_ulp": max(math.ulp(x) for x in values),
                        "rounded_centered_ss": sum(x*x for x in centered),
                        "centering_residual_nonzero": any(x != 0 for x in centered),
                        "exact_degenerate": _exact_ss(values) == 0}
    return result


def numerical_input_digest(inputs):
    """Identity after the reviewed float argument conversion, not JSON spelling.

    For this source, ``0`` and ``0.0`` become the same binary float. Hashing
    their JSON spellings as different would inflate fresh-input discovery.
    """
    if not domain_guard(inputs, public_input_contract("NEAR_CONSTANT_DIAGNOSTIC")):
        raise ValueError("finite paired reviewed numerical inputs required")
    return digest({name: [float(x) for x in inputs[name]] for name in ("a", "b")})


def _family(inputs):
    f = input_features(inputs)
    x, y = f["a"], f["b"]
    if x["all_identical"] and y["all_identical"]:
        return "BOTH_CONSTANT_RESIDUAL" if x["centering_residual_nonzero"] and y["centering_residual_nonzero"] else "CONSTANT_EXACT_CENTERING"
    if x["all_identical"]:
        return "X_CONSTANT_RESIDUAL" if x["centering_residual_nonzero"] else "CONSTANT_EXACT_CENTERING"
    if y["all_identical"]:
        return "Y_CONSTANT_RESIDUAL" if y["centering_residual_nonzero"] else "CONSTANT_EXACT_CENTERING"
    return "NATIVE_NONDEGENERATE"


@dataclass(frozen=True)
class FailureGuidanceRecipe:
    """A strict data contract. Frozen serialization is checked at every use."""
    _serialized: str

    @classmethod
    def from_dict(cls, value):
        fields = ("schema_version", "recipe_id", "source_evidence_refs", "origin_type", "public_contract",
                  "mechanism_hypotheses", "input_properties", "permitted_transformations",
                  "parameter_strategy", "domain_guard", "comparison_contract", "known_counterevidence",
                  "development_validation", "cost_budget", "provenance")
        keys(value, fields)
        if value["schema_version"] != RECIPE_SCHEMA or value["origin_type"] not in ORIGINS[:2]:
            raise ValueError("unsupported recipe schema or origin")
        if value["recipe_id"] != "source-pearson-centering-v1":
            raise ValueError("unapproved numerical recipe")
        refs = value["source_evidence_refs"]
        if not isinstance(refs, list) or not 1 <= len(refs) <= 1024 or len(set(refs)) != len(refs):
            raise ValueError("bounded unique evidence references required")
        for ref in refs:
            if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", ref):
                raise ValueError("invalid evidence reference")
        contract = validate_input_contract(value["public_contract"])
        if value["domain_guard"] != {"kind": "EXACT_INPUT_CENTERED_SUM_SQUARES", "contract_sha256": digest(contract)}:
            raise ValueError("recipe domain guard differs")
        if value["comparison_contract"] != COMPARISON_CONTRACT:
            raise ValueError("the reviewed numerical comparison contract must be preserved")
        if value["permitted_transformations"] != list(TRANSFORMATIONS):
            raise ValueError("unapproved transformation or executable content")
        if value["mechanism_hypotheses"] != ["ROUNDED_CENTERING_CAN_MASK_EXACT_CONSTANT_VARIANCE"]:
            raise ValueError("unreviewed mechanism hypothesis")
        if value["input_properties"] != ["EXACT_FLOAT_EQUALITY", "LENGTH", "SCALE_ULP", "PUBLIC_CENTERING_RESIDUAL"]:
            raise ValueError("unreviewed input feature")
        parameters = value["parameter_strategy"]
        keys(parameters, ("families", "weights", "selection_rule", "calibration_counts"))
        if parameters["families"] != list(FAMILIES) or parameters["selection_rule"] != "1_PLUS_FLOOR_15_FAILURES_OVER_ALL_WITHIN_FAMILY":
            raise ValueError("unreviewed strategy family or policy")
        weights, counts = parameters["weights"], parameters["calibration_counts"]
        if not isinstance(weights, dict) or set(weights) != set(FAMILIES) or not isinstance(counts, dict) or set(counts) != set(FAMILIES):
            raise ValueError("complete bounded strategy weights required")
        for family in FAMILIES:
            integer(weights[family], 1, 16)
            keys(counts[family], ("failure", "normal"))
            integer(counts[family]["failure"], 0, 16384); integer(counts[family]["normal"], 0, 16384)
            total = sum(counts[family].values())
            expected = 1 + 15*counts[family]["failure"]//total if total else 1
            if weights[family] != expected:
                raise ValueError("weights differ from frozen calibration rule")
        total_failures = sum(v["failure"] for v in counts.values())
        total_normals = sum(v["normal"] for v in counts.values())
        if total_failures + total_normals > 16384 or not total_failures or not total_normals:
            raise ValueError("bounded failure and normal calibration support required")
        counter = value["known_counterevidence"]
        keys(counter, ("state", "normal_observations", "quarantined_observations"))
        if counter["state"] != "PRESERVED_AS_COUNTEREVIDENCE_NOT_A_FAILURE_CLASSIFIER":
            raise ValueError("explicit counterevidence scope required")
        for key in ("normal_observations", "quarantined_observations"):
            integer(counter[key], 0, 16384)
        if counter["normal_observations"] != total_normals or total_failures + total_normals + counter["quarantined_observations"] > 16384:
            raise ValueError("counterevidence differs from calibration support")
        validation = value["development_validation"]
        keys(validation, ("origin_type", "status"))
        if validation != {"origin_type": "OBSERVED_VALIDATION_RESULT", "status": "NOT_YET_EXECUTED_SEPARATE_RECEIPT_REQUIRED"}:
            raise ValueError("validation results cannot be folded back into the frozen recipe")
        if value["cost_budget"] != {"max_candidates": 1024, "max_examples": 8192, "max_shrink_calls": 1024}:
            raise ValueError("recipe resource bounds differ")
        provenance = value["provenance"]
        keys(provenance, ("source_archive_digest", "prior", "calibration_scope", "oracle_outputs_included"))
        _sha(provenance["source_archive_digest"])
        if provenance["prior"] != PUBLIC_PRIOR or provenance["calibration_scope"] != "SOURCE_DEVELOPMENT_ONLY" or provenance["oracle_outputs_included"] is not False:
            raise ValueError("recipe provenance must separate public prior and Source calibration")
        if len(canonical(value).encode()) > 256*1024:
            raise ValueError("recipe exceeds compact data bound")
        return cls(canonical(value))

    def to_dict(self):
        import json
        return json.loads(self._serialized)


def calibrate_recipe(observations, *, source_evidence_refs, archive_digest, contract=None):
    """Fit only family allocation, not outputs, exact input values or predicates.

    The trusted host must first validate archive linkage. Minimal rows are
    ``{inputs,status}`` with status FAILURE/REFUTATION. Invalid/domain-rejected
    rows remain quarantined and cannot become negative training examples.
    """
    contract = public_input_contract() if contract is None else validate_input_contract(contract)
    _sha(archive_digest)
    if not isinstance(observations, list) or not 1 <= len(observations) <= 16384:
        raise ValueError("bounded DEVELOPMENT calibration observations required")
    counts = {family: {"failure": 0, "normal": 0} for family in FAMILIES}
    quarantined = 0
    for row in observations:
        keys(row, ("inputs", "status"), ("evidence_ref",))
        if row["status"] not in ("FAILURE", "REFUTATION") or not domain_guard(row["inputs"], contract):
            quarantined += 1
            continue
        counts[_family(row["inputs"])]["failure" if row["status"] == "FAILURE" else "normal"] += 1
    failures = sum(v["failure"] for v in counts.values())
    normals = sum(v["normal"] for v in counts.values())
    if not failures or not normals:
        raise ValueError("Source-calibrated guidance requires actual failure and normal DEVELOPMENT observations")
    weights = {k: 1+15*v["failure"]//sum(v.values()) if sum(v.values()) else 1 for k, v in counts.items()}
    recipe = dict(schema_version=RECIPE_SCHEMA, recipe_id="source-pearson-centering-v1",
                  source_evidence_refs=list(source_evidence_refs), origin_type="SOURCE_CALIBRATED_GUIDANCE",
                  public_contract=contract, mechanism_hypotheses=["ROUNDED_CENTERING_CAN_MASK_EXACT_CONSTANT_VARIANCE"],
                  input_properties=["EXACT_FLOAT_EQUALITY", "LENGTH", "SCALE_ULP", "PUBLIC_CENTERING_RESIDUAL"],
                  permitted_transformations=list(TRANSFORMATIONS),
                  parameter_strategy={"families": list(FAMILIES), "weights": weights,
                                      "selection_rule": "1_PLUS_FLOOR_15_FAILURES_OVER_ALL_WITHIN_FAMILY",
                                      "calibration_counts": counts},
                  domain_guard={"kind": "EXACT_INPUT_CENTERED_SUM_SQUARES", "contract_sha256": digest(contract)},
                  comparison_contract=deepcopy(COMPARISON_CONTRACT),
                  known_counterevidence={"state": "PRESERVED_AS_COUNTEREVIDENCE_NOT_A_FAILURE_CLASSIFIER",
                                        "normal_observations": normals, "quarantined_observations": quarantined},
                  development_validation={"origin_type": "OBSERVED_VALIDATION_RESULT",
                                          "status": "NOT_YET_EXECUTED_SEPARATE_RECEIPT_REQUIRED"},
                  cost_budget={"max_candidates": 1024, "max_examples": 8192, "max_shrink_calls": 1024},
                  provenance={"source_archive_digest": archive_digest, "prior": deepcopy(PUBLIC_PRIOR),
                              "calibration_scope": "SOURCE_DEVELOPMENT_ONLY", "oracle_outputs_included": False})
    return FailureGuidanceRecipe.from_dict(recipe)


def numerical_strategy(method, *, recipe=None, contract=None, replay_inputs=None):
    """Native strategies; B receives the same full public numerical prior as D."""
    from hypothesis import strategies as st
    if method not in ("A", "B", "C", "D"):
        raise ValueError("method must be A, B, C or D")
    if recipe is not None:
        recipe = FailureGuidanceRecipe.from_dict(recipe).to_dict()
    if method == "D" and recipe is None:
        raise ValueError("D requires a frozen Source-calibrated recipe")
    contract = (recipe["public_contract"] if recipe is not None else public_input_contract()) if contract is None else validate_input_contract(contract)
    if recipe is not None and (contract["profile"] != recipe["public_contract"]["profile"] or not set(contract["lengths"]) <= set(recipe["public_contract"]["lengths"])):
        raise ValueError("generation contract must remain within the calibrated applicability scope")
    lengths = st.sampled_from(contract["lengths"])
    native = st.floats(-1, 1, allow_nan=False, allow_infinity=False, width=64)
    if method == "A":
        # Ordinary typed lists have independently drawn lengths, as in R1.
        values = st.lists(native, min_size=min(contract["lengths"]), max_size=max(contract["lengths"]))
        return st.fixed_dictionaries({"a": values, "b": values}).map(lambda p: (p, "NATIVE_TYPED_STRATEGY"))

    @st.composite
    def value_strategy(draw):
        # Binary and decimal public priors: a parameter grammar, not a stored
        # list of failing floats. Scale/sign/adjacent changes are re-evaluated.
        representation = draw(st.integers(0, 2))
        if representation == 0:
            value = draw(native)
        elif representation == 1:
            numerator = draw(st.integers(-16, 16))
            exponent = draw(st.integers(-12, -4))
            value = math.ldexp(float(numerator), exponent)
        else:
            numerator = draw(st.integers(-9, 9))
            denominator = draw(st.sampled_from([10, 100, 1000]))
            value = float(numerator/denominator)
        if draw(st.booleans()):
            value = math.nextafter(value, 1.0 if draw(st.booleans()) else -1.0)
        return max(-1.0, min(1.0, value))

    value = value_strategy()
    if method == "C":
        if not isinstance(replay_inputs, list) or not replay_inputs or len(replay_inputs) > 1024:
            raise ValueError("C requires bounded reviewed Source failure inputs at the host")
        if any(not domain_guard(p, public_input_contract(contract["profile"])) for p in replay_inputs):
            raise ValueError("replay source inputs must satisfy the reviewed domain")
        @st.composite
        def mutations(draw):
            point = deepcopy(draw(st.sampled_from(replay_inputs)))
            n = draw(lengths)
            point = {name: [float(values[i % len(values)]) for i in range(n)] for name, values in point.items()}
            shift = draw(st.integers(0, n-1))
            if draw(st.booleans()):
                point = {k: list(reversed(v)) for k, v in point.items()}
            point = {k: v[shift:]+v[:shift] for k, v in point.items()}
            sign = draw(st.sampled_from([-1, 1])); exponent = draw(st.integers(-4, 0))
            point = {k: [math.ldexp(sign*x, exponent) for x in v] for k, v in point.items()}
            if draw(st.booleans()):
                point = {"a": point["b"], "b": point["a"]}
            if draw(st.booleans()):
                # Shift each value together; no claim of bitwise invariance.
                toward = draw(st.sampled_from([-1.0, 1.0]))
                point = {k: [math.nextafter(x, toward) for x in v] for k, v in point.items()}
            return point, "GENERIC_REPLAY_TRANSFORM"
        return mutations()
    weights = recipe["parameter_strategy"]["weights"] if method == "D" else dict.fromkeys(FAMILIES, 1)
    family_choice = st.sampled_from([family for family in FAMILIES for _ in range(weights[family])])

    @st.composite
    def informed(draw):
        family = draw(family_choice); n = draw(lengths)
        a = draw(value); b = draw(value)
        ordinary = draw(st.lists(native, min_size=n, max_size=n))
        if family == "BOTH_CONSTANT_RESIDUAL":
            point = {"a": [a]*n, "b": [b]*n}
        elif family == "X_CONSTANT_RESIDUAL":
            point = {"a": [a]*n, "b": ordinary}
        elif family == "Y_CONSTANT_RESIDUAL":
            point = {"a": ordinary, "b": [b]*n}
        elif family == "CONSTANT_EXACT_CENTERING":
            exact = math.ldexp(float(draw(st.integers(-16, 16))), -5)
            point = {"a": [exact]*n, "b": ordinary}
        elif family == "PATTERNED_NONDEGENERATE":
            # Normal contrast with exact values and alternating/repeated order.
            anchor = draw(st.sampled_from([0.125, 0.25, 0.5]))
            xs = [anchor if i % 2 else -anchor for i in range(n)]
            shift = draw(st.integers(0, n-1))
            ys = xs[shift:]+xs[:shift]
            point = {"a": xs, "b": list(reversed(ys)) if draw(st.booleans()) else ys}
        else:
            point = {"a": ordinary, "b": draw(st.lists(native, min_size=n, max_size=n))}
        # Requested family is a proposal, not a failure label. A public
        # mechanism filter is charged separately by the collector.
        return point, family
    return informed()


def generate_numerical_candidates(method, *, recipe=None, seed=7, size=32, max_examples=1024,
                                  excluded_digests=(), replay_inputs=None, contract=None):
    """Collect bounded native draws. No Target/Oracle callable is accepted."""
    started, cpu = time.perf_counter(), time.process_time()
    from hypothesis import HealthCheck, Phase, given, seed as hypothesis_seed, settings
    integer(seed, 0, 2**32-1); integer(size, 1, 1024); integer(max_examples, 1, 8192)
    if not isinstance(excluded_digests, (list, tuple, set)) or len(excluded_digests) > 16384:
        raise ValueError("bounded existing input digest set required")
    excluded = {_sha(v) for v in excluded_digests}
    normalized = FailureGuidanceRecipe.from_dict(recipe).to_dict() if recipe is not None else None
    contract = (normalized["public_contract"] if normalized else public_input_contract()) if contract is None else validate_input_contract(contract)
    strategy = numerical_strategy(method, recipe=normalized, contract=contract, replay_inputs=replay_inputs)
    result = {"schema": "tomolab-numerical-candidates-v1", "method": method, "candidates": [],
              "attempts": 0, "domain_rejections": 0, "duplicate_rejections": 0,
              "existing_input_rejections": 0, "mechanism_filter_rejections": 0,
              "explicit_replays": 0, "oracle_calls": 0, "target_calls": 0}
    seen = set()
    def append(point, transform, origin, *, replay=False):
        if not domain_guard(point, contract):
            result["domain_rejections"] += 1
            return
        point = {name: [float(x) for x in point[name]] for name in ("a", "b")}
        token = numerical_input_digest(point)
        if token in seen:
            result["duplicate_rejections"] += 1
            return
        if not replay and token in excluded:
            result["existing_input_rejections"] += 1
            return
        seen.add(token)
        result["candidates"].append({"inputs": deepcopy(point), "origin": origin,
                                      "recipe_id": normalized["recipe_id"] if method == "D" else None,
                                      "transform": transform, "features": input_features(point)})
        if replay:
            result["explicit_replays"] += 1
    if method == "C":
        for point in replay_inputs:
            if len(result["candidates"]) >= size:
                break
            append(point, "EXPLICIT_COUNTEREXAMPLE_REPLAY", "KNOWN_INPUT_REPLAY", replay=True)
    class Complete(BaseException):
        pass
    @hypothesis_seed(seed)
    @settings(max_examples=max_examples, deadline=None, database=None, phases=[Phase.generate],
              suppress_health_check=list(HealthCheck), report_multiple_bugs=False)
    @given(strategy)
    def collect(proposal):
        result["attempts"] += 1
        point, family = proposal
        # Domain rejection takes precedence over a mechanism proposal: an
        # excluded near-constant input is never labelled normal or hidden in
        # an ordinary family-filter miss.
        if not domain_guard(point, contract):
            result["domain_rejections"] += 1
            return
        if family.endswith("CONSTANT_RESIDUAL"):
            try:
                matched = _family(point) == family
            except ValueError:
                matched = False
            if not matched:
                result["mechanism_filter_rejections"] += 1
                return
        origin = "SOURCE_CALIBRATED_GUIDANCE" if method == "D" else "SOURCE_REPLAY_GENERIC_TRANSFORMATION" if method == "C" else "HAND_SPECIFIED_PRIOR" if method == "B" else "NATIVE_TYPED_STRATEGY"
        append(point, family, origin)
        if len(result["candidates"]) >= size:
            raise Complete()
    if len(result["candidates"]) < size:
        try:
            collect()
        except Complete:
            pass
    result.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
                  stop="REQUESTED_CANDIDATES" if len(result["candidates"]) == size else "DRAW_BUDGET_OR_DOMAIN_EXHAUSTED")
    return result


def shrink_numerical_failure(predicate, *, method="B", recipe=None, contract=None,
                              replay_inputs=None, initial_witness=None, budget=128, seed=7):
    """Trusted-host native find+shrink, with every predicate invocation charged.

    With ``initial_witness`` this first reproduces that actual observed failure,
    then searches only bounded transforms derived from it, preserving each
    axis's exact constant/nonconstant structure. Without it this is a fresh
    native find+shrink search, explicitly not shrinking an earlier witness.
    Neither mode proves global mathematical minimality. Workers never receive
    this callback or the original witness.
    """
    started = time.perf_counter()
    from hypothesis import HealthCheck, Phase, find, settings, strategies as st
    from hypothesis.errors import NoSuchExample, Unsatisfiable
    from .hypothesis_adapter import BudgetExhausted
    if not callable(predicate):
        raise ValueError("caller-reviewed host predicate required")
    integer(budget, 1, 1024); integer(seed, 0, 2**32-1)
    contract = (recipe["public_contract"] if recipe else public_input_contract()) if contract is None else validate_input_contract(contract)
    calls = 0; attempts = 0; rejected = 0; structure_rejected = 0; failures = []; first_failure = None
    original = None
    constant_axes = None
    if initial_witness is None:
        strategy = numerical_strategy(method, recipe=recipe, contract=contract, replay_inputs=replay_inputs)
    else:
        if not domain_guard(initial_witness, contract):
            raise ValueError("initial witness must satisfy the declared shrink domain")
        original = {name: [float(x) for x in initial_witness[name]] for name in ("a", "b")}
        constant_axes = {name: _exact_ss(original[name]) == 0 for name in ("a", "b")}
        lengths = [n for n in contract["lengths"] if n <= len(original["a"])]

        @st.composite
        def initial_transforms(draw):
            n = draw(st.sampled_from(lengths))
            # Shrinking this rank toward zero proposes smaller magnitudes.
            # The unmodified original is also in the union, so a failed search
            # never discards the already reproduced witness.
            exponent = draw(st.integers(0, 24)) - 24
            adjacent_steps = draw(st.integers(0, 2))
            point = {}
            for name in ("a", "b"):
                values = [math.ldexp(x, exponent) for x in original[name][:n]]
                for _ in range(adjacent_steps):
                    values = [math.nextafter(x, 0.0) for x in values]
                point[name] = values
            return point, "INITIAL_WITNESS_PREFIX_SCALE_ADJACENT"
        strategy = st.one_of(initial_transforms(), st.just((original, "INITIAL_WITNESS_IDENTITY")))

    def invoke(point):
        nonlocal calls, first_failure
        if calls >= budget:
            raise BudgetExhausted()
        calls += 1
        failed = predicate(deepcopy(point))
        if type(failed) is not bool:
            raise ValueError("predicate must return an exact bool")
        if failed:
            failures.append(deepcopy(point))
            if first_failure is None:
                first_failure = time.perf_counter()-started
        return failed

    if original is not None and not invoke(original):
        raise ValueError("initial witness did not reproduce the declared failure")

    def condition(proposal):
        nonlocal attempts, rejected, structure_rejected
        attempts += 1; point, _ = proposal
        if not domain_guard(point, contract):
            rejected += 1; return False
        if constant_axes is not None and any((_exact_ss(point[name]) == 0) != constant_axes[name] for name in ("a", "b")):
            structure_rejected += 1; return False
        return invoke(point)
    witness = None; stop = "COMPLETE"
    if calls >= budget:
        stop = "RESOURCE_BUDGET"
    else:
        try:
            witness = find(strategy, condition, random=random.Random(seed),
                           settings=settings(max_examples=budget, deadline=None, database=None,
                                             phases=[Phase.generate, Phase.shrink],
                                             suppress_health_check=list(HealthCheck)))[0]
        except BudgetExhausted:
            stop = "RESOURCE_BUDGET"
        except (NoSuchExample, Unsatisfiable):
            stop = "NO_WITNESS_WITHIN_BUDGET"
    if witness is None and failures:
        # Only failures actually observed in this shrink transaction can be
        # returned. In witness mode the reproduced original is always retained.
        witness = min(failures, key=lambda p: (len(p["a"]), max(abs(x) for v in p.values() for x in v), len(canonical(p)), canonical(p)))
    return {"schema": "tomolab-numerical-shrink-v1", "witness": deepcopy(witness),
            "witness_mode": "INITIAL_WITNESS_TRANSFORMS" if original is not None else "FRESH_NATIVE_FIND_AND_SHRINK",
            "initial_witness_digest": numerical_input_digest(original) if original is not None else None,
            "initial_witness_reproduced": original is not None,
            "initial_witness_preserved": original is not None and witness == original,
            "transformation_contract": "PREFIX_LENGTH_COMMON_BINARY_SCALE_AND_COMMON_ADJACENT_STEPS_PRESERVE_CONSTANT_AXES" if original is not None else None,
            "predicate_calls": calls, "hypothesis_attempts": attempts, "domain_rejections": rejected,
            "structure_rejections": structure_rejected,
            "first_failure_seconds": first_failure, "wall_seconds": time.perf_counter()-started,
            "stop": stop, "shrinking": "NATIVE_COMPLETED" if stop == "COMPLETE" else "INCOMPLETE_OR_NO_WITNESS"}
