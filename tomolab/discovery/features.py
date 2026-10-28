"""Typed feature relations, never source strings or executable expressions."""
from itertools import combinations
import math

from .schema import canonical, decode_value, digest, keys


def _numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def measurements(inputs, spec, predicates=()):
    by_role = {item["role"]: decode_value(inputs[item["name"]],item["type"]) for item in spec["inputs"]}
    result = {}
    def put(kind, roles, value):
        if type(value) is bool:
            value = int(value)
        if _numeric(value):
            result[canonical({"kind": kind, "roles": roles})] = value
    for item in spec["inputs"]:
        role = item["role"]
        value = by_role[role]
        kind = item["type"]["kind"]
        if kind in ("int", "float"):
            put("value", [role], value)
            put("absolute", [role], abs(value))
            put("integral", [role], float(value).is_integer())
            put("sign", [role], -1 if value < 0 else 1 if value > 0 else 0)
            put("lower_boundary", [role], value == item["type"]["min"])
            put("upper_boundary", [role], value == item["type"]["max"])
        else:
            put("length", [role], len(value))
            put("empty", [role], not value)
        if kind == "str":
            for feature, flag in [("whitespace", any(c.isspace() for c in value)),
                                  ("strip_changes", value != value.strip()), ("nonascii", not value.isascii()),
                                  ("decimal", value.isdecimal()), ("case_changes", value != value.lower()),
                                  ("separator", any(c in '/\\:;,.|' for c in value)),
                                  ("brackets", any(c in '[]{}()' for c in value)),
                                  ("leading_sign", value.startswith(('+', '-')))]:
                put(feature, [role], flag)
        if kind in ("list", "tuple", "dict"):
            items = list(value.values()) if kind == "dict" else value
            put("duplicates", [role], len({canonical(v) for v in items}) < len(items))
            put("contains_empty", [role], any(isinstance(v, (str,list,dict,tuple)) and not v for v in items))
            put("contains_zero", [role], any(_numeric(v) and v == 0 for v in items))
            put("contains_negative", [role], any(_numeric(v) and v < 0 for v in items))
            if items and all(_numeric(v) for v in items):
                put("minimum", [role], min(items))
                put("maximum", [role], max(items))
                put("total", [role], sum(items))
                put("range", [role], max(items)-min(items))
                put("ordered", [role], all(a <= b for a,b in zip(items, items[1:])))
            if items and all(isinstance(v, str) for v in items):
                put("ordered", [role], all(a <= b for a,b in zip(items, items[1:])))
            # Limited transition traces: repeated adjacent declared actions.
            if kind == "list" and items and all(isinstance(v, (list,tuple)) and v for v in items):
                actions = [v[0] for v in items]
                put("repeated_action", [role], any(a == b for a,b in zip(actions, actions[1:])))
            if kind == "dict":
                for key in item["type"]["keys"]:
                    put("key:"+key, [role], key in value)
    for a,b in combinations(sorted(by_role), 2):
        left,right = by_role[a],by_role[b]
        put("equal", [a,b], left == right)
        if _numeric(left) and _numeric(right):
            put("difference", [a,b], left-right)
            put("sum", [a,b], left+right)
            put("absolute_difference", [a,b], abs(left-right))
        if isinstance(left,(list,tuple,dict,str)) and isinstance(right,(list,tuple,dict,str)):
            put("length_difference", [a,b], len(left)-len(right))
    if predicates:
        from .predicates import predicate_roles, predicate_value
        for predicate in predicates:
            term={"kind":"ast","roles":sorted(predicate_roles(predicate)),"expression":predicate}
            result[canonical(term)]=int(predicate_value(predicate,inputs,spec))
    return result


def relation_id(relation):
    return "D-"+digest(relation)[:20]


