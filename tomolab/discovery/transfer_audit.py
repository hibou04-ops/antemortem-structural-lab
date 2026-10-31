"""Bounded retrospective scope audit; never an execution or promotion permit.

This module reuses existing identities, input/receipt validators and the
generation journal. Review hashes bind accountable host evidence; they do not
prove semantic independence. No source, callback, provider or container runs.
"""
from copy import deepcopy
from pathlib import Path

from .evaluation_usage import identity_tokens
from .harvester_execution import validate_reproduction_receipt
from .harvester_review import validate_review_bundle
from .online_schema import input_identity, validate_contract, validate_input
from .recursive_observe import validate_pair_receipt
from .recursive_policy import MAX_RECEIPTS
from .recursive_store import GenerationStore
from .schema import canonical, digest, identifier, keys

SCOPES = ("PAIRED_REMEASUREMENT", "WITHIN_FUNCTION_UNSEEN_INPUT", "CROSS_IMPLEMENTATION_TRANSFER")
MAX_CASES = 64
MAX_INPUTS = 128


def _case_rows(rows):
    if type(rows) is not list or len(rows) > MAX_CASES:
        raise ValueError("at most64 data-only cases per role required")
    found = {}
    for row in rows:
        if type(row) is not dict or type(row.get("identity")) is not dict or type(row.get("contract")) is not dict:
            raise ValueError("data-only case/identity/contract objects required")
        keys(row, ("case_id", "identity", "contract", "inputs"))
        identifier(row["case_id"])
        if row["case_id"] in found:
            raise ValueError("duplicate case ID within one role")
        identity_tokens(row["identity"])
        contract = validate_contract(row["contract"])
        if type(row["inputs"]) is not list or not 1 <= len(row["inputs"]) <= MAX_INPUTS:
            raise ValueError("one to128 bounded typed inputs required per case")
        if any(validate_input(point, contract) is not True for point in row["inputs"]):
            raise ValueError("case input differs from its reviewed type contract")
        # input_identity preserves mapping order, float sign and scalar types.
        if len({input_identity(point) for point in row["inputs"]}) != len(row["inputs"]):
            raise ValueError("duplicate case inputs cannot create independent observations")
        found[row["case_id"]] = deepcopy(row)
    return found


def _point(case, point):
    return (case["identity"]["implementation_sha256"], digest(case["contract"]), input_identity(point))


def _case_bindings(rows):
    return [dict(case_id=case_id, identity=case["identity"], contract_sha256=digest(case["contract"]),
                 input_digests=[input_identity(point) for point in case["inputs"]])
            for case_id, case in sorted(rows.items())]


def _qualification(cases, evidence, trusted_review, holds, blocks):
    valid, witnessed = {}, set()
    if trusted_review is not True:
        holds.add("ACCOUNTABLE_HOST_REVIEW_REQUIRED")
        return valid, witnessed
    if evidence is None:
        evidence = {}
    if type(evidence) is not dict or set(evidence) - set(cases):
        raise ValueError("qualification evidence must map exact declared case IDs")
    for case_id, case in cases.items():
        triple = evidence.get(case_id)
        if type(triple) is not dict or set(triple) != {"candidate", "review", "execution_receipt"}:
            holds.add(case_id + ":QUALIFICATION_EVIDENCE_MISSING")
            continue
        try:
            review = validate_review_bundle(triple["candidate"], triple["review"])
            reproduction = validate_reproduction_receipt(triple["candidate"], review, triple["execution_receipt"])
        except (ValueError, PermissionError, TypeError, KeyError, AttributeError, IndexError):
            holds.add(case_id + ":QUALIFICATION_EVIDENCE_INVALID")
            continue
        if (case["identity"] != review["function_identity"]
                or canonical(case["contract"]) != canonical(review["contract"])):
            blocks.add(case_id + ":DECLARED_CASE_DIFFERS_FROM_REVIEWED_SOURCE_OR_CONTRACT")
            continue
        if reproduction["status"] != "REPRODUCED" or reproduction["unknown_external_call_records"] != 0:
            holds.add(case_id + ":ORACLE_RESET_OCI_REPRODUCTION_NOT_ESTABLISHED")
            continue
        valid[case_id] = review
        # Reproduction witness inputs have already been observed, even though
        # qualification is distinct from selector training/development pooling.
        for branch in ("buggy", "fixed"):
            for repeat in reproduction[branch]:
                for record in repeat.values():
                    if record["status"] == "COMPLETE":
                        witnessed.add(_point(case, record["input"]))
    return valid, witnessed


