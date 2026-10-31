"""Opt-in E8-R1 claim meaning over the existing bounded relation grammar.

Truth is three-valued. A censored family and an undefined input feature never
become negative evidence. These functions make no Oracle calls and prove no
global necessity, sufficiency, causality, or cross-implementation recurrence.
"""
from copy import deepcopy
from itertools import combinations
import math

from .features import grammar, measurements, relation_id, transferable, validate_relation
from .predicates import validate_predicate
from .schema import canonical, decode_value, digest, integer, keys, normalize_evidence, validate_inputs

SEMANTIC_VERSION = "e8-r1-claims-v1"
EXACT = "EXACT_FAILURE_PREDICATE"
SUFFICIENT = "SUFFICIENT_FAILURE_CONDITION"
NECESSARY = "NECESSARY_FAILURE_CONDITION"
EMPIRICAL = "EMPIRICAL_SEARCH_GUIDANCE"
CLAIM_KINDS = (EXACT, SUFFICIENT, NECESSARY, EMPIRICAL)
DEFAULT_POLICY = dict(semantic_version=SEMANTIC_VERSION, max_atomic_relations=512,
    max_compound_relations=128, max_relations=640, max_depth=3, max_terms=3,
    max_claims=4096, max_events=512, extra_features=[])
OBSERVATION_STATUSES = {"VALID", "INVALID_ORACLE", "DOMAIN_REJECTED", "EXECUTION_ERROR", "NONDETERMINISTIC", "UNOBSERVED"}


def normalize_policy(policy=None):
    if policy is None:
        return deepcopy(DEFAULT_POLICY)
    keys(policy, (), DEFAULT_POLICY)
    result = deepcopy(DEFAULT_POLICY)
    result.update(deepcopy(policy))
    if result["semantic_version"] != SEMANTIC_VERSION:
        raise ValueError("unsupported explicit claim semantic version")
    for name in DEFAULT_POLICY:
        if name not in ("semantic_version", "extra_features"):
            integer(result[name], 0 if name == "max_compound_relations" else 1, DEFAULT_POLICY[name])
    if result["max_terms"] > 3 or result["max_depth"] > 3:
        raise ValueError("Boolean composition exceeds the fixed R1 complexity budget")
    if result["extra_features"] != []:
        raise ValueError("no additional input features have been approved for this semantic policy")
    return result


def normalize_claim_kinds(kinds=None):
    if kinds is None:
        return list(CLAIM_KINDS)
    if not isinstance(kinds, (list, tuple)) or not kinds or len(kinds) > len(CLAIM_KINDS):
        raise ValueError("bounded nonempty explicit claim kinds required")
    if len(set(kinds)) != len(kinds) or any(kind not in CLAIM_KINDS for kind in kinds):
        raise ValueError("unknown or duplicate claim kind")
    return [kind for kind in CLAIM_KINDS if kind in kinds]


def classify(predicted, observed, claim_kind):
    if claim_kind not in CLAIM_KINDS:
        raise ValueError("unknown claim kind")
    if predicted is not None and type(predicted) is not bool or observed is not None and type(observed) is not bool:
        raise ValueError("claim classification requires Boolean or UNKNOWN values")
    cell = ("UNKNOWN" if predicted is None or observed is None else
            "TP" if predicted and observed else "FP" if predicted else "FN" if observed else "TN")
    refutes = cell in ({"FP", "FN"} if claim_kind == EXACT else {"FP"} if claim_kind == SUFFICIENT else {"FN"} if claim_kind == NECESSARY else set())
    supports = cell != "UNKNOWN" and not refutes and (cell == "TP" if claim_kind == EMPIRICAL else True)
    return {"cell":cell, "refutes":refutes, "supports":supports}


def normalize_semantic_evidence(evidence, spec):
    required = ("kind", "evidence_id", "inputs", "invariant", "category", "signature")
    keys(evidence, required, ("family_observations", "observation_status"))
    result = normalize_evidence({k:evidence[k] for k in required}, spec)
    status = evidence.get("observation_status", "VALID")
    if status not in OBSERVATION_STATUSES:
        raise ValueError("unknown observation validity status")
    if "observation_status" in evidence:
        result["observation_status"] = status
    if "family_observations" in evidence:
        labels = evidence["family_observations"]
        if not isinstance(labels, dict) or len(labels) > 64:
            raise ValueError("bounded explicit family observability map required")
        for family, value in labels.items():
            if (not isinstance(family, str) or len(family) > 500 or len(family.split("/", 2)) != 3
                    or family.split("/", 1)[0] not in spec["contract"]["invariants"]
                    or value is not None and type(value) is not bool):
                raise ValueError("invalid explicit family observation")
        actual = result["invariant"]+"/"+result["category"]+"/"+result["signature"]
        if status == "VALID" and result["kind"] == "FAILURE" and actual in labels and labels[actual] is not True:
            raise ValueError("observed failure contradicts its family observability map")
        if status == "VALID" and result["kind"] == "REFUTATION" and any(value is True and family.split("/",1)[0]==result["invariant"] for family,value in labels.items()):
            raise ValueError("checked normal invariant contradicts its family observability map")
        if status != "VALID" and any(value is not None for value in labels.values()):
            raise ValueError("invalid execution cannot supply true or false family labels")
        result["family_observations"] = deepcopy(labels)
    return result


