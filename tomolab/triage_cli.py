"""Bounded data-only static triage; no download or external execution path."""
from collections import Counter
import json
from pathlib import Path
import re

COMMANDS = {"harvest-triage"}
INPUT_SCHEMA = "tomolab-prequalification-triage-input-v1"
MAX_MANIFEST_BYTES = 64 * 1024 * 1024


def register(commands):
    command = commands.add_parser("harvest-triage", help="Classify bounded hash-bound source data by static AST inspection only")
    command.add_argument("--manifest", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)


def triage_manifest(manifest):
    from .discovery.prequalification_triage import triage_record
    from .discovery.schema import digest
    if (type(manifest) is not dict or set(manifest) - {"schema", "records", "expected_candidate_ids", "read_plan_sha256"}
            or manifest.get("schema") != INPUT_SCHEMA):
        raise ValueError("strict bounded data-only triage manifest required")
    records = manifest.get("records")
    if type(records) is not list or not 1 <= len(records) <= 64:
        raise ValueError("one to 64 prospectively bounded triage records required")
    ids = [record.get("candidate_id") if type(record) is dict else None for record in records]
    if any(type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("unique original candidate identities required")
    if "expected_candidate_ids" in manifest and manifest["expected_candidate_ids"] != ids:
        raise ValueError("records differ from the frozen candidate order/denominator")
    pin = manifest.get("read_plan_sha256")
    if pin is not None and (type(pin) is not str or re.fullmatch(r"[a-f0-9]{64}", pin) is None):
        raise ValueError("explicit read-plan digest required")
    results = [triage_record(record) for record in records]
    value = dict(schema="tomolab-prequalification-triage-batch-v1", status="COMPLETE", read_plan_sha256=pin, denominator=len(records),
        candidate_ids=ids, outcomes=dict(sorted(Counter(row["status"] for row in results).items())),
        candidate_sequence_int=sum(row["status"] == "CANDIDATE_SEQUENCE_INT" for row in results),
        candidate_text=sum(row["status"] == "CANDIDATE_TEXT" for row in results), results=results,
        qualified=0, oracle_independence="UNKNOWN", source_imported=False, source_executed=False, source_pytest=False,
        target_calls=0, oracle_calls=0, network_requests=0, policy_updates=0,
        scope="STATIC_CANDIDATES_ONLY_NOT_REPRODUCED_NOT_QUALIFIED_NOT_OOS")
    value["sha256"] = digest(value)
    return value


def dispatch(args):
    from .discovery.harvester_service import save_new
    if args.command != "harvest-triage":
        raise ValueError("unknown static triage command")
    path = args.manifest
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("bounded regular data-only triage manifest required")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("triage output must be a new file")
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                raise ValueError("duplicate triage JSON field")
            value[key] = child
        return value
    manifest = json.loads(path.read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite triage JSON")))
    result = triage_manifest(manifest)
    save_new(args.output, result)
    return result