def _receipt_points(rows, cases, reviews, holds, blocks, *, origin):
    observed, proposed, receipt_ids, reservations = set(), set(), set(), set()
    role_points = {role: set() for role in ("native", "anchor", "common", "learned")}
    for raw in rows:
        try:
            receipt = validate_pair_receipt(raw)
        except (ValueError, PermissionError, TypeError, KeyError, AttributeError, IndexError):
            blocks.add(origin + ":INVALID_PAIRED_RECEIPT")
            continue
        rid, reservation = receipt["pair_receipt_sha256"], receipt["reservation_id"]
        if rid in receipt_ids or reservation in reservations:
            blocks.add(origin + ":DUPLICATE_PAIRED_EXECUTION")
            continue
        receipt_ids.add(rid)
        reservations.add(reservation)
        matching = [case for case in cases.values()
                    if case["identity"]["implementation_sha256"] == receipt["identity"]["implementation_sha256"]
                    and digest(case["contract"]) == receipt["input_contract_sha256"]]
        if not matching:
            holds.add(origin + ":RECEIPT_SOURCE_OR_CONTRACT_NOT_DECLARED")
        lineage_matching = [case for case in matching if case["case_id"] in reviews and all(
            receipt[field] == reviews[case["case_id"]]["lineage"][field]
            for field in ("source_lineage_id", "project_id", "mechanism_id"))]
        if matching and not lineage_matching:
            holds.add(origin + ":PAIRED_REVIEW_BINDING_UNKNOWN")
        for case in lineage_matching:
            review = reviews.get(case["case_id"])
            if review is None:
                holds.add(origin + ":PAIRED_REVIEW_BINDING_UNKNOWN")
                continue
            if (receipt["identity"]["oracle_sha256"] != review["oracle_sha256"]
                    or receipt["identity"]["reset_adapter_sha256"] != review["reset_adapter_sha256"]
                    or receipt["identity"]["purity_review_id"] != review["review_ids"]["reset_review_id"]):
                blocks.add(origin + ":PAIRED_REVIEW_IDENTITY_MISMATCH")
        # Record exposure conservatively even if the missing semantic review
        # prevents qualification. Never erase actual calls on UNKNOWN outcomes.
        for role in role_points:
            point = receipt["reservation"][role + "_input"]
            token = (receipt["identity"]["implementation_sha256"], receipt["input_contract_sha256"], input_identity(point))
            role_points[role].add(token)
            proposed.add(token)
            if role in ("common", "learned") and any(
                    row["target_calls"] > 0 or row["oracle_calls"] > 0 for row in receipt["branches"][role]):
                observed.add(token)
    return dict(observed=observed, proposed=proposed, receipt_ids=receipt_ids, roles=role_points)


def _generation_rows(path, generation_id, holds):
    if path is None or generation_id is None:
        holds.add("FROZEN_GENERATION_HISTORY_UNKNOWN")
        return [], None
    identifier(generation_id)
    if not isinstance(path, (str, Path)):
        raise ValueError("generation_store must be a local journal path")
    path = Path(path)
    if not path.exists():
        holds.add("FROZEN_GENERATION_STORE_MISSING")
        return [], None
    try:
        # The existing reader validates the whole raw chain, including each
        # preserved new receipt. Only the frozen prefix enters this audit.
        records = GenerationStore(path).records()
    except (ValueError, PermissionError, TypeError, KeyError, AttributeError, OSError):
        holds.add("GENERATION_HISTORY_INTEGRITY_UNKNOWN")
        return [], None
    selected = next((i for i, row in enumerate(records) if row["generation"]["generation_id"] == generation_id), None)
    if selected is None:
        holds.add("FROZEN_GENERATION_NOT_FOUND")
        return [], None
    rows = [receipt for row in records[:selected + 1] for receipt in row["generation"]["new_paired_receipts"]]
    if len(rows) > MAX_RECEIPTS:
        raise ValueError("bounded generation receipt prefix required")
    generation = records[selected]["generation"]
    return rows, dict(generation_id=generation_id, generation_digest=generation["sha256"],
                      selector_digest=generation["selector"]["selector_digest"], prefix_records=selected + 1)