def semantic_label(event, family):
    if event.get("observation_status", "VALID") != "VALID":
        return None
    if family in event.get("family_observations", {}):
        value = event["family_observations"][family]
        if value is not None and type(value) is not bool:
            raise ValueError("family label must be Boolean or UNKNOWN")
        return value
    if event["invariant"] != family.split("/", 1)[0]:
        return None
    if event["kind"] == "REFUTATION":
        return False
    actual = event["invariant"]+"/"+event["category"]+"/"+event["signature"]
    return True if actual == family else None


def kleene(op, values):
    if any(value is not None and type(value) is not bool for value in values):
        raise ValueError("Boolean composition requires Boolean or UNKNOWN operands")
    if op == "not":
        if len(values) != 1:
            raise ValueError("NOT requires one operand")
        return None if values[0] is None else not values[0]
    if op not in ("and", "or") or not 2 <= len(values) <= 3:
        raise ValueError("bounded AND/OR required")
    if op == "and":
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def _predicate_value3(node, by_role):
    """The existing typed AST vocabulary, with undefined leaves retained."""
    if not isinstance(node, dict):
        return node
    if "var" in node:
        return by_role[node["var"]]
    op = node["op"]
    if op in ("and", "or", "not"):
        return kleene(op, [_predicate_value3(arg, by_role) for arg in node["args"]])
    try:
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            a, b = _predicate_value3(node["left"], by_role), _predicate_value3(node["right"], by_role)
            if a is None or b is None:
                return None
            return {"eq":lambda:a==b,"ne":lambda:a!=b,"lt":lambda:a<b,"le":lambda:a<=b,"gt":lambda:a>b,"ge":lambda:a>=b}[op]()
        args = [_predicate_value3(arg, by_role) for arg in node["args"]]
        if any(arg is None for arg in args):
            return None
        if op in ("len", "abs", "sum", "min", "max"):
            value = {"len":len,"abs":abs,"sum":sum,"min":min,"max":max}[op](args[0])
        elif op == "neg":
            value = -args[0]
        else:
            a,b = args
            value = {"add":lambda:a+b,"sub":lambda:a-b,"mul":lambda:a*b,"mod":lambda:a%b}[op]()
        return None if type(value) is float and not math.isfinite(value) else value
    except (ArithmeticError, ValueError, TypeError, KeyError, OverflowError):
        return None


def measurements3(inputs, spec, predicates=()):
    inputs = validate_inputs(inputs, spec)
    measured = measurements(inputs, spec)
    by_role = {item["role"]:decode_value(inputs[item["name"]], item["type"]) for item in spec["inputs"]}
    from .predicates import predicate_roles
    for predicate in predicates:
        clean = validate_predicate(predicate, spec)
        term = {"kind":"ast", "roles":sorted(predicate_roles(clean)), "expression":clean}
        value = _predicate_value3(clean, by_role)
        measured[canonical(term)] = int(value) if type(value) is bool else None
    return measured


def validate_semantic_relation(relation, spec, policy=None):
    policy = normalize_policy(policy)
    roles = {item["role"] for item in spec["inputs"]}
    def visit(value, depth=0):
        if depth > policy["max_depth"]:
            raise ValueError("relation expression depth exceeded")
        keys(value, ("term", "operator", "value"))
        term = value["term"]
        if not isinstance(term, dict):
            raise ValueError("typed relation term required")
        if term.get("kind") != "compound":
            validate_relation(value)
            if not set(term["roles"]) <= roles:
                raise ValueError("relation references undeclared roles")
            if term["kind"] == "ast":
                validate_predicate(term["expression"], spec)
            return 1, set(term["roles"])
        keys(term, ("kind", "roles", "expression"))
        if value["operator"] != "eq" or value["value"] != 1:
            raise ValueError("compound relation requires Boolean membership")
        expression = term["expression"]
        keys(expression, ("op", "args"))
        op,args = expression["op"],expression["args"]
        if not isinstance(args,list) or (len(args) != 1 if op == "not" else op not in ("and","or") or not 2 <= len(args) <= policy["max_terms"]):
            raise ValueError("invalid bounded Boolean relation")
        children = [visit(arg,depth+1) for arg in args]
        leaves = sum(count for count,_ in children)
        bound_roles = set().union(*(value for _,value in children))
        if leaves > policy["max_terms"] or term["roles"] != sorted(bound_roles):
            raise ValueError("relation term count or declared roles differ")
        return leaves,bound_roles
    visit(relation)
    if len(canonical(relation)) > 32000:
        raise ValueError("bounded relation bytes exceeded")
    return deepcopy(relation)


