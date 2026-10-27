"""Bounded, data-only public contracts. No arbitrary expressions or callables."""
from copy import deepcopy
import hashlib
import json
import math
import re

SCHEMA = "tomolab-discovery-spec-v1"
CATEGORIES = ("mismatch", "exception", "metamorphic", "state_violation")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("missing or unsupported fields")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        raise ValueError("invalid bounded identifier")
    return value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"integer outside [{low}, {high}]")
    return value


def validate_type(value, depth=0):
    if depth > 3 or not isinstance(value, dict):
        raise ValueError("type nesting exceeds supported depth")
    kind = value.get("kind")
    if kind in ("int", "float"):
        keys(value, ("kind", "min", "max"))
        for bound in (value["min"], value["max"]):
            if kind == "int":
                integer(bound, -10**12, 10**12)
            elif type(bound) not in (int, float) or not math.isfinite(bound) or abs(bound) > 10**12:
                raise ValueError("finite bounded float required")
        if value["min"] > value["max"]:
            raise ValueError("reversed numeric bounds")
    elif kind == "str":
        keys(value, ("kind", "alphabet", "min_size", "max_size"), ("choices",))
        if not isinstance(value["alphabet"], str) or len(set(value["alphabet"])) > 128:
            raise ValueError("alphabet must contain at most 128 characters")
        integer(value["min_size"], 0, 64)
        integer(value["max_size"], value["min_size"], 64)
        if not value["alphabet"] and value["max_size"]:
            raise ValueError("nonempty alphabet required")
        if "choices" in value:
            if not isinstance(value["choices"], list) or not 1 <= len(value["choices"]) <= 32:
                raise ValueError("choices must be a bounded nonempty list")
            for choice in value["choices"]:
                validate_value(choice, {k: v for k, v in value.items() if k != "choices"})
    elif kind in ("list", "dict"):
        required = ("kind", "min_size", "max_size", "items") if kind == "list" else ("kind", "min_size", "max_size", "keys", "values")
        keys(value, required)
        integer(value["min_size"], 0, 16)
        integer(value["max_size"], value["min_size"], 16)
        child = value["items"] if kind == "list" else value["values"]
        validate_type(child, depth + 1)
        if kind == "dict":
            if not isinstance(value["keys"], list) or not 1 <= len(value["keys"]) <= 16:
                raise ValueError("dict requires finite declared keys")
            if any(not isinstance(key, str) or not 1 <= len(key) <= 32 for key in value["keys"]):
                raise ValueError("invalid dict key")
            if len(set(value["keys"])) != len(value["keys"]) or value["max_size"] > len(value["keys"]):
                raise ValueError("dict key or cardinality mismatch")
    elif kind == "tuple":
        keys(value, ("kind", "items"))
        if not isinstance(value["items"], list) or not 1 <= len(value["items"]) <= 8:
            raise ValueError("tuple requires 1..8 typed slots")
        for child in value["items"]:
            validate_type(child, depth + 1)
    else:
        raise ValueError("unsupported type kind")
    return deepcopy(value)


def validate_value(value, schema):
    kind = schema["kind"]
    if kind == "int":
        integer(value, schema["min"], schema["max"])
    elif kind == "float":
        if type(value) not in (int, float) or not math.isfinite(value) or not schema["min"] <= value <= schema["max"]:
            raise ValueError("float input violates finite bounds")
    elif kind == "str":
        if not isinstance(value, str) or not schema["min_size"] <= len(value) <= schema["max_size"] or set(value) - set(schema["alphabet"]):
            raise ValueError("string violates declared alphabet or size")
        if "choices" in schema and value not in schema["choices"]:
            raise ValueError("string not in declared choices")
    elif kind == "list":
        if not isinstance(value, list) or not schema["min_size"] <= len(value) <= schema["max_size"]:
            raise ValueError("list size/type mismatch")
        for child in value:
            validate_value(child, schema["items"])
    elif kind == "tuple":
        if not isinstance(value, (list, tuple)) or len(value) != len(schema["items"]):
            raise ValueError("tuple shape mismatch")
        for child, subschema in zip(value, schema["items"]):
            validate_value(child, subschema)
    elif kind == "dict":
        if not isinstance(value, dict) or not schema["min_size"] <= len(value) <= schema["max_size"] or set(value) - set(schema["keys"]):
            raise ValueError("dict shape mismatch")
        for child in value.values():
            validate_value(child, schema["values"])
    return value


