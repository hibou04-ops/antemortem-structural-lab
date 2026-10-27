"""Public-data-only, bounded Hypothesis-first guidance and reusable SMT state."""
from copy import deepcopy
import time

from .hypothesis_adapter import generate_pool, guided_candidates
from .predicates import predicate_holds, validate_predicate
from .schema import canonical, digest, integer, validate_inputs, validate_spec


def temporal_trace_strategy(spec, contract):
    """Native composite trace Strategy preserving declared EFSM preconditions."""
    from hypothesis import assume, strategies as st
    from .hypothesis_adapter import type_strategy
    from .temporal import available_actions, apply_action, initial_state, validate_temporal_contract
    spec = validate_spec(spec)
    contract = validate_temporal_contract(contract, spec)
    item = spec["inputs"][0]
    trace_type = item["type"]
    argument_strategy = type_strategy(trace_type["items"]["items"][1])

    @st.composite
    def trace(draw):
        state, previous, rows = initial_state(contract), None, []
        length = draw(st.integers(trace_type["min_size"], trace_type["max_size"]))
        for index in range(length):
            argument = draw(argument_strategy)
            actions = available_actions(state, argument, index, previous, contract, spec)
            if not actions:
                break
            action = draw(st.sampled_from(actions))
            previous = apply_action(state, action, argument, index, previous, contract, spec)
            state = previous["post"]
            rows.append([action, argument])
        assume(len(rows) >= trace_type["min_size"])
        return {item["name"]: rows}
    return trace()


def generate_temporal_pool(spec, contract, *, seed=7, size=32, relations=(), excluded=()):
    """Public model generation only; no implementation or Oracle callback."""
    from hypothesis import HealthCheck, Phase, given, seed as hypothesis_seed, settings
    from hypothesis.errors import Unsatisfiable
    from .temporal import simulate_trace, temporal_holds
    integer(seed, 0, 2**32-1)
    integer(size, 1, 4096)
    if not isinstance(relations, (list, tuple)) or len(relations) > 128:
        raise ValueError("bounded public temporal relations required")
    canonical(relations)
    points, seen = [], {canonical(validate_inputs(point, spec)) for point in excluded}

    def informative(point):
        if canonical(point) in seen:
            return False
        replay = simulate_trace(point, spec, contract)
        votes = [temporal_holds(relation, replay) for relation in relations]
        return not votes or (any(votes) and not all(votes))

    @hypothesis_seed(seed)
    @settings(max_examples=size, deadline=None, database=None, phases=[Phase.generate],
              suppress_health_check=list(HealthCheck))
    @given(temporal_trace_strategy(spec, contract).filter(informative))
    def collect(point):
        encoded = canonical(point)
        if encoded not in seen:
            seen.add(encoded)
            points.append(point)
    try:
        collect()
    except Unsatisfiable:
        pass
    return points


class EvidenceCache:
    """Run-local cache; specification, engine version and actual input identify it."""
    def __init__(self, spec, engine_version=0):
        self.spec = validate_spec(spec)
        self.spec_digest = digest(self.spec)
        self.version = integer(engine_version, 0, 2**31-1)
        self.entries = {}
        self.hits = 0

    def set_version(self, version):
        version = integer(version, 0, 2**31-1)
        if version != self.version:
            self.entries.clear()
            self.version = version

    def key(self, inputs):
        return (self.spec_digest, self.version, canonical(validate_inputs(inputs, self.spec)))

    def get(self, inputs):
        key = self.key(inputs)
        if key not in self.entries:
            return None
        self.hits += 1
        return deepcopy(self.entries[key])

    def put(self, inputs, value):
        canonical(value)
        self.entries[self.key(inputs)] = deepcopy(value)


