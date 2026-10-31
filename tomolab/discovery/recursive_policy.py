"""Data-only binary selector for reviewed paired development experience.

This sidecar does not alter Mold rules or their empirical scores.  Its utility
is an equal-lineage descriptive statistic, never a success probability.
Host receipt validation is imported only by the development update function;
the worker needs only the bounded data validator and deterministic lookup.
"""
from copy import deepcopy
from fractions import Fraction
import math
import re

from .online_mold import _features
from .online_schema import KINDS, common_operators
from .schema import canonical, digest, identifier, keys

SELECTOR_SCHEMA = "tomolab-binary-selector-v1"
RUNTIME_SELECTOR_SCHEMA = "tomolab-binary-selector-runtime-v1"
MANIFEST_SCHEMA = "tomolab-selector-development-v1"
ALGORITHM = "equal-lineage-net-paired-utility-v1"
ALGORITHM_SPEC = dict(version=ALGORITHM, minimum_resolved_lineages=2,
    statistic="mean_lineage((gain-loss)/resolved)", threshold="strictly_positive",
    unresolved_lineage="abstain", unknown="not_zero_reward", fallback="common")
ALGORITHM_DIGEST = digest(ALGORITHM_SPEC)
MAX_RECEIPTS = 4096
MAX_SELECTOR_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_LINEAGES = 128
CONTEXT_FIELDS = ("kind", "size_class", "all_equal", "has_negative",
                  "common_operator", "learned_edit_composition")
LABELS = ("gain", "loss", "neutral_pass", "neutral_failure", "UNKNOWN")
EVIDENCE_CLASSES = ("AUTHORED_SYNTHETIC_FIXTURE", "REVIEWED_REAL_DEVELOPMENT")
LINEAGE_FIELDS = ("source_lineage_id", "project_id", "mechanism_id",
    "implementation_sha256", "oracle_sha256", "input_contract_sha256",
    "independence_id", "review_id")


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError("SHA256 identity required")
    return value


def _signed(value, field):
    return {**value, field: digest(value)}


def _check_digest(value, field):
    _sha(value.get(field))
    if value[field] != digest({k: v for k, v in value.items() if k != field}):
        raise ValueError("selector or manifest content digest mismatch")


def validate_context(context):
    keys(context, CONTEXT_FIELDS)
    if context["kind"] not in KINDS:
        raise ValueError("unsupported selector kind")
    if context["size_class"] not in ("EMPTY", "SINGLETON", "MANY", "UNKNOWN"):
        raise ValueError("unsupported size class")
    for name in ("all_equal", "has_negative"):
        if type(context[name]) is not bool and context[name] != "UNKNOWN":
            raise ValueError("missing public features must remain UNKNOWN")
    operators = common_operators(context["kind"])
    if context["common_operator"] is not None and context["common_operator"] not in operators:
        raise ValueError("unsupported common operator")
    edits = context["learned_edit_composition"]
    if not isinstance(edits, list) or not 1 <= len(edits) <= 2 or any(op not in operators for op in edits):
        raise ValueError("unsupported frozen Mold edit composition")
    return deepcopy(context)


def make_context(anchor, contract, common_operator, learned_operators):
    features = _features(anchor)
    context = dict(kind=contract["kind"],
        size_class=features.get("size_class", "UNKNOWN"),
        all_equal=features.get("all_equal", "UNKNOWN"),
        has_negative=features.get("has_negative", "UNKNOWN"),
        common_operator=common_operator,
        learned_edit_composition=list(learned_operators))
    return validate_context(context)


