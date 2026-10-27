"""Minimal E5 JSON messages, checked before transport and in the worker."""
from copy import deepcopy

from .schema import canonical, identifier, integer, keys, normalize_evidence, validate_spec

PROTOCOL = "tomolab-discovery-protocol-v1"
MAX_MESSAGE = 8_000_000
FIELDS = {
    "init": (("action", "spec"), ("seed", "strategy", "pool_size", "public_ir", "solver")),
    "propose": (("action",), ()),
    "observe": (("action", "evidence"), ()),
    "freeze": (("action",), ()),
    "snapshot": (("action",), ()),
    "transfer": (("action", "snapshot", "spec", "target_ir"),
                 ("seed", "budget", "pool_size", "solver", "mapping", "target_evidence")),
    "diagnose": (("action", "host_sentinel"), ()),
    "close": (("action",), ()),
}


def validate_request(message, spec=None):
    if not isinstance(message, dict) or message.get("action") not in FIELDS:
        raise ValueError("unknown discovery action")
    action = message["action"]
    keys(message, *FIELDS[action])
    if len(canonical(message)) + 1 > MAX_MESSAGE:
        raise ValueError("discovery message exceeds bound")
    clean = deepcopy(message)
    if action in ("init", "transfer"):
        clean["spec"] = validate_spec(message["spec"])
        integer(message.get("seed", 7), 0, 2**32 - 1)
        integer(message.get("pool_size", 128), 1, 4096)
        if message.get("solver", "enumeration") not in ("enumeration", "z3"):
            raise ValueError("unsupported discovery solver")
        if action == "init" and message.get("strategy", "integrated") not in ("integrated", "hypothesis"):
            raise ValueError("unsupported discovery strategy")
        ir = message.get("public_ir") if action == "init" else message["target_ir"]
        if ir is not None:
            from .predicates import validate_public_ir
            validate_public_ir(ir, clean["spec"])
    if action == "observe":
        if spec is None:
            raise ValueError("init required")
        clean["evidence"] = normalize_evidence(message["evidence"], spec)
    if action == "transfer":
        from .engine import DiscoveryEngine
        restored = DiscoveryEngine.from_snapshot(message["snapshot"])
        if not restored.frozen:
            raise ValueError("transfer requires a frozen snapshot")
        integer(message.get("budget", 64), 1, 4096)
        if "target_evidence" in message:
            events = message["target_evidence"]
            if not isinstance(events,list) or len(events) > 256:
                raise ValueError("bounded approved development counterevidence required")
            clean["target_evidence"] = [normalize_evidence(e,clean["spec"]) for e in events]
        if "mapping" in message and message["mapping"] is not None:
            mapping = message["mapping"]
            if not isinstance(mapping, dict) or len(mapping) > 6 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):
                raise ValueError("invalid role mapping")
            for name in [*mapping,*mapping.values()]:
                identifier(name)
            if set(mapping) != {item["name"] for item in restored.spec["inputs"]} or set(mapping.values()) != {item["name"] for item in clean["spec"]["inputs"]}:
                raise ValueError("mapping must use only the complete public parameter names")
    if action == "diagnose":
        path = message["host_sentinel"]
        if not isinstance(path,str) or not 1 <= len(path) <= 4096 or "\x00" in path:
            raise ValueError("invalid public diagnostic sentinel")
    return clean
