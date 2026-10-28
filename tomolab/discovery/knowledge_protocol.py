"""Pure public E7 messages, validated before transport and inside the worker."""
from copy import deepcopy
import json

from .schema import canonical, integer, keys, validate_spec

PROTOCOL = "tomolab-knowledge-protocol-v1"
MAX_MESSAGE = 8_000_000
OPTIONS = ("archive", "temporal_contract", "target_provenance", "public_ir", "seed", "budget", "pool_size", "guidance_budget",
           "purpose", "allow_unvalidated_empirical")
FIELDS = {
    "init": (("action", "spec"), OPTIONS),
    "plan": (("action", "spec", "archive"), tuple(k for k in OPTIONS if k != "archive")),
    "propose": (("action",), ()), "observe": (("action", "evidence"), ()),
    "freeze": (("action",), ()), "snapshot": (("action",), ()),
    "metrics": (("action",), ()), "close": (("action",), ()),
    "diagnose": (("action", "host_sentinel"), ()),
}


def semantic_observation_mode(initialization):
    """Derive observation meaning only from an already validated init/plan."""
    from .knowledge import SEMANTIC_SCHEMA
    archive = initialization.get("archive")
    return (initialization.get("purpose", "INDEPENDENT_TRANSFER") == "SOURCE_DEVELOPMENT"
            or isinstance(archive, dict) and archive.get("schema") == SEMANTIC_SCHEMA)


def validate_request(message, spec=None, temporal_contract=None, target_provenance=None,
                     semantic_mode=False):
    # Validate and return one immutable JSON capture. A caller mutating nested
    # dictionaries must never change the payload after a different copy passed.
    if type(semantic_mode) is not bool:
        raise ValueError("initialized semantic observation mode must be Boolean")
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
        # An empirical trial is an explicit Source-development request, never
        # an alternative route around independent transfer qualification. Do
        # not insert defaults into legacy message captures or their digests.
        purpose = message.get("purpose", "INDEPENDENT_TRANSFER")
        empirical = message.get("allow_unvalidated_empirical", False)
        if purpose not in ("INDEPENDENT_TRANSFER", "SOURCE_DEVELOPMENT"):
            raise ValueError("explicit Source development or independent transfer purpose required")
        if type(empirical) is not bool or empirical and purpose != "SOURCE_DEVELOPMENT":
            raise ValueError("unadopted empirical rules are Source development experiments only")
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
        from .knowledge import normalize_observation, normalize_semantic_observation, validate_provenance
        if spec is None or target_provenance is None:
            raise ValueError("knowledge init with declared target provenance required")
        normalize = normalize_semantic_observation if semantic_mode else normalize_observation
        event = normalize(message["evidence"])
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