def validate_development_manifest(manifest):
    keys(manifest, ("schema", "split", "experiment_contract_sha256", "evidence_class",
                    "lineages", "manifest_digest"))
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported development manifest version")
    if manifest["split"] != "development":
        raise PermissionError("final evaluation feedback is forbidden")
    if manifest["evidence_class"] not in EVIDENCE_CLASSES:
        raise ValueError("explicit synthetic or reviewed real provenance required")
    _sha(manifest["experiment_contract_sha256"])
    lineages = manifest["lineages"]
    if not isinstance(lineages, list) or not 1 <= len(lineages) <= MAX_MANIFEST_LINEAGES:
        raise ValueError("bounded reviewed lineage manifest required")
    seen = set()
    identities = {}
    for row in lineages:
        keys(row, LINEAGE_FIELDS)
        for name in ("source_lineage_id", "project_id", "mechanism_id", "independence_id", "review_id"):
            identifier(row[name])
        for name in ("implementation_sha256", "oracle_sha256", "input_contract_sha256"):
            _sha(row[name])
        if row["source_lineage_id"] in seen:
            raise ValueError("duplicate development lineage")
        seen.add(row["source_lineage_id"])
        # The same reviewed implementation/Oracle unit cannot acquire a new
        # independent vote merely by changing its visible lineage label.
        unit = row["implementation_sha256"]
        if unit in identities and identities[unit] != row["independence_id"]:
            raise ValueError("same implementation unit has conflicting independence IDs")
        identities[unit] = row["independence_id"]
    _check_digest(manifest, "manifest_digest")
    return deepcopy(manifest)


def make_development_manifest(lineages, experiment_contract_sha256, *,
                              evidence_class="AUTHORED_SYNTHETIC_FIXTURE"):
    manifest = _signed(dict(schema=MANIFEST_SCHEMA, split="development",
        experiment_contract_sha256=experiment_contract_sha256,
        evidence_class=evidence_class, lineages=deepcopy(lineages)), "manifest_digest")
    return validate_development_manifest(manifest)


def _statistics(evidence):
    contexts = {}
    for row in evidence:
        context_key = canonical(row["context"])
        context_row = contexts.setdefault(context_key,
            dict(context=deepcopy(row["context"]), lineages={}))
        # Independence IDs are reviewed defect/implementation units, not seeds.
        unit = row["independence_id"]
        stat = context_row["lineages"].setdefault(unit,
            dict(independence_id=unit, source_lineage_ids=[], gain=0, loss=0,
                 neutral_pass=0, neutral_failure=0, resolved=0, unknown=0))
        if row["source_lineage_id"] not in stat["source_lineage_ids"]:
            stat["source_lineage_ids"].append(row["source_lineage_id"])
            stat["source_lineage_ids"].sort()
        if row["label"] == "UNKNOWN":
            stat["unknown"] += 1
        else:
            stat[row["label"]] += 1
            stat["resolved"] += 1
    result = []
    for context_key in sorted(contexts):
        row = contexts[context_key]
        lineages = [row["lineages"][unit] for unit in sorted(row["lineages"])]
        resolved = [stat for stat in lineages if stat["resolved"]]
        # A lineage with no resolved outcome makes its contribution unknown.
        # Compute the sign exactly: floating 0.1 + 0.2 - 0.3 must not
        # manufacture a positive intervention at the strict-zero threshold.
        utility = None if len(resolved) != len(lineages) else float(sum(
            (Fraction(stat["gain"]-stat["loss"], stat["resolved"]) for stat in resolved),
            Fraction())/len(resolved))
        result.append(dict(context=row["context"], lineages=lineages,
            resolved_lineages=len(resolved), utility=utility,
            choice="learned" if len(resolved) >= 2 and utility is not None and utility > 0 else "common"))
    return result


def initial_selector(mold_digest, *, input_contract_digest=None):
    _sha(mold_digest)
    if input_contract_digest is not None:
        _sha(input_contract_digest)
    return _signed(dict(schema=SELECTOR_SCHEMA, algorithm=ALGORITHM,
        algorithm_digest=ALGORITHM_DIGEST, mold_digest=mold_digest,
        input_contract_digest=input_contract_digest, final_feedback_allowed=False,
        consumed_manifest_digests=[], evidence=[], statistics=[]), "selector_digest")