def validate_spec(spec):
    keys(spec, ("schema", "task_id", "inputs", "contract"))
    if spec["schema"] != SCHEMA:
        raise ValueError("unsupported discovery spec")
    identifier(spec["task_id"])
    if not isinstance(spec["inputs"], list) or not 1 <= len(spec["inputs"]) <= 6:
        raise ValueError("1..6 named inputs required")
    for item in spec["inputs"]:
        keys(item, ("name", "role", "type"))
        identifier(item["name"])
        identifier(item["role"])
        validate_type(item["type"])
    for field in ("name", "role"):
        if len({item[field] for item in spec["inputs"]}) != len(spec["inputs"]):
            raise ValueError("names and semantic roles must be unique")
    contract = spec["contract"]
    keys(contract, ("id", "operation", "preconditions", "invariants", "state_model", "graph_signature"))
    for field in ("id", "operation", "state_model"):
        identifier(contract[field])
    for field in ("preconditions", "invariants"):
        if not isinstance(contract[field], list) or len(contract[field]) > 32:
            raise ValueError("bounded contract list required")
        for item in contract[field]:
            identifier(item)
        if len(set(contract[field])) != len(contract[field]):
            raise ValueError("duplicate contract item")
    if not contract["invariants"]:
        raise ValueError("at least one invariant required")
    if contract["graph_signature"] != "UNKNOWN" and (not isinstance(contract["graph_signature"], str) or not re.fullmatch('[0-9a-f]{64}', contract["graph_signature"])):
        raise ValueError("graph signature must be SHA-256 or UNKNOWN")
    # Bound serialized request size independently of recursive value depth.
    if len(canonical(spec)) > 32000:
        raise ValueError("spec too large")
    if 2+sum(len(canonical(i["name"]))+2+_encoded_bound(i["type"]) for i in spec["inputs"])>65536:
        raise ValueError("declared input domain exceeds serialized size limit")
    return deepcopy(spec)


def _encoded_bound(schema):
    """Conservative JSON bound, so native generation cannot overrun its contract."""
    kind=schema["kind"]
    if kind=="int":
        return max(len(str(schema["min"])),len(str(schema["max"])))
    if kind=="float":
        return 32
    if kind=="str":
        return max(map(lambda x:len(canonical(x)),schema["choices"])) if "choices" in schema else 2+12*schema["max_size"]
    if kind=="list":
        return 2+schema["max_size"]*(1+_encoded_bound(schema["items"]))
    if kind=="dict":
        key_lengths=sorted((len(canonical(k)) for k in schema["keys"]),reverse=True)[:schema["max_size"]]
        return 2+sum(n+2+_encoded_bound(schema["values"]) for n in key_lengths)
    return 2+sum(1+_encoded_bound(t) for t in schema["items"])


def validate_inputs(inputs, spec):
    keys(inputs, [item["name"] for item in spec["inputs"]])
    for item in spec["inputs"]:
        validate_value(inputs[item["name"]], item["type"])
    if len(canonical(inputs)) > 65536:
        raise ValueError("input exceeds serialized size limit")
    return json.loads(canonical(inputs))


def decode_value(value, schema):
    kind = schema["kind"]
    if kind == "tuple":
        return tuple(decode_value(v, t) for v, t in zip(value, schema["items"]))
    if kind == "list":
        return [decode_value(v, schema["items"]) for v in value]
    if kind == "dict":
        return {k: decode_value(v, schema["values"]) for k, v in value.items()}
    return float(value) if kind == "float" else value


def decode_inputs(inputs, spec):
    clean = validate_inputs(inputs, spec)
    return {item["name"]: decode_value(clean[item["name"]], item["type"]) for item in spec["inputs"]}


def normalize_evidence(evidence, spec):
    keys(evidence, ("kind", "evidence_id", "inputs", "invariant", "category", "signature"))
    if evidence["kind"] not in ("FAILURE", "REFUTATION") or evidence["category"] not in CATEGORIES:
        raise ValueError("unsupported minimal evidence category")
    for field in ("evidence_id", "signature"):
        identifier(evidence[field])
    if evidence["invariant"] not in spec["contract"]["invariants"]:
        raise ValueError("unknown invariant")
    result = deepcopy(evidence)
    result["inputs"] = validate_inputs(evidence["inputs"], spec)
    return result


def type_subset(target, source):
    if target["kind"] != source["kind"]:
        return False
    kind = source["kind"]
    if kind in ("int", "float"):
        return source["min"] <= target["min"] <= target["max"] <= source["max"]
    if kind in ("str", "list", "dict"):
        if not source["min_size"] <= target["min_size"] <= target["max_size"] <= source["max_size"]:
            return False
    if kind == "str":
        if not set(target["alphabet"]) <= set(source["alphabet"]):
            return False
        return "choices" not in source or ("choices" in target and set(target["choices"]) <= set(source["choices"]))
    if kind == "list":
        return type_subset(target["items"], source["items"])
    if kind == "dict":
        return set(target["keys"]) <= set(source["keys"]) and type_subset(target["values"], source["values"])
    if kind == "tuple":
        return len(target["items"]) == len(source["items"]) and all(type_subset(t, s) for t, s in zip(target["items"], source["items"]))
    return True