def _relation_value(relation, measured):
    term = relation["term"]
    if term["kind"] == "compound":
        expression = term["expression"]
        return kleene(expression["op"], [_relation_value(arg,measured) for arg in expression["args"]])
    value = measured.get(canonical(term))
    try:
        defined=type(value) in (int,float) and math.isfinite(value)
    except (ValueError,OverflowError,TypeError):
        defined=False
    if not defined:
        return None
    op,threshold = relation["operator"],relation["value"]
    return value == threshold if op == "eq" else value <= threshold if op == "le" else value >= threshold


def relation_prediction(relation, inputs, spec, policy=None, measured=None):
    relation = validate_semantic_relation(relation,spec,policy)
    if measured is None:
        predicates=[]
        def collect(value):
            term=value["term"]
            if term["kind"] == "compound":
                for arg in term["expression"]["args"]:collect(arg)
            elif term["kind"] == "ast" and term["expression"] not in predicates:
                predicates.append(term["expression"])
        collect(relation)
        measured=measurements3(inputs,spec,predicates)
    return _relation_value(relation,measured)


def semantic_relation_id(relation):
    return relation_id(relation) if relation["term"]["kind"] != "compound" else "R1-"+digest(relation)[:20]


def semantic_claim_id(relation, claim_kind, family, scope):
    if claim_kind not in CLAIM_KINDS:
        raise ValueError("unknown claim kind")
    return "KR1-"+digest({"expression":relation,"claim_kind":claim_kind,
        "semantic_version":SEMANTIC_VERSION,"failure_family":family,"scope":scope})[:28]


def semantic_coordinate_only(relation):
    term = relation["term"]
    if term["kind"] == "compound":
        return any(semantic_coordinate_only(arg) for arg in term["expression"]["args"])
    if not transferable(relation):
        return True
    if term["kind"] == "ast":
        def arbitrary(value):
            if type(value) in (int,float):return value not in (0,1)
            if isinstance(value,str):return True
            if isinstance(value,dict):return False if "var" in value else any(arbitrary(v) for k,v in value.items() if k!="op")
            return isinstance(value,list) and any(arbitrary(v) for v in value)
        return arbitrary(term["expression"])
    return False


def semantic_grammar(pool, spec, predicates=(), policy=None, seed_relations=None):
    """Bounded, label-independent composition. All syntax keeps provenance."""
    policy=normalize_policy(policy)
    predicates=list(deepcopy(predicates))
    if seed_relations is None:
        _,relations,_=grammar(pool,spec,predicates)
    else:
        if not isinstance(seed_relations,list) or not 1<=len(seed_relations)<=policy["max_atomic_relations"]:
            raise ValueError("bounded nonempty frozen atomic relation list required")
        relations={}
        for relation in seed_relations:
            if not isinstance(relation,dict) or not isinstance(relation.get("term"),dict) or relation["term"].get("kind")=="compound":
                raise ValueError("frozen seeds must use the existing atomic relation grammar")
            value=validate_semantic_relation(relation,spec,policy)
            rid=relation_id(value)
            if rid in relations:
                raise ValueError("duplicate frozen atomic relation")
            relations[rid]=value
            term=value["term"]
            if term["kind"]=="ast" and term["expression"] not in predicates:
                predicates.append(term["expression"])
    if len(relations)>policy["max_atomic_relations"]:
        raise ValueError("R1 atomic relation cap exceeded; narrow the declared scope")
    measured=[measurements3(point,spec,predicates) for point in pool]
    atoms=[relations[rid] for rid in sorted(relations,key=lambda r:(semantic_coordinate_only(relations[r]),r))]
    structural=[value for value in atoms if not semantic_coordinate_only(value)]
    limit=min(policy["max_compound_relations"],policy["max_relations"]-len(relations))
    if limit<0:raise ValueError("R1 total expression cap exceeded")
    quota={"not":limit//3,"and":limit//3,"or":limit-2*(limit//3)}
    for op in ("not","and","or"):
        if op != "not" and policy["max_terms"] < 2:
            continue
        groups=([atom] for atom in structural) if op=="not" else combinations(structural,2)
        for number,args in enumerate(groups):
            if number>=quota[op]:break
            args=list(args)
            roles=sorted(set().union(*(set(v["term"]["roles"]) for v in args)))
            relation={"term":{"kind":"compound","roles":roles,"expression":{"op":op,"args":deepcopy(args)}},"operator":"eq","value":1}
            validate_semantic_relation(relation,spec,policy)
            relations[semantic_relation_id(relation)]=relation
    masks,unknown={},{}
    for rid,relation in relations.items():
        values=[_relation_value(relation,row) for row in measured]
        masks[rid]=sum(1<<i for i,v in enumerate(values) if v is True)
        unknown[rid]=sum(1<<i for i,v in enumerate(values) if v is None)
    return measured,relations,masks,unknown