def validate_selector(selector, *, mold_digest=None):
    if isinstance(selector, dict) and selector.get("schema") == RUNTIME_SELECTOR_SCHEMA:
        return validate_runtime_selector(selector, mold_digest=mold_digest)
    keys(selector, ("schema", "algorithm", "algorithm_digest", "mold_digest",
        "input_contract_digest", "final_feedback_allowed", "consumed_manifest_digests",
        "evidence", "statistics", "selector_digest"))
    if (selector["schema"] != SELECTOR_SCHEMA or selector["algorithm"] != ALGORITHM
            or selector["algorithm_digest"] != ALGORITHM_DIGEST):
        raise ValueError("unsupported selector schema or update algorithm")
    if selector["final_feedback_allowed"] is not False:
        raise PermissionError("final feedback is never allowed")
    _sha(selector["mold_digest"])
    if mold_digest is not None and selector["mold_digest"] != mold_digest:
        raise ValueError("selector belongs to a different frozen Mold")
    if selector["input_contract_digest"] is not None:
        _sha(selector["input_contract_digest"])
    manifests = selector["consumed_manifest_digests"]
    if not isinstance(manifests, list) or len(manifests) > MAX_RECEIPTS or len(set(manifests)) != len(manifests):
        raise ValueError("invalid consumed development manifests")
    for item in manifests:
        _sha(item)
    evidence = selector["evidence"]
    if not isinstance(evidence, list) or len(evidence) > MAX_RECEIPTS:
        raise ValueError("bounded paired evidence required")
    reservations, receipts, units, lineage_identities = set(), set(), {}, {}
    for row in evidence:
        keys(row, ("reservation_id", "pair_receipt_sha256", "manifest_digest", "source_lineage_id",
            "project_id", "mechanism_id", "independence_id", "implementation_sha256", "oracle_sha256",
            "input_contract_sha256", "evidence_class", "context", "label", "cost"))
        for name in ("reservation_id", "pair_receipt_sha256", "manifest_digest",
                     "implementation_sha256", "oracle_sha256", "input_contract_sha256"):
            _sha(row[name])
        for name in ("source_lineage_id", "project_id", "mechanism_id", "independence_id"):
            identifier(row[name])
        if row["manifest_digest"] not in manifests or row["evidence_class"] not in EVIDENCE_CLASSES:
            raise ValueError("unbound development evidence")
        if selector["input_contract_digest"] is not None and row["input_contract_sha256"] != selector["input_contract_digest"]:
            raise ValueError("selector input contract differs from evidence")
        validate_context(row["context"])
        if row["label"] not in LABELS:
            raise ValueError("unsupported paired label")
        if row["reservation_id"] in reservations or row["pair_receipt_sha256"] in receipts:
            raise ValueError("duplicate paired support")
        reservations.add(row["reservation_id"]); receipts.add(row["pair_receipt_sha256"])
        identity = row["implementation_sha256"]
        if identity in units and units[identity] != row["independence_id"]:
            raise ValueError("renamed lineage cannot create independent support")
        units[identity] = row["independence_id"]
        lineage_identity = tuple(row[name] for name in ("project_id", "mechanism_id",
            "independence_id", "implementation_sha256", "oracle_sha256", "input_contract_sha256"))
        if row["source_lineage_id"] in lineage_identities and lineage_identities[row["source_lineage_id"]] != lineage_identity:
            raise ValueError("development lineage identity changed across manifests")
        lineage_identities[row["source_lineage_id"]] = lineage_identity
        _validate_pair_cost(row["cost"])
    if selector["statistics"] != _statistics(evidence):
        raise ValueError("selector statistics do not replay from preserved experience")
    _check_digest(selector, "selector_digest")
    if len(canonical(selector).encode()) > MAX_SELECTOR_BYTES:
        raise ValueError("selector byte cap exceeded")
    return deepcopy(selector)


