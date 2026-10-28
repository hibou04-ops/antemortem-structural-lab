"""Producer-neutral, append-only DEVELOPMENT evidence at the reviewed host.

Receipts bind reviewed attestations and original results; JSON hashes cannot
prove that execution happened, that an Oracle is correct, or independence.
Only ``generator_evidence`` crosses the existing minimal evidence boundary.
This module never executes a target, an Oracle, or producer-supplied code.
"""
from copy import deepcopy
import json
import math
import re

from .schema import canonical, decode_inputs, digest, identifier, integer, keys, normalize_evidence, validate_inputs, validate_spec
from .knowledge import KnowledgeArchive, make_observation, validate_provenance

SCHEMA = "tomolab-development-evidence-v1"
REQUIRED = ("record_id", "generation_id", "split", "producer_tool", "producer_version",
            "project", "revision", "function_identity", "implementation_hash",
            "oracle_identity", "oracle_hash", "oracle_validation_receipt",
            "public_spec_hash", "spec", "domain_validity", "input_or_trace",
            "observed_failure_or_refutation", "failure_signature", "replay_status",
            "execution_receipt", "provenance")
OPTIONAL = ("schema", "temporal_contract", "public_ir", "mechanism")
MAX_RECORDS = 16384


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("pinned SHA-256 required")
    return value


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or "\x00" in value:
        raise ValueError("nonempty bounded identity required")
    return value


def normalize_development_record(value):
    """Validate host data shape; quarantine eligibility is evaluated separately.

    Rejected and invalid execution results remain original host data. They are
    never silently converted to normal REFUTATION observations.
    """
    keys(value, REQUIRED, OPTIONAL)
    if len(canonical(value)) > 2_000_000:
        raise ValueError("development record exceeds bound")
    clean = json.loads(canonical(value))
    if clean.get("schema", SCHEMA) != SCHEMA or clean["split"] != "DEVELOPMENT":
        raise ValueError("only the DEVELOPMENT evidence contract is accepted")
    clean["schema"] = SCHEMA
    for field in ("record_id", "generation_id", "failure_signature"):
        identifier(clean[field])
    for field in ("producer_tool", "producer_version", "project", "revision", "function_identity", "oracle_identity"):
        _text(clean[field])
    for field in ("implementation_hash", "oracle_hash", "public_spec_hash"):
        _hash(clean[field])
    clean["spec"] = validate_spec(clean["spec"])
    if digest(clean["spec"]) != clean["public_spec_hash"]:
        raise ValueError("public specification hash mismatch")
    # Fixed fields plus explicitly bounded extension data retain actual results.
    oracle = clean["oracle_validation_receipt"]
    keys(oracle, ("status", "receipt_id", "oracle_hash", "public_spec_hash", "receipt_sha256", "bindings"),
         ("authority", "source_receipt_sha256", "limitations", "comparison_policy"))
    _text(oracle["receipt_id"])
    for field in ("oracle_hash", "public_spec_hash", "receipt_sha256"):
        _hash(oracle[field])
    if (oracle["oracle_hash"], oracle["public_spec_hash"]) != (clean["oracle_hash"], clean["public_spec_hash"]):
        raise ValueError("Oracle validation is bound to a different Oracle or contract")
    domain = clean["domain_validity"]
    keys(domain, ("status", "receipt_sha256", "bindings"), ("reason",))
    _hash(domain["receipt_sha256"])
    outcome = clean["observed_failure_or_refutation"]
    keys(outcome, ("status", "invariant", "category", "actual_result", "oracle_result"), ("reason", "first_failure_index"))
    replay = clean["replay_status"]
    keys(replay, ("status", "deterministic", "matching_observations", "receipt_sha256", "bindings"), ("kind", "observation_refs"))
    integer(replay["matching_observations"], 0, MAX_RECORDS)
    if type(replay["deterministic"]) is not bool:
        raise ValueError("explicit deterministic replay attestation required")
    _hash(replay["receipt_sha256"])
    execution = clean["execution_receipt"]
    keys(execution, ("status", "execution_kind", "target_calls", "oracle_calls", "original_receipt_sha256", "bindings"),
         ("original_receipt_id", "original_target_calls", "original_oracle_calls", "wall_seconds"))
    if execution["execution_kind"] not in ("CACHED_REPLAY", "NEW_EXECUTION"):
        raise ValueError("cached and newly executed evidence must be distinguished")
    for field in ("target_calls", "oracle_calls"):
        integer(execution[field], 0, 10**9)
    for field in ("original_target_calls", "original_oracle_calls"):
        if field in execution:
            integer(execution[field], 0, 10**9)
    if "wall_seconds" in execution:
        wall = execution["wall_seconds"]
        if type(wall) not in (float, int) or not math.isfinite(wall) or wall < 0:
            raise ValueError("finite nonnegative execution time required")
    if execution["execution_kind"] == "CACHED_REPLAY" and (execution["target_calls"] or execution["oracle_calls"]):
        raise ValueError("cached ingestion cannot claim new execution calls")
    _hash(execution["original_receipt_sha256"])
    bindings = dict(implementation_hash=clean["implementation_hash"], oracle_identity=clean["oracle_identity"],
                    oracle_hash=clean["oracle_hash"], public_spec_hash=clean["public_spec_hash"],
                    input_hash=digest(clean["input_or_trace"]), original_receipt_sha256=execution["original_receipt_sha256"])
    for receipt in (oracle, domain, replay, execution):
        if receipt["bindings"] != bindings:
            raise ValueError("receipt is bound to different implementation, Oracle, input, or original execution")
    if "mechanism" in clean:
        mechanism = clean["mechanism"]
        keys(mechanism, ("status", "identity", "review_receipt_sha256"))
        if mechanism["status"] not in ("REVIEWED", "UNKNOWN"):
            raise ValueError("mechanism status must distinguish reviewed identity from UNKNOWN")
        identifier(mechanism["identity"])
        _hash(mechanism["review_receipt_sha256"])
    provenance = clean["provenance"]
    keys(provenance, ("origin", "evidence_origin", "parent_generation_id", "source_file_sha256", "source_record_sha256"),
         ("source_locator", "authority", "limitations"))
    origin = validate_provenance(provenance["origin"])
    if (origin["project"], origin["revision"], origin.get("implementation_sha256"), origin["oracle_id"], origin.get("oracle_sha256")) != (
            clean["project"], clean["revision"], clean["implementation_hash"], clean["oracle_identity"], clean["oracle_hash"]):
        raise ValueError("host identities differ from reviewed provenance")
    _text(provenance["evidence_origin"])
    if provenance["parent_generation_id"] is not None:
        identifier(provenance["parent_generation_id"])
    for field in ("source_file_sha256", "source_record_sha256"):
        _hash(provenance[field])
    # Validate the minimal envelope for eligible results only: malformed or
    # out-of-domain data must be retainable in the quarantine journal.
    if not _quarantine_reasons(clean):
        _minimal(clean)
    return clean