class HypothesisFirstPolicy:
    """Fresh native draws by default; bounded disagreement only with evidence."""
    def __init__(self, spec, *, seed=7, batch_size=8):
        self.spec = validate_spec(spec)
        self.seed = integer(seed, 0, 2**32-1)
        self.batch_size = integer(batch_size, 1, 64)
        self.seen, self.exhausted = set(), set()
        self.round = 0
        self.metrics = {"native_rounds": 0, "guided_rounds": 0, "duplicates": 0,
                        "constraint_rejections": 0, "wall_seconds": 0.0, "cpu_seconds": 0.0}

    def candidates(self, *, size=None, guidance=None, version=0):
        count = self.batch_size if size is None else integer(size, 1, 64)
        integer(version, 0, 2**31-1)
        before, cpu = time.perf_counter(), time.process_time()
        seed = (self.seed + self.round) % 2**32
        self.round += 1
        result, source, reason = [], "NATIVE_HYPOTHESIS", "NO_QUALIFIED_STRUCTURAL_EVIDENCE"
        qualified = (isinstance(guidance, dict) and guidance.get("qualified") is True
                     and guidance.get("applicability") == "APPLICABLE_FOR_PROBING"
                     and isinstance(guidance.get("evidence_ids"), list) and bool(guidance["evidence_ids"])
                     and isinstance(guidance.get("predicates"), list) and 2 <= len(guidance["predicates"]) <= 16)
        if qualified:
            predicates = [validate_predicate(p, self.spec) for p in guidance["predicates"]]
            signature = digest({"spec": self.spec, "version": version, "predicates": predicates})
            if signature not in self.exhausted:
                # One bounded attempt per changed hypothesis set; do not repeatedly
                # pay inference costs for guidance that supplies no new input.
                response = guided_candidates(self.spec, predicates=predicates, seed=seed, size=count,
                                             max_examples=32, relation_mode="disagreement")
                self.metrics["guided_rounds"] += 1
                self.metrics["constraint_rejections"] += response["constraint_rejections"]
                result = [point for point in response["candidates"] if canonical(point) not in self.seen]
                if result:
                    source, reason = "QUALIFIED_DISAGREEMENT", "NOVEL_COMPETING_PREDICTIONS"
                else:
                    self.exhausted.add(signature)
                    reason = "GUIDANCE_WITHOUT_NOVEL_INFORMATION"
        if not result:
            self.metrics["native_rounds"] += 1
            points = generate_pool(self.spec, seed=seed, size=min(4096, count * 4))
            for point in points:
                if canonical(point) in self.seen:
                    self.metrics["duplicates"] += 1
                elif len(result) < count:
                    result.append(point)
        for point in result:
            self.seen.add(canonical(point))
        self.metrics["wall_seconds"] += time.perf_counter() - before
        self.metrics["cpu_seconds"] += time.process_time() - cpu
        return {"candidates": deepcopy(result), "source": source, "reason": reason,
                "version": version, "oracle_calls": 0, "metrics": deepcopy(self.metrics)}