def validate_runtime_selector(selector, *, mold_digest=None):
    """Worker projection contains no receipt, implementation or Oracle hashes."""
    keys(selector, ("schema", "algorithm", "algorithm_digest", "mold_digest",
        "input_contract_digest", "final_feedback_allowed", "source_selector_digest",
        "contexts", "selector_digest"))
    if (selector["schema"] != RUNTIME_SELECTOR_SCHEMA or selector["algorithm"] != ALGORITHM
            or selector["algorithm_digest"] != ALGORITHM_DIGEST):
        raise ValueError("unsupported runtime selector schema or algorithm")
    if selector["final_feedback_allowed"] is not False:
        raise PermissionError("final feedback is never allowed")
    _sha(selector["mold_digest"]); _sha(selector["source_selector_digest"])
    if mold_digest is not None and selector["mold_digest"] != mold_digest:
        raise ValueError("runtime selector belongs to a different frozen Mold")
    if selector["input_contract_digest"] is not None:
        _sha(selector["input_contract_digest"])
    rows = selector["contexts"]
    if not isinstance(rows, list) or len(rows) > MAX_RECEIPTS:
        raise ValueError("bounded runtime selector contexts required")
    contexts = set()
    for row in rows:
        keys(row, ("context", "resolved_lineages", "unresolved_lineages", "utility", "choice"))
        validate_context(row["context"])
        token = canonical(row["context"])
        if token in contexts:
            raise ValueError("duplicate runtime selector context")
        contexts.add(token)
        for name in ("resolved_lineages", "unresolved_lineages"):
            if type(row[name]) is not int or not 0 <= row[name] <= MAX_RECEIPTS:
                raise ValueError("invalid runtime lineage count")
        if not 1 <= row["resolved_lineages"] + row["unresolved_lineages"] <= MAX_RECEIPTS:
            raise ValueError("runtime context requires bounded recorded experience")
        utility = row["utility"]
        if row["unresolved_lineages"]:
            if utility is not None:
                raise ValueError("unknown lineage utility cannot be zero-imputed")
        elif type(utility) not in (int, float) or not math.isfinite(utility) or not -1 <= utility <= 1:
            raise ValueError("invalid runtime utility")
        expected = "learned" if row["resolved_lineages"] >= 2 and utility is not None and utility > 0 else "common"
        if row["choice"] != expected:
            raise ValueError("runtime choice differs from fixed selection rule")
    _check_digest(selector, "selector_digest")
    if len(canonical(selector).encode()) > MAX_SELECTOR_BYTES:
        raise ValueError("runtime selector byte cap exceeded")
    return deepcopy(selector)


def public_selector(selector):
    """Project a host-validated sidecar to only the data needed for selection.

    The opaque source selector digest binds policy identity.  It is not a
    Target/Oracle output digest and confers no semantic evidence authority.
    """
    selector = validate_selector(selector)
    if selector["schema"] == RUNTIME_SELECTOR_SCHEMA:
        return selector
    projected = dict(schema=RUNTIME_SELECTOR_SCHEMA, algorithm=ALGORITHM,
        algorithm_digest=ALGORITHM_DIGEST, mold_digest=selector["mold_digest"],
        input_contract_digest=selector["input_contract_digest"], final_feedback_allowed=False,
        source_selector_digest=selector["selector_digest"],
        contexts=[dict(context=deepcopy(row["context"]), resolved_lineages=row["resolved_lineages"],
            unresolved_lineages=len(row["lineages"])-row["resolved_lineages"],
            utility=row["utility"], choice=row["choice"]) for row in selector["statistics"]])
    projected["selector_digest"] = digest(projected)
    return validate_runtime_selector(projected)


def _validate_pair_cost(cost):
    keys(cost, ("target_calls", "oracle_calls", "reset_calls", "wall_seconds"))
    for name in ("target_calls", "oracle_calls", "reset_calls"):
        if type(cost[name]) is not int or not 0 <= cost[name] <= 6:
            raise ValueError("invalid paired execution cost")
    seconds = cost["wall_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid paired wall time")


