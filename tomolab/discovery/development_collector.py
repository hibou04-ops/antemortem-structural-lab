"""Reviewed-host Native Hypothesis collection into the E8 evidence contract.

This executes only caller-approved development functions. It is not an OS
sandbox, an ownership check, or proof of Oracle/implementation independence.
No generator worker receives callbacks, original outcomes, or source bodies.
``max_calls`` bounds target PLUS Oracle calls, including every replay; 256
therefore permits at most 128 complete pairs. A callback must itself return.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from importlib.metadata import version
import inspect
import re
import time

from .development_evidence import DevelopmentEvidenceArchive
from .knowledge import validate_provenance
from .schema import canonical, decode_inputs, digest, identifier, integer, keys, validate_inputs, validate_spec


def _exception(error):
    return {"kind": "exception", "type": type(error).__module__ + "." + type(error).__qualname__}


def _arguments(signature, arguments):
    arguments = deepcopy(arguments)
    positional = []
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            if parameter.name not in arguments:
                raise ValueError("all positional-only parameters must be declared")
            positional.append(arguments.pop(parameter.name))
    signature.bind(*positional, **arguments)
    return positional, arguments


def collect_native_development(target, oracle, spec, *, provenance, function_identity,
                               generation_id, oracle_validation_receipt, budget=64,
                               seed=7, max_calls=256, input_accepts=None,
                               trusted_execution=False):
    """Collect fresh development observations with native generation and shrink.

    Oracle validation is a reviewed host receipt, pinned BEFORE execution. Its
    input/execution bindings are derived only after freezing the original raw
    receipt. Original outcomes remain host data; ``evidence_bundle`` is also
    host-only. Export through DevelopmentEvidenceArchive's existing minimal API.

    Only a pre-reviewed ``EXACT_CANONICAL_JSON`` comparison policy is supported.
    Numerical tolerance comparisons and contractually normal exceptions are
    outside this collector's scope; do not classify those contracts with it.

    The fixed policy reserves four primitive calls for two witness replay pairs.
    After search, replay the final observed witness first, then remaining points
    in original observation order. Every accepted new point requires two actual
    replay pairs; search duplicates alone never substitute for explicit replay.
    Missing budget, an exception, or any changed result quarantines the point.
    """
    if trusted_execution is not True:
        raise PermissionError("reviewed development target and Oracle require explicit trusted execution")
    if not callable(target) or not callable(oracle) or target is oracle:
        raise ValueError("distinct reviewed development target and Oracle callables required")
    if input_accepts is not None and not callable(input_accepts):
        raise ValueError("reviewed domain guard must be callable")
    spec = validate_spec(spec)
    origin = validate_provenance(provenance)
    for field in ("implementation_sha256", "oracle_sha256"):
        if field not in origin:
            raise ValueError("pinned implementation and Oracle hashes required")
    identifier(generation_id)
    if not isinstance(function_identity, str) or not 1 <= len(function_identity) <= 1024 or "\x00" in function_identity:
        raise ValueError("explicit reviewed function identity required")
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("one independently reviewed invariant per collection")
    integer(budget, 1, 4096); integer(seed, 0, 2**32-1); integer(max_calls, 0, 10000)
    review = deepcopy(oracle_validation_receipt)
    keys(review, ("status", "receipt_id", "oracle_hash", "public_spec_hash", "receipt_sha256", "comparison_policy"),
         ("authority", "source_receipt_sha256", "limitations"))
    if review["status"] != "VALIDATED" or review["oracle_hash"] != origin["oracle_sha256"] or review["public_spec_hash"] != digest(spec):
        raise ValueError("validated Oracle receipt must match the reviewed Oracle and public specification before execution")
    if review["comparison_policy"] != "EXACT_CANONICAL_JSON":
        raise ValueError("only a pre-reviewed EXACT_CANONICAL_JSON comparison policy is supported")
    if not isinstance(review["receipt_id"], str) or not review["receipt_id"]:
        raise ValueError("Oracle review receipt identity required")
    for field in ("oracle_hash", "public_spec_hash", "receipt_sha256"):
        if not isinstance(review[field], str) or not re.fullmatch(r"[a-f0-9]{64}", review[field]):
            raise ValueError("pinned Oracle review SHA-256 required")
    canonical(review)
    signatures = {"target": inspect.signature(target), "oracle": inspect.signature(oracle)}
    for signature in signatures.values():
        _arguments(signature, {item["name"]: None for item in spec["inputs"]})
    # Optional QA dependency is loaded only after execution approval and scope.
    from .hypothesis_adapter import BudgetExhausted, native_find
    producer_version = version("hypothesis")
    started, cpu = time.perf_counter(), time.process_time()
    counters = dict(target_calls=0, oracle_calls=0, replay_target_calls=0, replay_oracle_calls=0,
                    domain_rejections=0, guard_errors=0)
    rows = []
    search_limit = max(0, max_calls - 4)

    def primitive_calls():
        return counters["target_calls"] + counters["oracle_calls"]

    def invoke(name, callback, point, phase):
        positional, arguments = _arguments(signatures[name], decode_inputs(point, spec))
        counters[name + "_calls"] += 1
        if phase == "replay":
            counters["replay_" + name + "_calls"] += 1
        try:
            result = callback(*positional, **arguments)
        except Exception as error:
            return _exception(error), False
        try:
            encoded = canonical(result)
            if len(encoded) > 65536:
                raise ValueError("oversized reviewed outcome")
            return {"kind": "return", "value": deepcopy(result)}, True
        except (ValueError, TypeError, OverflowError):
            return {"kind": "unsupported-result", "type": type(result).__module__ + "." + type(result).__qualname__}, False

    def execute(point, phase):
        if time.perf_counter() - started >= 15:
            raise BudgetExhausted()
        clean = validate_inputs(point, spec)
        row = dict(row_id="native-row-%05d" % len(rows), phase=phase, input_or_trace=deepcopy(clean),
                   domain_validity="VALID", status="NOT_EXECUTED", actual_result=None, oracle_result=None,
                   target_calls=0, oracle_calls=0)
        if input_accepts is not None:
            try:
                allowed = input_accepts(deepcopy(clean))
                if type(allowed) is not bool:
                    raise ValueError("domain guard must return an exact bool")
            except Exception as error:
                row.update(domain_validity="GUARD_ERROR", status="GUARD_ERROR", guard_error=_exception(error))
                counters["guard_errors"] += 1
                rows.append(row)
                return False
            if not allowed:
                row.update(domain_validity="OUT_OF_DOMAIN", status="OUT_OF_DOMAIN")
                counters["domain_rejections"] += 1
                rows.append(row)
                return False
        limit = search_limit if phase == "search-and-shrink" else max_calls
        if primitive_calls() + 2 > limit:
            raise BudgetExhausted()
        row["oracle_result"], oracle_ok = invoke("oracle", oracle, clean, phase)
        row["oracle_calls"] = 1
        if not oracle_ok:
            row["status"] = "INVALID_ORACLE"
        else:
            row["actual_result"], target_ok = invoke("target", target, clean, phase)
            row["target_calls"] = 1
            if not target_ok:
                row["status"] = "EXECUTION_ERROR"
            else:
                row["status"] = "FAILURE" if canonical(row["actual_result"]) != canonical(row["oracle_result"]) else "REFUTATION"
        rows.append(row)
        return row["status"] == "FAILURE"

    try:
        native = native_find(spec, lambda point: execute(point, "search-and-shrink"),
                             budget=budget, seed=seed, cache=False)
        native["predicate_calls"] = native.pop("oracle_calls")
    except Exception as error:
        # E.g. Hypothesis' own flaky-result rejection is host collection evidence,
        # never a product failure or successful native shrink.
        native = dict(status="NATIVE_COLLECTION_ERROR", error=_exception(error), witness=None,
                      shrinking="INCOMPLETE_OR_NO_WITNESS", cache_enabled=False, cache_hits=0)
    search_rows = list(rows)
    witness = native.get("witness")
    if witness is None:
        witness = next((r["input_or_trace"] for r in search_rows if r["status"] == "FAILURE"), None)
    points, seen = [], set()
    for point in ([witness] if witness is not None else []) + [r["input_or_trace"] for r in search_rows if r["status"] in ("FAILURE", "REFUTATION")]:
        key = canonical(point)
        if key not in seen:
            seen.add(key); points.append(point)
    for point in points:
        for _ in range(2):
            try:
                execute(point, "replay")
            except BudgetExhausted:
                break
    raw = dict(schema="tomolab-native-development-host-receipt-v1", generation_id=generation_id,
               split="DEVELOPMENT", producer_tool="NativeHypothesis", producer_version=producer_version,
               project=origin["project"], revision=origin["revision"], function_identity=function_identity,
               implementation_hash=origin["implementation_sha256"], oracle_identity=origin["oracle_id"],
               oracle_hash=origin["oracle_sha256"], public_spec_hash=digest(spec), oracle_validation_receipt=review,
               budget=budget, seed=seed, max_calls=max_calls, execution_kind="NEW_EXECUTION", comparison_policy="EXACT_CANONICAL_JSON",
               policy="native_find cache=False/database=None; reserve2witness-replay-pairs; every accepted point needs2explicit-replay-pairs; exact JSON outcome comparison; cooperative15second-wall-limit",
               ownership_and_purity="REVIEWED_HOST_ATTESTATION_REQUIRED; NOT_AN_OS_SANDBOX",
               native_search=deepcopy(native), raw=rows, **counters,
               actual_primitive_calls=primitive_calls(), wall_seconds=time.perf_counter()-started,
               cpu_seconds=time.process_time()-cpu)
    assert raw["actual_primitive_calls"] <= max_calls
    raw["receipt_sha256"] = digest(raw)  # Freeze original execution BEFORE derived records.
    raw_sha = raw["receipt_sha256"]
    groups = defaultdict(list)
    for row in rows:
        groups[canonical(row["input_or_trace"])].append(row)
    ledger = DevelopmentEvidenceArchive(generation_id)
    for row in rows:
        group = groups[canonical(row["input_or_trace"])]
        labels = {digest({k: r[k] for k in ("status", "actual_result", "oracle_result", "domain_validity")}) for r in group}
        replay_rows = [r for r in group if r["phase"] == "replay" and r["status"] in ("FAILURE", "REFUTATION")]
        verified = len(labels) == 1 and len(replay_rows) == 2
        refs = [{"raw_receipt_sha256": raw_sha, "row_id": r["row_id"], "row_sha256": digest(r)} for r in group]
        bindings = dict(implementation_hash=origin["implementation_sha256"], oracle_identity=origin["oracle_id"],
                        oracle_hash=origin["oracle_sha256"], public_spec_hash=digest(spec),
                        input_hash=digest(row["input_or_trace"]), original_receipt_sha256=raw_sha)
        oracle_record = deepcopy(review)
        oracle_record["bindings"] = deepcopy(bindings)
        if row["status"] == "INVALID_ORACLE":
            oracle_record["status"] = "INVALID_ORACLE"
        outcome_status = row["status"] if row["status"] in ("FAILURE", "REFUTATION") else "ERROR"
        record = dict(record_id="native-" + digest([raw_sha, row["row_id"]])[:32], generation_id=generation_id,
            split="DEVELOPMENT", producer_tool="NativeHypothesis", producer_version=producer_version,
            project=origin["project"], revision=origin["revision"], function_identity=function_identity,
            implementation_hash=origin["implementation_sha256"], oracle_identity=origin["oracle_id"], oracle_hash=origin["oracle_sha256"],
            public_spec_hash=digest(spec), spec=spec, oracle_validation_receipt=oracle_record,
            domain_validity=dict(status=row["domain_validity"], receipt_sha256=digest([raw_sha, row["domain_validity"], row["input_or_trace"]]), bindings=deepcopy(bindings)),
            input_or_trace=deepcopy(row["input_or_trace"]), observed_failure_or_refutation=dict(status=outcome_status,
                invariant=spec["contract"]["invariants"][0], category="mismatch", actual_result=deepcopy(row["actual_result"]), oracle_result=deepcopy(row["oracle_result"])),
            failure_signature="reference-comparison", replay_status=dict(status="REPRODUCED" if verified else "NOT_VERIFIED",
                deterministic=verified, matching_observations=len(group), receipt_sha256=digest(refs),
                kind="NEW_EXECUTION_EXPLICIT_REPLAY", observation_refs=refs, bindings=deepcopy(bindings)),
            execution_receipt=dict(status="COMPLETED" if outcome_status != "ERROR" else "ERROR", execution_kind="NEW_EXECUTION",
                target_calls=row["target_calls"], oracle_calls=row["oracle_calls"], original_receipt_sha256=raw_sha,
                original_receipt_id=row["row_id"], bindings=deepcopy(bindings)),
            provenance=dict(origin=deepcopy(origin), evidence_origin="NATIVE_HYPOTHESIS_NEW_DEVELOPMENT", parent_generation_id=None,
                source_file_sha256=raw_sha, source_record_sha256=digest(row), source_locator="host-receipt:" + raw_sha + "#" + row["row_id"],
                authority="CALLER_REVIEWED_DEVELOPMENT_ONLY", limitations="Explicit host approval is not proof of ownership, Oracle correctness or independent implementation."))
        ledger.ingest(record, trusted_host=True)
    bundle = ledger.snapshot()
    summary = dict(ledger.summary(), actual_target_calls=counters["target_calls"], actual_oracle_calls=counters["oracle_calls"],
                   actual_primitive_calls=primitive_calls(), replay_target_calls=counters["replay_target_calls"],
                   replay_oracle_calls=counters["replay_oracle_calls"], domain_rejections=counters["domain_rejections"],
                   guard_errors=counters["guard_errors"], max_calls=max_calls, budget_unit="TARGET_PLUS_ORACLE_PRIMITIVE_CALLS",
                   raw_receipt_sha256=raw_sha, producer_version=producer_version,
                   comparison_policy="EXACT_CANONICAL_JSON",
                   quarantine_reasons=dict(Counter(reason for row in bundle["journal"] for reason in row["decision"]["reasons"])),
                   total_wall_seconds=time.perf_counter()-started, total_cpu_seconds=time.process_time()-cpu,
                   source_oracle_independence="NOT_ESTABLISHED_BY_DISTINCT_CALLABLES_OR_HASHES")
    return dict(schema="tomolab-native-development-collection-v1", status="VALID_FAILURE_COLLECTED" if summary["valid_failures"] else "NO_VALID_FAILURE_COLLECTED",
                raw_receipt=raw, evidence_bundle=bundle, summary=summary, native_search=deepcopy(native))