class IncrementalIntSolver:
    """One Z3 bounded-integer context, scoped push/pop queries and versioned cache.

    Reuses E5's strict predicate validation and concrete witness interpreter.
    Unsupported types/operators abstain; they are never silently approximated.
    """
    def __init__(self, spec, *, timeout_ms=100):
        self.spec = validate_spec(spec)
        self.timeout = integer(timeout_ms, 1, 10000)
        self.version = None
        self.cache, self.compiled = {}, {}
        self.metrics = {"solver_calls": 0, "cache_hits": 0, "pushes": 0, "pops": 0,
                        "wall_seconds": 0.0, "cpu_seconds": 0.0}
        self.solver = self.z3 = None
        self.variables = {}

    def _prepare(self):
        if any(item["type"]["kind"] != "int" for item in self.spec["inputs"]):
            raise ValueError("incremental SMT supports bounded integer inputs only")
        if self.solver is None:
            import z3
            self.z3 = z3
            self.solver = z3.Solver()
            self.solver.set(timeout=self.timeout)
            for item in self.spec["inputs"]:
                variable = z3.Int(item["name"])
                self.variables[item["role"]] = variable
                self.solver.add(variable >= item["type"]["min"], variable <= item["type"]["max"])

    def _term(self, node):
        if type(node) is int:
            return self.z3.IntVal(node)
        if type(node) is bool:
            return self.z3.BoolVal(node)
        if not isinstance(node, dict):
            raise ValueError("unsupported integer expression")
        if "var" in node:
            return self.variables[node["var"]]
        op = node["op"]
        if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
            left, right = self._term(node["left"]), self._term(node["right"])
            return {"eq": lambda: left == right, "ne": lambda: left != right,
                    "lt": lambda: left < right, "le": lambda: left <= right,
                    "gt": lambda: left > right, "ge": lambda: left >= right}[op]()
        args = node.get("args", [])
        values = [self._term(arg) for arg in args]
        if op == "and": return self.z3.And(*values)
        if op == "or": return self.z3.Or(*values)
        if op == "not": return self.z3.Not(values[0])
        if op == "add": return values[0] + values[1]
        if op == "sub": return values[0] - values[1]
        if op == "neg": return -values[0]
        if op == "abs": return self.z3.If(values[0] >= 0, values[0], -values[0])
        if op == "mul" and any(type(arg) is int for arg in args): return values[0] * values[1]
        if op == "mod" and type(args[1]) is int and args[1] > 0: return values[0] % values[1]
        raise ValueError("unsupported integer expression")

    def solve(self, predicates, *, mode="all", excluded=(), version=0):
        integer(version, 0, 2**31-1)
        if mode not in {"all", "any", "disagreement"}:
            raise ValueError("invalid solver mode")
        if not isinstance(predicates, (list, tuple)) or len(predicates) > 64:
            raise ValueError("bounded predicate list required")
        clean = [validate_predicate(p, self.spec) for p in predicates]
        if mode == "disagreement" and len(clean) < 2:
            raise ValueError("competing predicates required")
        if not isinstance(excluded, (list, tuple)) or len(excluded) > 4096:
            raise ValueError("bounded exclusions required")
        points = [validate_inputs(point, self.spec) for point in excluded]
        if version != self.version:
            self.cache.clear()
            self.version = version
        key = digest({"spec": self.spec, "version": version, "predicates": clean,
                      "mode": mode, "excluded": points})
        if key in self.cache:
            self.metrics["cache_hits"] += 1
            return deepcopy(self.cache[key])
        before, cpu = time.perf_counter(), time.process_time()
        result = {"status": "UNKNOWN", "witness": None, "backend": "Z3_INCREMENTAL"}
        pushed = False
        try:
            self._prepare()
            terms = []
            for predicate in clean:
                encoded = canonical(predicate)
                if encoded not in self.compiled:
                    self.compiled[encoded] = self._term(predicate)
                terms.append(self.compiled[encoded])
            self.solver.push()
            pushed = True
            self.metrics["pushes"] += 1
            self.solver.add(self.z3.And(*terms) if mode == "all" else self.z3.Or(*terms))
            if mode == "disagreement":
                self.solver.add(self.z3.Not(self.z3.And(*terms)))
            for point in points:
                self.solver.add(self.z3.Not(self.z3.And(*(self.variables[item["role"]] == point[item["name"]]
                                                         for item in self.spec["inputs"]))))
            self.metrics["solver_calls"] += 1
            status = self.solver.check()
            if status == self.z3.unsat:
                result["status"] = "UNSAT"
            elif status == self.z3.sat:
                model = self.solver.model()
                point = {item["name"]: model.eval(self.variables[item["role"]], model_completion=True).as_long()
                         for item in self.spec["inputs"]}
                point = validate_inputs(point, self.spec)
                votes = [predicate_holds(p, point, self.spec) for p in clean]
                valid = all(votes) if mode == "all" else any(votes)
                if mode == "disagreement": valid = any(votes) and not all(votes)
                if not valid or point in points:
                    raise ValueError("symbolic witness failed concrete validation")
                result.update(status="SAT", witness=point, concrete_readback="MATCHED")
        except (ImportError, ValueError) as error:
            result["reason"] = str(error)
        finally:
            if pushed:
                self.solver.pop()
                self.metrics["pops"] += 1
            self.metrics["wall_seconds"] += time.perf_counter() - before
            self.metrics["cpu_seconds"] += time.process_time() - cpu
        self.cache[key] = deepcopy(result)
        return result