def choose_candidate(selector, context):
    selector = validate_selector(selector)
    context = validate_context(context)
    rows = selector["contexts"] if selector["schema"] == RUNTIME_SELECTOR_SCHEMA else selector["statistics"]
    row = next((item for item in rows if item["context"] == context), None)
    return row["choice"] if row is not None else "common"


def update_selector(selector, receipts, development_manifest):
    """Host-only, idempotent update from complete, validated paired receipts."""
    from .recursive_observe import validate_pair_receipt
    updated = validate_selector(selector)
    if updated["schema"] != SELECTOR_SCHEMA:
        raise ValueError("development updates require the complete host selector, not its worker projection")
    manifest = validate_development_manifest(development_manifest)
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("bounded development receipt batch required")
    lineages = {row["source_lineage_id"]: row for row in manifest["lineages"]}
    existing = {row["reservation_id"]: row for row in updated["evidence"]}
    receipt_ids = {row["pair_receipt_sha256"] for row in updated["evidence"]}
    for receipt in receipts:
        validate_pair_receipt(receipt)
        if receipt["split"] != "development":
            raise PermissionError("final evaluation feedback is forbidden")
        if receipt["experiment_contract_sha256"] != manifest["experiment_contract_sha256"]:
            raise ValueError("paired receipt belongs to a different development contract")
        if receipt["mold_digest"] != updated["mold_digest"]:
            raise ValueError("paired receipt belongs to a different frozen Mold")
        lineage = lineages.get(receipt["source_lineage_id"])
        if lineage is None:
            raise ValueError("unreviewed development lineage")
        for name in ("project_id", "mechanism_id", "input_contract_sha256"):
            if receipt[name] != lineage[name]:
                raise ValueError("paired lineage metadata differs from reviewed manifest")
        for name in ("implementation_sha256", "oracle_sha256"):
            if receipt["identity"][name] != lineage[name]:
                raise ValueError("paired code or Oracle identity differs from reviewed manifest")
        if updated["input_contract_digest"] is not None and receipt["input_contract_sha256"] != updated["input_contract_digest"]:
            raise ValueError("paired input contract differs from selector")
        old = existing.get(receipt["reservation_id"])
        if old is not None:
            if old["pair_receipt_sha256"] != receipt["pair_receipt_sha256"]:
                raise ValueError("reservation was completed with conflicting results")
            continue
        if receipt["pair_receipt_sha256"] in receipt_ids:
            raise ValueError("same paired receipt cannot create new support")
        row = dict(reservation_id=receipt["reservation_id"], pair_receipt_sha256=receipt["pair_receipt_sha256"],
            manifest_digest=manifest["manifest_digest"], source_lineage_id=receipt["source_lineage_id"],
            project_id=lineage["project_id"], mechanism_id=lineage["mechanism_id"],
            independence_id=lineage["independence_id"], implementation_sha256=lineage["implementation_sha256"],
            oracle_sha256=lineage["oracle_sha256"], input_contract_sha256=lineage["input_contract_sha256"],
            evidence_class=manifest["evidence_class"], context=deepcopy(receipt["context"]),
            label=receipt["label"], cost=deepcopy(receipt["cost"]))
        updated["evidence"].append(row)
        existing[row["reservation_id"]] = row; receipt_ids.add(row["pair_receipt_sha256"])
    if len(updated["evidence"]) > MAX_RECEIPTS:
        raise ValueError("selector paired evidence cap exceeded")
    # An idempotent replay must not change even the sidecar digest.
    if len(updated["evidence"]) != len(selector["evidence"]):
        if manifest["manifest_digest"] not in updated["consumed_manifest_digests"]:
            updated["consumed_manifest_digests"].append(manifest["manifest_digest"])
        updated["statistics"] = _statistics(updated["evidence"])
        updated["selector_digest"] = digest({k: v for k, v in updated.items() if k != "selector_digest"})
    return validate_selector(updated)