def _quarantine_reasons(record):
    reasons = []
    if record["oracle_validation_receipt"]["status"] != "VALIDATED":
        reasons.append("INVALID_ORACLE")
    if record["domain_validity"]["status"] != "VALID":
        reasons.append("OUT_OF_DOMAIN")
    else:
        try:
            validate_inputs(record["input_or_trace"], record["spec"])
        except ValueError:
            reasons.append("OUT_OF_DOMAIN")
    execution = record["execution_receipt"]
    if execution["status"] != "COMPLETED":
        reasons.append("EXECUTION_ERROR")
    if execution["execution_kind"] == "NEW_EXECUTION" and min(execution["target_calls"], execution["oracle_calls"]) < 1:
        reasons.append("EXECUTION_NOT_VERIFIED")
    if execution["execution_kind"] == "CACHED_REPLAY" and min(execution.get("original_target_calls", 0), execution.get("original_oracle_calls", 0)) < 1:
        reasons.append("EXECUTION_NOT_VERIFIED")
    replay = record["replay_status"]
    if replay["status"] != "REPRODUCED" or not replay["deterministic"] or replay["matching_observations"] < 2:
        reasons.append("REPLAY_NOT_VERIFIED")
    if record["observed_failure_or_refutation"]["status"] not in ("FAILURE", "REFUTATION"):
        reasons.append("INVALID_OBSERVATION")
    if not reasons:
        try:
            _minimal(record)
        except ValueError:
            reasons.append("INVALID_MINIMAL_EVIDENCE")
    return reasons


def _minimal(record):
    outcome = record["observed_failure_or_refutation"]
    event = dict(kind="FAILURE" if outcome["status"] == "FAILURE" else "REFUTATION",
                 evidence_id="dev-" + digest(_semantic_event(record))[:32],
                 inputs=deepcopy(record["input_or_trace"]), invariant=outcome["invariant"],
                 category=outcome["category"], signature=record["failure_signature"])
    if record.get("temporal_contract") is not None:
        from .temporal import normalize_temporal_evidence
        event["first_failure_index"] = outcome.get("first_failure_index")
        return normalize_temporal_evidence(event, record["spec"], record["temporal_contract"])
    return normalize_evidence(event, record["spec"])