def audit_transfer_scope(*, claim_scope, source_cases, evaluation_cases, paired_receipts=(),
                         generation_store=None, generation_id=None, qualification_evidence=None,
                         trusted_review=False):
    """Check a scope against evidence, without making a utility/OOS finding.

    Cases are {case_id, identity, contract, inputs}; inputs describe a pool,
    not execution. qualification_evidence maps case IDs to the existing exact
    {candidate,review,execution_receipt} triple. No caller PASS label is trusted.
    A frozen generation_id is necessary for claims about unseen material.
    Paired receipts prove their own observations, not an OCI/M0 execution link.
    """
    if claim_scope not in SCOPES:
        raise ValueError("explicit supported transfer claim scope required")
    if type(paired_receipts) not in (list, tuple) or len(paired_receipts) > MAX_RECEIPTS:
        raise ValueError("bounded paired receipt sequence required")
    source, evaluation = _case_rows(source_cases), _case_rows(evaluation_cases)
    if len(source) + len(evaluation) > MAX_CASES:
        raise ValueError("at most64 total source/evaluation cases required")
    if len(canonical(dict(source=source, evaluation=evaluation)).encode()) > 4 * 1024 * 1024:
        raise ValueError("bounded data-only scope input required")
    if len(canonical(qualification_evidence).encode()) > 32 * 1024 * 1024:
        raise ValueError("bounded data-only qualification evidence required")
    holds, blocks = set(), set()
    if not source or not evaluation:
        holds.add("NONEMPTY_SOURCE_AND_EVALUATION_CASES_REQUIRED")
    cases = dict(source)
    for case_id, case in evaluation.items():
        if case_id in cases and (case["identity"] != cases[case_id]["identity"] or
                                 canonical(case["contract"]) != canonical(cases[case_id]["contract"])):
            blocks.add("CASE_IDENTITY_CONFLICT_BETWEEN_ROLES")
        cases[case_id] = case
    reviews, witnessed = _qualification(cases, qualification_evidence, trusted_review, holds, blocks)
    selected = _receipt_points(paired_receipts, cases, reviews, holds, blocks, origin="SELECTED")
    history_holds = set()
    raw_consumed, frozen = _generation_rows(generation_store, generation_id, history_holds)
    if claim_scope != "PAIRED_REMEASUREMENT":
        holds.update(history_holds)
    consumed = _receipt_points(raw_consumed, cases, reviews, holds, blocks, origin="LEARNING")
    source_points = {_point(case, point) for case in source.values() for point in case["inputs"]}
    evaluation_points = {_point(case, point) for case in evaluation.values() for point in case["inputs"]}
    pool = source_points | selected["proposed"] | consumed["proposed"]
    pool_overlap = pool & evaluation_points
    selected_overlap = selected["observed"] & evaluation_points
    consumed_overlap = consumed["observed"] & evaluation_points
    witness_overlap = witnessed & evaluation_points
    source_tokens = set().union(*(identity_tokens(case["identity"]) for case in source.values())) if source else set()
    identity_overlap = set().union(*(identity_tokens(case["identity"]) & source_tokens for case in evaluation.values())) if evaluation else set()
    if claim_scope == "CROSS_IMPLEMENTATION_TRANSFER":
        if identity_overlap:
            blocks.add("DEVELOPMENT_POOL_FUNCTION_IDENTITY_EXPOSURE")
        source_units = {reviews[case_id]["lineage"]["independence_id"] for case_id in source if case_id in reviews}
        evaluation_units = {reviews[case_id]["lineage"]["independence_id"] for case_id in evaluation if case_id in reviews}
        if source_units & evaluation_units:
            blocks.add("CROSS_IMPLEMENTATION_LINEAGE_NOT_INDEPENDENT")
        if any(case["identity"]["implementation_sha256"] in {point[0] for point in selected["proposed"] | consumed["proposed"]}
               for case in evaluation.values()):
            blocks.add("SELECTED_OR_LEARNING_FUNCTION_IDENTITY_EXPOSURE")
        if pool_overlap or selected_overlap or consumed_overlap:
            blocks.add("DEVELOPMENT_INPUT_EXPOSURE")
    elif claim_scope == "WITHIN_FUNCTION_UNSEEN_INPUT":
        for case in evaluation.values():
            if not any(case["identity"] == old["identity"] and canonical(case["contract"]) == canonical(old["contract"])
                       for old in source.values()):
                blocks.add("WITHIN_FUNCTION_IDENTITY_OR_CONTRACT_NOT_SHARED")
        for points, reason in ((pool_overlap, "POOL_INPUT_ALREADY_EXPOSED"),
                               (selected_overlap, "SELECTED_INPUT_ALREADY_OBSERVED"),
                               (consumed_overlap, "INPUT_ALREADY_CONSUMED_BY_LEARNING"),
                               (witness_overlap, "QUALIFICATION_WITNESS_ALREADY_OBSERVED")):
            if points:
                blocks.add(reason)
    else:
        source_bound = {(canonical(case["identity"]), digest(case["contract"]), input_identity(point))
                        for case in source.values() for point in case["inputs"]}
        evaluation_bound = {(canonical(case["identity"]), digest(case["contract"]), input_identity(point))
                            for case in evaluation.values() for point in case["inputs"]}
        if source_bound != evaluation_bound:
            blocks.add("PAIRED_REMEASUREMENT_REQUIRES_IDENTICAL_FUNCTION_CONTRACT_AND_INPUTS")
        if not evaluation_points <= selected["observed"] | consumed["observed"] | witnessed:
            holds.add("PAIRED_ACTUAL_OBSERVATION_EVIDENCE_MISSING")
    status = "BLOCK" if blocks else "HOLD" if holds else "PASS"
    report = dict(schema="tomolab-transfer-scope-audit-v1", status=status, requested_scope=claim_scope,
        supported_scope=claim_scope if status == "PASS" else "UNKNOWN" if status == "HOLD" else "NOT_SUPPORTED",
        claim_supported=status == "PASS", reasons=sorted(blocks | holds), blocking_reasons=sorted(blocks), hold_reasons=sorted(holds),
        exposure=dict(pool_cases=len(source), evaluation_cases=len(evaluation), development_pool_points=len(pool),
            selected_observed_points=len(selected["observed"]), selected_receipts=len(selected["receipt_ids"]),
            learning_consumed_points=len(consumed["observed"]) if frozen else None,
            learning_consumed_receipts=len(consumed["receipt_ids"]) if frozen else None,
            qualification_observed_points=len(witnessed),
            selected_proposal_roles={role: len(points) for role, points in selected["roles"].items()},
            overlaps=dict(pool=len(pool_overlap), selected_observed=len(selected_overlap), learning_consumed=len(consumed_overlap),
                          qualification_witness=len(witness_overlap), function_identity_tokens=len(identity_overlap))),
        frozen_generation=frozen, generation_history_status="VALIDATED_FROZEN_PREFIX" if frozen else "UNKNOWN",
        bindings=dict(source_cases_sha256=digest(_case_bindings(source)),
            evaluation_cases_sha256=digest(_case_bindings(evaluation)),
            qualification_evidence_sha256=digest(qualification_evidence),
            selected_paired_receipt_digests=sorted(selected["receipt_ids"]),
            learning_consumed_paired_receipt_digests=sorted(consumed["receipt_ids"]) if frozen else None,
            accountable_review_opt_in=trusted_review is True),
        semantic_independence="ACCOUNTABLE_HOST_REVIEW_BASIS_NOT_PROVED_BY_HASH" if reviews else "UNKNOWN",
        qualified_cases=len(reviews),
        qualified_function_identities=len({canonical(cases[case_id]["identity"]) for case_id in reviews}),
        paired_oci_linkage="NOT_ESTABLISHED_BY_THIS_SCOPE_AUDIT",
        purpose="SCOPE_ELIGIBILITY_ONLY_NOT_EXECUTION_OR_OUTCOME_VERIFICATION",
        authority_scope="PROVIDED_CASES_AND_FROZEN_GENERATION_PREFIX_NOT_GLOBAL_CENSUS",
        execution_authorized=False, promotion_authorized=False, generalization_demonstrated=False,
        transfer_utility="NOT_ESTABLISHED", host_external_code_executed=False, provider_calls=0)
    report["audit_sha256"] = digest(report)
    return report
