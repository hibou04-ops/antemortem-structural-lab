"""Data-only M0 material gate; never invokes a target, Oracle or container."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .harvester_learning import FROZEN_MOLD_DIGEST
from .harvester_review import assess_candidate, development_lineage
from .online_schema import validate_contract
from .schema import digest, keys

INPUT_SCHEMA = "tomolab-m0-readiness-input-v1"


def make_manifest(input_contract: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    value = dict(schema=INPUT_SCHEMA, input_contract=validate_contract(input_contract),
                 mold_digest=FROZEN_MOLD_DIGEST, evidence=deepcopy(evidence))
    value["manifest_digest"] = digest(value)
    return value


def assess_m0_readiness(manifest: dict[str, Any], *, trusted_review: bool = False) -> dict[str, Any]:
    """Revalidate original candidate/review/reproduction chains without promotion.

    A positive result permits preparing the separate preregistration. It is
    neither execution authority nor evidence of utility or generalization.
    """
    if type(trusted_review) is not bool:
        raise ValueError("review authority must be an exact boolean")
    keys(manifest, ("schema", "input_contract", "mold_digest", "evidence", "manifest_digest"))
    if manifest["schema"] != INPUT_SCHEMA or manifest["manifest_digest"] != digest({k: v for k, v in manifest.items() if k != "manifest_digest"}):
        raise ValueError("frozen readiness manifest identity differs")
    contract = validate_contract(manifest["input_contract"])
    evidence = manifest["evidence"]
    if type(evidence) is not list or len(evidence) > 32:
        raise ValueError("bounded explicit evidence denominator required")
    reasons: list[str] = []
    if manifest["mold_digest"] != FROZEN_MOLD_DIGEST:
        reasons.append("FROZEN_ALL_MOLD_IDENTITY_DIFFERS")
    if contract["kind"] != "sequence_int":
        reasons.append("FROZEN_ALL_MOLD_REQUIRES_SEQUENCE_INT")
    if not trusted_review:
        reasons.append("EXPLICIT_ACCOUNTABLE_REVIEW_REQUIRED")
    rows: list[dict[str, Any]] = []
    qualified: list[dict[str, Any]] = []
    seen: set[str] = set()
    implementations: set[str] = set()
    clones: set[str] = set()
    for index, item in enumerate(evidence):
        keys(item, ("candidate", "review", "reproduction"))
        candidate = item["candidate"]
        if type(candidate) is not dict or type(candidate.get("candidate_id")) is not str:
            raise ValueError("original candidate identity required")
        candidate_id = candidate["candidate_id"]
        row: dict[str, Any] = dict(index=index, candidate_id=candidate_id, status="HOLD", reasons=[])
        rows.append(row)
        if candidate_id in seen:
            row["reasons"].append("DUPLICATE_CANDIDATE_ID")
            continue
        seen.add(candidate_id)
        try:
            assessment = assess_candidate(candidate, review=item["review"], execution_receipt=item["reproduction"], trusted_review=trusted_review)
            row.update(status=assessment["status"], reasons=assessment["reasons"], assessment_digest=assessment["sha256"])
            if assessment["status"] == "DEVELOPMENT_ELIGIBLE":
                lineage = development_lineage(candidate, assessment, item["review"])
                implementation = lineage["implementation_sha256"]
                clone = item["review"]["function_identity"]["normalized_ast_clone_sha256"]
                if implementation in implementations or clone in clones:
                    row.update(status="HOLD_DUPLICATE_IMPLEMENTATION", reasons=["IMPLEMENTATION_OR_AST_CLONE_REUSED"])
                    continue
                implementations.add(implementation)
                clones.add(clone)
                row["lineage"] = lineage
                row["common_contract"] = item["review"]["contract"] == contract
                qualified.append(row)
                if not row["common_contract"]:
                    row["reasons"].append("REVIEWED_INPUT_CONTRACT_DIFFERS_FROM_FROZEN_COMMON_CONTRACT")
        except (ValueError, PermissionError, KeyError, TypeError) as error:
            row.update(status="HOLD_INVALID_EVIDENCE", reasons=["EVIDENCE_CHAIN_" + type(error).__name__])
    selected = [row for row in qualified if row["common_contract"]]
    lineages = [row["lineage"] for row in selected]
    counts = dict(evidence_rows=len(evidence), unique_candidates=len(seen), reviewed_reproduced=len(qualified),
        common_contract_candidates=len(selected), independent_units=len({r["independence_id"] for r in lineages}),
        source_lineages=len({r["source_lineage_id"] for r in lineages}), projects=len({r["project_id"] for r in lineages}),
        mechanisms=len({r["mechanism_id"] for r in lineages}))
    if len(evidence) != 4 or len(seen) != 4:
        reasons.append("EXACT_FOUR_DISTINCT_FROZEN_CANDIDATES_REQUIRED")
    if len(selected) != 4:
        reasons.append("FOUR_REVIEWED_REPRODUCED_COMMON_CONTRACT_CANDIDATES_REQUIRED")
    for name, minimum in (("independent_units", 4), ("source_lineages", 4), ("projects", 2), ("mechanisms", 2)):
        if counts[name] < minimum:
            reasons.append("INSUFFICIENT_" + name.upper())
    if any(row["status"] != "DEVELOPMENT_ELIGIBLE" or row["reasons"] for row in rows):
        reasons.append("PRESERVED_ROW_HOLDS_OR_DUPLICATES")
    result = dict(schema="tomolab-m0-readiness-receipt-v1", status="HOLD" if reasons else "READY_FOR_PREREGISTRATION",
        manifest_digest=manifest["manifest_digest"], input_contract_digest=digest(contract), mold_digest=manifest["mold_digest"],
        counts=counts, rows=rows, reasons=sorted(set(reasons)),
        next_gate="ACQUIRE_REVIEWED_COMMON_CONTRACT_INDEPENDENT_MATERIAL" if reasons else "FREEZE_SEPARATE_M0_PREREGISTRATION_AND_EXECUTION_AUTHORITY",
        reset_requirement="ONE_SUCCESSFUL_RESET_BEFORE_EACH_TARGET_AND_ORACLE_ENTRY",
        assessment_only=True, registry_writes=0, target_calls=0, oracle_calls=0, reset_calls=0, network_requests=0,
        execution_authorized=False, m0="HOLD", utility="NOT_ESTABLISHED", oos="NOT_ESTABLISHED",
        independence_scope="ACCOUNTABLE_SEMANTIC_REVIEW_NOT_PROVED_BY_DISTINCT_IDS_OR_HASHES")
    result["sha256"] = digest(result)
    return result
