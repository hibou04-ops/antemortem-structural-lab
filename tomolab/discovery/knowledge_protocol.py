"""Pure public E7 messages, validated before transport and inside the worker."""
from copy import deepcopy
import json

from .schema import canonical, integer, keys, validate_spec

PROTOCOL = "tomolab-knowledge-protocol-v1"
MAX_MESSAGE = 8_000_000
OPTIONS = ("archive", "temporal_contract", "target_provenance", "public_ir", "seed", "budget", "pool_size", "guidance_budget")
FIELDS = {
    "init": (("action", "spec"), OPTIONS),
    "plan": (("action", "spec", "archive"), tuple(k for k in OPTIONS if k != "archive")),
    "propose": (("action",), ()), "observe": (("action", "evidence"), ()),
    "freeze": (("action",), ()), "snapshot": (("action",), ()),
    "metrics": (("action",), ()), "close": (("action",), ()),
    "diagnose": (("action", "host_sentinel"), ()),
}


def validate_request(message, spec=None, temporal_contract=None, target_provenance=None):
    # Validate and return one immutable JSON capture. A caller mutating nested
    # dictionaries must never change the payload after a different copy passed.
    captured = canonical(message)
    if len(captured)+1 > MAX_MESSAGE:
        raise ValueError("knowledge message exceeds bound")
    message = json.loads(captured)
    if not isinstance(message, dict) or message.get("action") not in FIELDS:
        raise ValueError("unknown knowledge action")
    action = message["action"]
    keys(message, *FIELDS[action])
    clean = deepcopy(message)
    if action in ("init", "plan"):
        from .knowledge import KnowledgeArchive, validate_provenance
        clean["spec"] = validate_spec(message["spec"])
        if message.get("archive") is not None:
            archive = KnowledgeArchive.from_snapshot(message["archive"])
            if not archive.frozen:
                raise ValueError("knowledge transfer requires a frozen source archive")
            clean["archive"] = archive.snapshot()
        if message.get("target_provenance") is not None:
            clean["target_provenance"] = validate_provenance(message["target_provenance"])
        if message.get("temporal_contract") is not None:
            from .temporal import validate_temporal_contract
            clean["temporal_contract"] = validate_temporal_contract(message["temporal_contract"], clean["spec"])
        if message.get("public_ir") is not None:
            from .predicates import validate_public_ir
            clean["public_ir"] = validate_public_ir(message["public_ir"], clean["spec"])
        integer(message.get("seed", 7), 0, 2**32-1)
        integer(message.get("budget", 64), 1, 4096)
        integer(message.get("pool_size", 64), 1, 4096)
        integer(message.get("guidance_budget", 16), 0, 2048)
    elif action == "observe":
        from .knowledge import normalize_observation, validate_provenance
        if spec is None or target_provenance is None:
            raise ValueError("knowledge init with declared target provenance required")
        event = normalize_observation(message["evidence"])
        if (canonical(event["spec"]) != canonical(spec)
                or canonical(event["temporal_contract"]) != canonical(temporal_contract)
                or canonical(event["origin"]) != canonical(validate_provenance(target_provenance))):
            raise ValueError("knowledge observation must match initialized public target scope")
        clean["evidence"] = event
    elif action == "diagnose":
        value = message["host_sentinel"]
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\x00" in value:
            raise ValueError("invalid public diagnostic sentinel")
    return clean
