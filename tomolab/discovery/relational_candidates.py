"""Opt-in, data-only relational proposals for exposed development fixtures.

This is a separate candidate grammar. It neither changes the frozen ALL Mold
nor authorizes external execution, learning, release, or a semantic claim.
"""
import ast
from copy import deepcopy
import hashlib
import inspect
import re
import textwrap

from .online_schema import validate_contract, validate_input, input_identity
from .schema import digest

SCHEMA = "tomolab-relational-candidate-v1"
SIGNATURE_SCHEMA = "tomolab-relational-syntax-v1"
EVIDENCE_CLASS = "DEVELOPMENT_SYNTHETIC_CANDIDATE"
CONSULTATION_SHA256 = "4ef7769f2a7e244d51c930080910090716690fe612b7f706e9be51935f60c2cc"
MUTATORS = ("M1_LENGTH_VALUE_COUPLED", "M2_ADJACENT_DIFF_INVERSION",
            "M3_AGGREGATE_COMPENSATED", "M4_CARDINALITY_TOPOLOGY")
REQUIRED_TAGS = {
    MUTATORS[0]: frozenset({"HAS_LEN_CALL", "HAS_INDEX_SUBSCRIPT"}),
    MUTATORS[1]: frozenset({"HAS_ADJACENT_OFFSET", "HAS_ORDER_COMPARE"}),
    MUTATORS[2]: frozenset({"HAS_ACCUMULATOR", "HAS_SUM_REDUCE"}),
    MUTATORS[3]: frozenset({"HAS_EQUALITY_COMPARE", "HAS_COUNT_SET_OP"}),
}
TAGS = set().union(*REQUIRED_TAGS.values()) | {"ONLY_EMPTY_CHECK"}


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA256 identity required")