def validate_relation(relation):
    keys(relation, ("term", "operator", "value"))
    keys(relation["term"], ("kind", "roles"), ("expression",))
    if relation["operator"] not in ("eq","le","ge") or not _numeric(relation["value"]):
        raise ValueError("invalid structural relation")
    roles = relation["term"]["roles"]
    if not isinstance(roles,list) or not 1 <= len(roles) <= (6 if relation["term"]["kind"]=="ast" else 2) or any(not isinstance(x,str) for x in roles):
        raise ValueError("invalid relation roles")
    supported = {"value","absolute","integral","sign","lower_boundary","upper_boundary","length","empty","whitespace","strip_changes","nonascii",
                 "decimal","case_changes","separator","brackets","leading_sign","duplicates","contains_empty",
                 "contains_zero","contains_negative","minimum","maximum","total","range","ordered",
                 "repeated_action","equal","difference","sum","absolute_difference","length_difference"}
    term_kind = relation["term"]["kind"]
    if term_kind=="ast":
        from .predicates import predicate_roles
        if set(relation["term"])!={"kind","roles","expression"} or roles!=sorted(predicate_roles(relation["term"]["expression"])):
            raise ValueError("invalid AST relation roles/expression")
        if len(canonical(relation["term"]["expression"]))>16000 or relation["operator"]!="eq" or relation["value"]!=1:
            raise ValueError("invalid AST predicate membership relation")
    elif "expression" in relation["term"]:
        raise ValueError("expression is permitted only on AST relations")
    elif term_kind not in supported and not (isinstance(term_kind,str) and term_kind.startswith("key:") and len(term_kind) <= 36):
        raise ValueError("unsupported feature kind")
    return relation


def transferable(relation):
    """Forbid copying observed absolute numeric coordinates across targets.

    Zero in role relations is an algebraic equality/order boundary; numeric
    domain-edge features are re-evaluated against each target's declared type.
    Cardinalities and boolean structural properties remain probe hypotheses.
    """
    validate_relation(relation)
    kind=relation["term"]["kind"]
    numeric_coordinates={"value","absolute","minimum","maximum","total","range","sum","difference","absolute_difference"}
    return kind not in numeric_coordinates or relation["value"]==0


def holds(relation, measured):
    value = measured.get(canonical(relation["term"]))
    # A missing feature (e.g. min of an empty list) is explicitly undefined and
    # never positive; this is a partial predicate, not a total arithmetic law.
    if value is None:
        return False
    op, threshold = relation["operator"], relation["value"]
    return value == threshold if op == "eq" else value <= threshold if op == "le" else value >= threshold


def grammar(pool, spec, predicates=()):
    import json
    measured = [measurements(point,spec,predicates) for point in pool]
    terms = sorted({key for row in measured for key in row})
    relations = {}
    masks = {}
    full = (1 << len(pool))-1
    for term in terms:
        if json.loads(term)["kind"]=="ast":
            relation={"term":json.loads(term),"operator":"eq","value":1}
            rid=relation_id(relation)
            relations[rid]=relation
            masks[rid]=sum(1<<i for i,row in enumerate(measured) if holds(relation,row))
            continue
        values = sorted({row[term] for row in measured if term in row})
        selected = set(values if len(values) <= 9 else [values[round(i*(len(values)-1)/8)] for i in range(9)])
        selected.update(x for x in (-1,0,1) if values[0] <= x <= values[-1])
        for value in sorted(selected):
            for op in ("eq","le","ge"):
                relation = {"term":json.loads(term),"operator":op,"value":value}
                mask = sum(1 << i for i,row in enumerate(measured) if holds(relation,row))
                if mask and mask != full:
                    rid = relation_id(relation)
                    relations[rid],masks[rid] = relation,mask
    if len(relations) > 4096:
        raise ValueError("feature grammar exceeds 4096 relations; narrow the public schema")
    return measured,relations,masks


def diversity_descriptor(measured):
    # Preserve structural axes, not exact input identities or oracle scores.
    parts = []
    for name,value in sorted(measured.items()):
        bucket = -1 if value < 0 else 0 if value == 0 else 1 if value == 1 else 2 if value <= 4 else 3
        parts.append((name,bucket))
    return digest(parts)[:16]


def measurements_with_unknowns(inputs, spec, predicates=()):
    """Opt-in R1 measurements; the legacy measurement API stays unchanged."""
    from .claim_semantics import measurements3
    return measurements3(inputs, spec, predicates)


def relation_truth(relation, inputs, spec, *, semantic_policy=None, measured=None):
    """Opt-in three-valued relation truth, including bounded composition."""
    from .claim_semantics import relation_prediction
    return relation_prediction(relation, inputs, spec, semantic_policy, measured=measured)
