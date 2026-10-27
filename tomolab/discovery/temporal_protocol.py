"""Strict public temporal messages; validation runs before any transport write."""
from copy import deepcopy

from .schema import canonical, identifier, integer, keys, validate_inputs, validate_spec

PROTOCOL = "tomolab-temporal-protocol-v1"
MAX_MESSAGE = 8_000_000
FIELDS = {
    "init": (("action", "spec", "temporal_contract"), ("seed", "strategy", "pool_size", "budget", "public_ir")),
    "propose": (("action",), ()),
    "register": (("action", "inputs"), ()),
    "observe": (("action", "evidence"), ()),
    "freeze": (("action",), ()),
    "snapshot": (("action",), ()),
    "metrics": (("action",), ()),
    "transfer": (("action", "snapshot", "spec", "temporal_contract"),
                 ("seed", "budget", "pool_size", "mapping", "target_evidence", "target_ir")),
    "diagnose": (("action", "host_sentinel"), ()),
    "close": (("action",), ()),
}


def validate_request(message, spec=None, temporal_contract=None):
    if not isinstance(message, dict) or message.get("action") not in FIELDS:
        raise ValueError("unknown temporal action")
    action = message["action"]
    keys(message, *FIELDS[action])
    if len(canonical(message)) + 1 > MAX_MESSAGE:
        raise ValueError("temporal message exceeds bound")
    clean = deepcopy(message)
    if action in ("init", "transfer"):
        from .temporal import validate_temporal_contract
        clean["spec"] = validate_spec(message["spec"])
        clean["temporal_contract"] = validate_temporal_contract(message["temporal_contract"], clean["spec"])
        integer(message.get("seed", 7), 0, 2**32-1)
        integer(message.get("pool_size", 128), 1, 4096)
        integer(message.get("budget", 64), 1, 4096)
        if message.get("strategy", "integrated") not in ("integrated", "hypothesis"):
            raise ValueError("unsupported temporal strategy")
        if message.get("public_ir") is not None:
            from .predicates import validate_public_ir
            clean["public_ir"] = validate_public_ir(message["public_ir"], clean["spec"])
    if action == "observe":
        from .temporal import normalize_temporal_evidence
        if spec is None or temporal_contract is None:
            raise ValueError("temporal init required")
        clean["evidence"] = normalize_temporal_evidence(message["evidence"], spec, temporal_contract)
    if action == "register":
        from .temporal import simulate_trace
        if spec is None or temporal_contract is None:
            raise ValueError("temporal init required")
        clean["inputs"] = validate_inputs(message["inputs"],spec)
        if not simulate_trace(clean["inputs"],spec,temporal_contract)["valid"]:
            raise ValueError("native trace violates public state preconditions")
    if action == "transfer":
        from .temporal_engine import TemporalEngine
        from .temporal import normalize_temporal_evidence
        restored = TemporalEngine.from_snapshot(message["snapshot"])
        if not restored.frozen:
            raise ValueError("temporal transfer requires a frozen snapshot")
        if message.get("target_ir") is not None:
            from .predicates import validate_public_ir
            clean["target_ir"] = validate_public_ir(message["target_ir"],clean["spec"])
        if "target_evidence" in message:
            events = message["target_evidence"]
            if not isinstance(events,list) or len(events)>256:
                raise ValueError("bounded approved temporal development evidence required")
            clean["target_evidence"] = [normalize_temporal_evidence(e,clean["spec"],clean["temporal_contract"]) for e in events]
        if message.get("mapping") is not None:
            mapping = message["mapping"]
            if not isinstance(mapping,dict) or len(mapping)>64 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):
                raise ValueError("invalid temporal role mapping")
            for name in [*mapping,*mapping.values()]:
                identifier(name)
            source_names = {v["name"] for v in restored.spec["inputs"]}
            target_names = {v["name"] for v in clean["spec"]["inputs"]}
            for field in ("state","actions"):
                source_names.update(v["name"] for v in restored.temporal_contract[field])
                target_names.update(v["name"] for v in clean["temporal_contract"][field])
            if not set(mapping)<=source_names or not set(mapping.values())<=target_names:
                raise ValueError("mapping must use only declared public input/state/action names")
    if action == "diagnose":
        path = message["host_sentinel"]
        if not isinstance(path,str) or not 1<=len(path)<=4096 or "\x00" in path:
            raise ValueError("invalid public temporal diagnostic sentinel")
    return clean