def extract_relational_signature(target, contract):
    """Inspect syntax only; tag presence does not establish branch semantics."""
    contract = validate_contract(contract)
    result = dict(schema=SIGNATURE_SCHEMA, status="UNSUPPORTED", tags=[], constants=[],
                  source_sha256=None, contract_sha256=digest(contract),
                  scope="SYNTAX_ONLY_NOT_MECHANISM_OR_FRONTIER_PROOF", unknown_reasons=[])
    if contract["kind"] != "sequence_int":
        result["unknown_reasons"] = ["UNSUPPORTED_RELATIONAL_CONTRACT"]
        return result
    if not inspect.isfunction(target):
        result["unknown_reasons"] = ["SOURCE_UNAVAILABLE"]
        return result
    try:
        source = textwrap.dedent(inspect.getsource(target))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError, IndentationError):
        result["unknown_reasons"] = ["SOURCE_UNAVAILABLE"]
        return result
    result["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1 or len(functions[0].args.args) != 1:
        result["unknown_reasons"] = ["ONE_SYNCHRONOUS_ARGUMENT_REQUIRED"]
        return result
    nodes, tags, constants = list(ast.walk(functions[0])), set(), []
    unsafe = (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Import,
              ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Lambda)
    if any(isinstance(n, unsafe) for n in nodes):
        result["unknown_reasons"].append("UNSUPPORTED_DYNAMIC_OR_EFFECTFUL_SYNTAX")
    for node in nodes:
        if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 10**12:
            if node.value not in constants:
                constants.append(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "len": tags.add("HAS_LEN_CALL")
            if name == "sum": tags.update(("HAS_SUM_REDUCE", "HAS_ACCUMULATOR"))
            if name in ("set", "Counter"): tags.add("HAS_COUNT_SET_OP")
            if name in ("exec", "eval", "getattr", "setattr", "__import__"):
                result["unknown_reasons"].append("DYNAMIC_CALL")
        if isinstance(node, ast.Subscript):
            tags.add("HAS_INDEX_SUBSCRIPT")
            if any(isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub))
                   for n in ast.walk(node.slice)):
                tags.add("HAS_ADJACENT_OFFSET")
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            tags.add("HAS_ACCUMULATOR")
        if isinstance(node, ast.Compare):
            if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                tags.add("HAS_EQUALITY_COMPARE")
            if any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops):
                tags.add("HAS_ORDER_COMPARE")
    # This narrow syntax guard deliberately does not infer an *uncovered*
    # frontier. Absence of the tag never proves absence of an empty-only path.
    tests = [n.test for n in nodes if isinstance(n, ast.If)]
    parameter = functions[0].args.args[0].arg
    def empty_test(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return isinstance(node.operand, ast.Name) and node.operand.id == parameter
        return (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
            and isinstance(node.ops[0], ast.Eq) and isinstance(node.left, ast.Call)
            and isinstance(node.left.func, ast.Name) and node.left.func.id == "len"
            and len(node.left.args) == 1 and isinstance(node.left.args[0], ast.Name)
            and node.left.args[0].id == parameter and isinstance(node.comparators[0], ast.Constant)
            and type(node.comparators[0].value) is int and node.comparators[0].value == 0)
    if tests and all(empty_test(t) for t in tests) and not any(isinstance(n, ast.Subscript) for n in nodes):
        tags.add("ONLY_EMPTY_CHECK")
    result.update(tags=sorted(tags), constants=constants[:64],
                  status="PARTIAL" if result["unknown_reasons"] else "SUPPORTED_SYNTAX_ONLY")
    result["unknown_reasons"] = sorted(set(result["unknown_reasons"]))
    return result


def _signature(signature, contract):
    fields = {"schema", "status", "tags", "constants", "source_sha256", "contract_sha256", "scope", "unknown_reasons"}
    if type(signature) is not dict or set(signature) != fields:
        raise ValueError("strict relational signature fields required")
    if signature["schema"] != SIGNATURE_SCHEMA or signature["contract_sha256"] != digest(contract):
        raise ValueError("signature contract identity mismatch")
    if signature["status"] not in ("SUPPORTED_SYNTAX_ONLY", "PARTIAL", "UNSUPPORTED"):
        raise ValueError("invalid syntax status")
    if signature["source_sha256"] is not None: _sha(signature["source_sha256"])
    if signature["status"] == "SUPPORTED_SYNTAX_ONLY" and signature["source_sha256"] is None:
        raise ValueError("supported syntax requires source identity")
    if signature["status"] == "SUPPORTED_SYNTAX_ONLY" and signature["unknown_reasons"]:
        raise ValueError("uncertain structure cannot authorize a proposal")
    if (type(signature["tags"]) is not list or len(signature["tags"]) > len(TAGS)
        or signature["tags"] != sorted(set(signature["tags"])) or set(signature["tags"]) - TAGS):
        raise ValueError("unsupported syntax tags")
    if type(signature["constants"]) is not list or len(signature["constants"]) > 64 or any(type(x) is not int or abs(x) > 10**12 for x in signature["constants"]):
        raise ValueError("bounded builtin integer constants required")
    if signature["scope"] != "SYNTAX_ONLY_NOT_MECHANISM_OR_FRONTIER_PROOF":
        raise ValueError("syntax scope cannot be widened")
    if type(signature["unknown_reasons"]) is not list or len(signature["unknown_reasons"]) > 16 or any(type(s) is not str or len(s) > 160 for s in signature["unknown_reasons"]):
        raise ValueError("bounded syntax uncertainty required")


def _frontier(frontier, base, contract, signature):
    if frontier is None:
        return None
    fields = {"schema", "authority", "input_digest", "contract_sha256", "structure_sha256", "expression", "operator", "lhs", "rhs"}
    if type(frontier) is not dict or set(frontier) != fields:
        raise ValueError("strict reviewed frontier fields required")
    if (frontier["schema"] != "tomolab-authored-frontier-v1" or frontier["authority"] != "AUTHORED_FIXTURE_REVIEW"
        or frontier["input_digest"] != input_identity(base) or frontier["contract_sha256"] != digest(contract)
        or frontier["structure_sha256"] != digest(signature)):
        raise ValueError("frontier identity or authored authority mismatch")
    if frontier["operator"] not in ("==", "!=", "<", "<=", ">", ">=") or frontier["expression"] not in ("sum_input", "first_value", "adjacent_difference", "cluster_difference"):
        raise ValueError("unsupported reviewed expression")
    if any(type(frontier[k]) is not int or abs(frontier[k]) > 10**12 for k in ("lhs", "rhs")):
        raise ValueError("bounded builtin integer frontier operands required")
    actual = {"sum_input": lambda: sum(base), "first_value": lambda: base[0] if base else None,
              "adjacent_difference": lambda: base[-1]-base[-2] if len(base)>1 else None,
              "cluster_difference": lambda: base[-1]-base[0] if base else None}[frontier["expression"]]()
    if actual != frontier["lhs"]:
        raise ValueError("reviewed public expression differs from anchor")
    return deepcopy(frontier)


def propose_relational_candidates(base, contract, signature, *, mutator_id=None,
                                  frontier=None, seen=(), history=None):
    """Return at most three valid, novel proposals or an explicit abstention.

    These authored operators are COMMON_PRIOR candidates, not learned rules.
    No Target/Oracle executes here. Rejection never becomes negative evidence.
    """
    contract = validate_contract(contract)
    result = dict(schema=SCHEMA, evidence_class=EVIDENCE_CLASS, status="ABSTAIN", candidates=[],
        reasons=[], contract_sha256=digest(contract), signature_sha256=digest(signature),
        frontier_used=False, external_execution_authorized=False, learned=False,
        source=dict(classification="EXPOSED_CONSULTATION_PROPOSAL", sha256=CONSULTATION_SHA256, pages=[23,24,25,26,27]))
    if contract["kind"] != "sequence_int":
        result["reasons"] = ["UNSUPPORTED_RELATIONAL_CONTRACT"]
        return result
    if not validate_input(base, contract):
        result["reasons"] = ["INVALID_BASE_INPUT_NO_COERCION"]
        return result
    _signature(signature, contract)
    if signature["status"] != "SUPPORTED_SYNTAX_ONLY":
        result["reasons"] = ["STRUCTURE_UNKNOWN"]
        return result
    if "ONLY_EMPTY_CHECK" in signature["tags"]:
        result["reasons"] = ["NEGATIVE_GUARD_ONLY_EMPTY_CHECK"]
        return result
    if mutator_id is not None and mutator_id not in MUTATORS:
        raise ValueError("unsupported relational mutator")
    known = set(seen)
    if len(known) > 10000: raise ValueError("bounded seen identities required")
    for item in known: _sha(item)
    if history is None: history = dict(gains=0, losses=0)
    if type(history) is not dict or set(history) != {"gains", "losses"} or any(type(v) is not int or not 0 <= v <= 4096 for v in history.values()):
        raise ValueError("bounded reviewed history counts required")
    if history["losses"] and history["gains"] <= history["losses"]:
        result["reasons"] = ["NEGATIVE_GUARD_NONPOSITIVE_NET"]
        return result
    frontier = _frontier(frontier, base, contract, signature)
    tags, rejected = set(signature["tags"]), set()
    selected = (mutator_id,) if mutator_id else MUTATORS
    for operator in selected:
        # The PDF table uses OR; explicit selection never bypasses guards.
        if not REQUIRED_TAGS[operator].intersection(tags):
            rejected.add("REQUIRED_SYNTAX_TAGS_ABSENT")
            continue
        minimum = 5 if operator in (MUTATORS[1], MUTATORS[3]) else 4
        n = max(len(base), minimum, contract.get("min_size", 0))
        if n > contract.get("max_size", 8):
            rejected.add("MINIMUM_LENGTH_OUTSIDE_CONTRACT")
            continue
        fill = 1 if contract.get("low", -16) <= 1 <= contract.get("high", 16) else contract.get("low", -16)
        xs = list(base) + [base[-1] if base else fill] * (n-len(base))
        proposals = []
        if operator == MUTATORS[0]:
            first = xs[:]; first[0], first[1], first[-1] = n, -n, n-1
            proposals = [(first, "LENGTH_VALUE_BOUNDARY", None)]
            if frontier and frontier["expression"] == "first_value" and frontier["rhs"] != frontier["lhs"]:
                deficit=frontier["rhs"]-frontier["lhs"]
                shifted=xs[:]; shifted[0],shifted[-1]=n+deficit,n-1+deficit
                proposals.append((shifted,"LENGTH_VALUE_DEFICIT_SHIFT",None))
            proposals.append((list(range(1,n+1)), "LENGTH_ORDINAL_BOUNDARY", None))
        elif operator == MUTATORS[1]:
            gap = max(1, abs(frontier["rhs"])) if frontier and frontier["expression"] == "adjacent_difference" else 1
            up = [xs[0]+i*gap for i in range(n)]
            terminal = up[:]; terminal[-1] = terminal[-2]-gap
            plateau = up[:]; plateau[n//2] = plateau[n//2-1]
            proposals = [(terminal,"TERMINAL_INVERSION",None),(plateau,"MIDPOINT_PLATEAU",None),
                         ([xs[0]+(gap if i%2==0 else -gap) for i in range(n)],"ALTERNATING_DIFFERENCE",None)]
        elif operator == MUTATORS[2]:
            k = frontier["rhs"] if frontier and frontier["expression"] == "sum_input" else (signature["constants"][0] if signature["constants"] else 0)
            exact = xs[:]; exact[-1] += k-sum(exact)
            # A zero-sum dipole preserves the aggregate. Invalid bounds are
            # rejected, never clamped into a false relationship.
            if max(map(abs,exact),default=0) < 2: exact[0] += 2; exact[1] -= 2
            adjacent = exact[:]; adjacent[-1] += 1
            zero = xs[:]; zero[-1] -= sum(zero)
            proposals = [(exact,"EXACT_AGGREGATE",k),(adjacent,"ADJACENT_AGGREGATE",k+1),(zero,"EXACT_AGGREGATE",0)]
        else:
            major = xs[0]
            gap = frontier["rhs"] if frontier and frontier["expression"] == "cluster_difference" else 1
            if gap == 0: gap = 1
            outlier = major+gap
            terminal = [major]*(n-1)+[outlier]
            pivot = [major]*n; pivot[n//2] = outlier
            proposals = [(terminal,"SINGLE_TERMINAL_OUTLIER",None),(pivot,"SINGLE_PIVOT_OUTLIER",None),
                         ([major]*(n//2)+[outlier]*(n-n//2),"BIMODAL_CARDINALITY",None)]
        for point, relationship, target in proposals:
            token = input_identity(point)
            if not validate_input(point, contract):
                rejected.add("CANDIDATE_CONTRACT_REJECTED_NO_CLAMP")
            elif token == input_identity(base) or token in known:
                rejected.add("DUPLICATE_OR_UNCHANGED_CANDIDATE")
            else:
                row = dict(mutator_id=operator,input=point,input_digest=token,relationship=relationship,
                           aggregate_target=target,learned=False)
                result["candidates"].append(row); known.add(token)
                if len(result["candidates"]) == 3: break
        if result["candidates"]: break
    expressions = {MUTATORS[0]: "first_value", MUTATORS[1]: "adjacent_difference",
                   MUTATORS[2]: "sum_input", MUTATORS[3]: "cluster_difference"}
    chosen = result["candidates"][0]["mutator_id"] if result["candidates"] else None
    result["frontier_used"] = bool(frontier and chosen and expressions[chosen] == frontier["expression"])
    if chosen == MUTATORS[0]:
        result["frontier_used"] = any(c["relationship"]=="LENGTH_VALUE_DEFICIT_SHIFT" for c in result["candidates"])
    result["status"] = "PROPOSED" if result["candidates"] else "ABSTAIN"
    result["reasons"] = sorted(rejected) or ([] if result["candidates"] else ["NO_VALID_NOVEL_CANDIDATE"])
    return result


def bounded_carryover_schedule(common_inputs, interventions, *, budget, prefix_steps):
    """Diagnostic of a finite insertion schedule, never a Hypothesis engine.

    Pending common inputs at the cap are explicit. This provides a constructive
    counterexample to interpreting prefix preservation as full-budget no-loss.
    """
    if type(budget) is not int or not 0 <= budget <= 10000 or type(prefix_steps) is not int or not 0 <= prefix_steps <= budget:
        raise ValueError("bounded schedule contract required")
    if type(common_inputs) is not list or len(common_inputs) > 10000 or type(interventions) is not dict:
        raise ValueError("bounded authored input schedule required")
    if any(type(i) is not int or not prefix_steps <= i < budget for i in interventions):
        raise ValueError("interventions must remain outside the protected prefix")
    common, rows = deepcopy(common_inputs), []
    cursor = 0
    for step in range(budget):
        if step in interventions:
            rows.append(dict(step=step,origin="RELATIONAL_INSERTION",input=deepcopy(interventions[step])))
        elif cursor < len(common):
            rows.append(dict(step=step,origin="COMMON",input=common[cursor])); cursor += 1
        else: break
    return dict(rows=rows,common_executed=cursor,pending_common=common[cursor:],
                total_calls=len(rows),prefix_steps=prefix_steps,full_budget_no_regression_guaranteed=False,
                engine="AUTHORED_FINITE_SCHEDULE_DIAGNOSTIC_NOT_HYPOTHESIS")