def _semantic_event(record):
    # Producer and alias labels are deliberately absent. Roles carry input
    # correspondence; the same implementation cannot gain independence by tool.
    try:
        inputs = decode_inputs(record["input_or_trace"], record["spec"])
    except ValueError:
        inputs = record["input_or_trace"]
    roles = ({item["role"]: inputs.get(item["name"]) for item in record["spec"]["inputs"]}
             if isinstance(inputs, dict) else {"INVALID_INPUT_OR_TRACE": inputs})
    return dict(implementation=record["implementation_hash"], contract=record["spec"]["contract"],
                roles=roles, invariant=record["observed_failure_or_refutation"]["invariant"],
                category=record["observed_failure_or_refutation"]["category"])


def _defect_key(record):
    event = _semantic_event(record)
    event.pop("roles")
    mechanism = record.get("mechanism", {})
    return digest(dict(event, mechanism=mechanism.get("identity") if mechanism.get("status") == "REVIEWED" else "UNKNOWN"))


class DevelopmentEvidenceArchive:
    """Host ledger; append-only snapshots replay rather than trust stored counts.

    ``trusted_host=True`` is an explicit host approval, not a sandbox or proof.
    The ledger retains duplicates and quarantine results with original records.
    """
    def __init__(self, generation_id, *, parent_generation_ids=()):
        self.generation_id = identifier(generation_id)
        self.parent_generation_ids = tuple(identifier(x) for x in parent_generation_ids)
        if self.generation_id in self.parent_generation_ids or len(set(self.parent_generation_ids)) != len(self.parent_generation_ids):
            raise ValueError("distinct parent generations required")
        self._journal, self._records, self._accepted, self._seen = [], {}, {}, {}

    def ingest(self, record, *, trusted_host=False):
        if trusted_host is not True:
            raise PermissionError("reviewed host approval required before ingesting development evidence")
        value = normalize_development_record(record)
        rid = value["record_id"]
        if value["generation_id"] != self.generation_id:
            raise ValueError("record belongs to a different generation")
        parent = value["provenance"]["parent_generation_id"]
        if parent is not None and parent not in self.parent_generation_ids:
            raise ValueError("record parent generation is not declared")
        if rid in self._records:
            if self._records[rid] != value:
                raise ValueError("append-only record ID conflict")
            return deepcopy(next(row["decision"] for row in self._journal if row["record"]["record_id"] == rid))
        if len(self._journal) >= MAX_RECORDS:
            raise ValueError("development ledger record cap exceeded")
        reasons = _quarantine_reasons(value)
        key, defect = digest(_semantic_event(value)), _defect_key(value)
        decision = dict(record_id=rid, status="QUARANTINED" if reasons else "ACCEPTED",
                        reasons=reasons, observation_key=key, mechanism_group_key=defect,
                        independent_implementation_claimed=False)
        if not reasons:
            outcome = value["observed_failure_or_refutation"]
            label = digest(dict(outcome={k: outcome[k] for k in ("status", "actual_result", "oracle_result")},
                                failure_signature=value["failure_signature"],
                                first_failure_index=outcome.get("first_failure_index")))
            if key in self._seen:
                previous = self._seen[key]
                if previous["label"] != label:
                    decision.update(status="QUARANTINED", reasons=["INCONSISTENT_REPLAY"])
                    # Existing accepted data are never erased. A later conflict
                    # makes this semantic key ineligible for every export.
                    previous["conflicted"] = True
                else:
                    decision.update(status="DUPLICATE", duplicate_of=previous["record_id"])
            else:
                self._seen[key] = dict(label=label, record_id=rid, conflicted=False)
                self._accepted[rid] = value
        self._records[rid] = value
        row = dict(record=deepcopy(value), decision=deepcopy(decision), previous_sha256=digest(self._journal[-1]) if self._journal else None)
        self._journal.append(row)
        return deepcopy(decision)

    def accepted_records(self):
        return [deepcopy(value) for value in self._accepted.values()
                if not self._seen[digest(_semantic_event(value))]["conflicted"]]

    def generator_evidence(self, record_id):
        value = self._accepted.get(record_id)
        if value is None or self._seen[digest(_semantic_event(value))]["conflicted"]:
            raise ValueError("only accepted, consistent development evidence may reach a generator")
        return _minimal(value)

    def build_knowledge_archive(self, record_ids=None, *, semantic_policy=None, claim_kinds=None, derived_from=None):
        """Reuse existing bounded learning and observation APIs, without execution.

        Preserve input order: source prefix <=256, then <=256 reviewed same-source
        DEVELOPMENT observations. These extra rows do not become independent
        corroboration. A failure absent from the prefix is never cherry-picked
        out of later rows to seed learning, and excess evidence is never dropped.
        """
        values = self.accepted_records()
        if record_ids is not None:
            requested = set(record_ids)
            values = [value for value in values if value["record_id"] in requested]
            if {value["record_id"] for value in values} != requested:
                raise ValueError("requested source records include ineligible evidence")
        if not values or not any(value["observed_failure_or_refutation"]["status"] == "FAILURE" for value in values):
            raise ValueError("source learning requires at least one accepted actual failure")
        first = values[0]
        scope = lambda value: canonical([value["spec"], value.get("temporal_contract"), value.get("public_ir"), value["provenance"]["origin"]])
        if any(scope(value) != scope(first) for value in values):
            raise ValueError("one source implementation and public contract per archive")
        if semantic_policy is not None or claim_kinds is not None:
            from .claim_semantics import normalize_policy
            policy=normalize_policy(semantic_policy)
            if len(values)>policy["max_events"]:
                raise ValueError("R1 complete source batch exceeds the fixed event capacity; no records were silently discarded")
            return KnowledgeArchive.from_failure_log(first["spec"],
                [self.generator_evidence(value["record_id"]) for value in values],first["provenance"]["origin"],
                temporal_contract=first.get("temporal_contract"),public_ir=first.get("public_ir"),
                semantic_policy=policy,claim_kinds=claim_kinds,derived_from=derived_from)
        if derived_from is not None:
            raise ValueError("new parent reinterpretation requires an explicit R1 semantic policy")
        from .knowledge import MAX_EVENTS
        if len(values) > 2 * MAX_EVENTS:
            raise ValueError("source context exceeds the existing source-plus-observation capacity; no records were silently discarded")
        prefix, remainder = values[:MAX_EVENTS], values[MAX_EVENTS:]
        if not any(value["observed_failure_or_refutation"]["status"] == "FAILURE" for value in prefix):
            raise ValueError("deterministic source prefix has no valid failure; later failures cannot be cherry-picked")
        archive = KnowledgeArchive.from_failure_log(first["spec"], [self.generator_evidence(value["record_id"]) for value in prefix],
                    first["provenance"]["origin"], temporal_contract=first.get("temporal_contract"), public_ir=first.get("public_ir"))
        for value in remainder:
            archive.observe(self.observation(value["record_id"]), trusted_observation=True)
        return archive

    def observation(self, record_id):
        """Existing reviewed observation API; this never establishes independence."""
        event = self.generator_evidence(record_id)
        value = self._accepted[record_id]
        return make_observation(value["spec"], event, value["provenance"]["origin"],
                                temporal_contract=value.get("temporal_contract"), public_ir=value.get("public_ir"))

    def summary(self):
        accepted = self.accepted_records()
        counts = {status: sum(row["decision"]["status"] == status for row in self._journal)
                  for status in ("ACCEPTED", "DUPLICATE", "QUARANTINED")}
        return dict(generation_id=self.generation_id, record_count=len(self._journal), decision_counts=counts,
                    eligible_records=len(accepted), valid_failures=sum(v["observed_failure_or_refutation"]["status"] == "FAILURE" for v in accepted),
                    unique_reviewed_defect_mechanisms=len({_defect_key(v) for v in accepted if v["observed_failure_or_refutation"]["status"] == "FAILURE" and v.get("mechanism", {}).get("status") == "REVIEWED"}),
                    unknown_mechanism_failure_groups=len({_defect_key(v) for v in accepted if v["observed_failure_or_refutation"]["status"] == "FAILURE" and v.get("mechanism", {}).get("status") != "REVIEWED"}),
                    new_target_calls=sum(v["execution_receipt"]["target_calls"] for v in self._records.values()),
                    new_oracle_calls=sum(v["execution_receipt"]["oracle_calls"] for v in self._records.values()),
                    independence="NOT_INFERRED_FROM_PRODUCER_OR_RECEIPT_HASH")

    def snapshot(self):
        value = dict(schema=SCHEMA, generation_id=self.generation_id,
                     parent_generation_ids=list(self.parent_generation_ids), journal=deepcopy(self._journal))
        value["receipt_sha256"] = digest(value)
        return value

    @classmethod
    def from_snapshot(cls, value):
        keys(value, ("schema", "generation_id", "parent_generation_ids", "journal", "receipt_sha256"))
        if value["schema"] != SCHEMA or value["receipt_sha256"] != digest({k: v for k, v in value.items() if k != "receipt_sha256"}):
            raise ValueError("development ledger snapshot integrity mismatch")
        archive = cls(value["generation_id"], parent_generation_ids=value["parent_generation_ids"])
        for row in value["journal"]:
            archive.ingest(row["record"], trusted_host=True)
        if archive.snapshot() != value:
            raise ValueError("development ledger replay mismatch")
        return archive
