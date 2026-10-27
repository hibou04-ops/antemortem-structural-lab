"""Host-only E8 readiness: evidence replay precedes any final measurement.

No target, Oracle, hidden control, or user callback is executed here. Receipts
bind reviewed host attestations; hashes do not prove their real-world truth.
This module is intentionally outside the Generator's module allowlist.
"""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import time
import tomllib

from .schema import canonical, digest, integer, keys, validate_inputs, validate_spec
from .development_evidence import DevelopmentEvidenceArchive
from .evaluation_usage import UsageLedger, identity_tokens, batch_identity_tokens
from .knowledge import KnowledgeArchive, _independent, _scope_reasons, evaluate_claim
from .predicates import predicate_value, validate_predicate

SCHEMA = "tomolab-e8-readiness-v1"
BLOCK = "READINESS_BLOCKED_"
TARGET_FIELDS = ("target_id", "spec", "provenance", "identity", "scope", "evaluation_role", "control_group", "oracle_validation", "controls", "public_guard")


def plan_knowledge(*args, **kwargs):
    # Empty/blocked readiness is available without the optional QA dependency.
    from .knowledge_engine import plan_knowledge as planner
    return planner(*args, **kwargs)


def runtime_versions():
    """Pin the loaded checkout version, or installed distribution when packaged."""
    project = Path(__file__).resolve().parents[2]/"pyproject.toml"
    version = (tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"] if project.is_file()
               else importlib.metadata.version("antemortem-structural-lab"))
    try:
        z3 = importlib.metadata.version("z3-solver")
    except importlib.metadata.PackageNotFoundError:
        z3 = "NOT_INSTALLED"
    return {"python":platform.python_version(), "package":version,
            "hypothesis":importlib.metadata.version("hypothesis"), "z3-solver":z3}


def planning_product_hashes():
    """Bind every package source, including the planner's indirect dependencies."""
    root = Path(__file__).resolve().parents[2]
    paths = [root/"pyproject.toml", *sorted((root/"tomolab").rglob("*.py"))]
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def plans_fingerprint(plans):
    """Semantic plan identity; real timing measurements remain in returned plans."""
    value = deepcopy(plans)
    for row in value:
        if "parent_plan_wall_seconds" in row:
            row["parent_plan_wall_seconds"] = 0.0
        snapshot = row["plan"]["snapshot"]
        for name in snapshot["metrics"]:
            if name.endswith("_seconds"):
                snapshot["metrics"][name] = 0.0
        snapshot["receipt"] = {"sha256":digest({k:v for k,v in snapshot.items() if k != "receipt"})}
    return digest(value)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("pinned SHA-256 required")
    return value


def _diagnostic(code, reasons=(), **detail):
    return {"status":BLOCK+code if reasons else "PASS", "reasons":sorted(set(reasons)), **detail}


class EvaluationReadiness:
    """Capture JSON once; recompute derived state instead of trusting PASS dicts.

    ``authority`` is a fixed host identity, never an output path. The final
    runner must obtain this from trusted configuration, pass the matching
    UsageLedger, then reauthorize this object immediately before atomic START.
    """
    def __init__(self, *, evidence_bundle=None, knowledge_snapshot=None,
                 lineage_review=None, targets=None, fixed_protocol=None,
                 usage_ledger=None, authority=None):
        self._capture_error = None
        try:
            # No external caller may mutate evidence, identities, protocol, or
            # controls between validation and final authorization.
            self._data = json.loads(canonical(dict(evidence_bundle=evidence_bundle,
                knowledge_snapshot=knowledge_snapshot, lineage_review=lineage_review,
                targets=targets, fixed_protocol=fixed_protocol)))
        except (ValueError, TypeError, OverflowError) as error:
            self._data = {}; self._capture_error = type(error).__name__
        self._ledger = usage_ledger
        self._authority = authority if isinstance(authority, str) else None
        self._prepared = []
        self._archive_cache = None
        self._evidence_cache = None
        self._last_validation_metrics = None

    def _evidence_archive(self):
        if self._capture_error:
            raise ValueError("readiness JSON capture failed")
        if self._evidence_cache is None:
            self._evidence_cache = DevelopmentEvidenceArchive.from_snapshot(self._data.get("evidence_bundle"))
        return self._evidence_cache

    def _negative_snapshot(self):
        """Cheap rejection only; captured negative metadata can never grant PASS.

        A large already contradicted development snapshot need not spend minutes
        rebuilding claims merely to refuse final execution. Every accepting path
        still uses KnowledgeArchive.from_snapshot's full semantic replay.
        """
        value = self._data.get("knowledge_snapshot")
        if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
            return None
        receipt = value.get("receipt", {})
        if receipt.get("sha256") != digest({k:v for k,v in value.items() if k != "receipt"}):
            return None
        if receipt.get("authenticity") != "REVIEWED_HOST_ATTESTATION_REQUIRED":
            return None
        return value

    def _archives(self):
        if self._capture_error:
            raise ValueError("readiness JSON capture failed")
        # Captured JSON has no public mutation API. Replayed archives are host
        # internal and never returned. Avoid redoing the bounded journal replay
        # for every check; authorization still rechecks evidence membership,
        # all known counterevidence, lineage, live product and usage history.
        if self._archive_cache is not None:
            return self._archive_cache
        evidence = self._evidence_archive()
        knowledge = KnowledgeArchive.from_snapshot(self._data.get("knowledge_snapshot"))
        self._archive_cache = evidence, knowledge
        return self._archive_cache

    def _lineage(self, records):
        review = self._data.get("lineage_review")
        keys(review, ("status", "development", "consumed_targets", "review_receipt_sha256"))
        if review["status"] != "REVIEWED":
            raise ValueError("reviewed implementation lineage required")
        _sha(review["review_receipt_sha256"])
        if not isinstance(review["development"], list) or not isinstance(review["consumed_targets"], list):
            raise ValueError("individual development and consumed identities required")
        by_id = {}
        all_records = {r["record_id"]:r for r in records}
        for row in review["development"]:
            keys(row, ("record_id", "identity", "lineage", "independence_id", "review_receipt_sha256"))
            identity_tokens(row["identity"]); _sha(row["review_receipt_sha256"])
            rid = row["record_id"]
            if rid in by_id or rid not in all_records:
                raise ValueError("lineage must bind unique accepted development record IDs")
            record = all_records[rid]; origin = record["provenance"]["origin"]
            if (row["identity"]["implementation_sha256"], row["lineage"], row["independence_id"]) != (
                    record["implementation_hash"], origin["lineage"], origin.get("independence_id")):
                raise ValueError("lineage receipt does not bind actual development implementation")
            by_id[rid] = row
        for identity in review["consumed_targets"]:
            identity_tokens(identity)
        return by_id, review["consumed_targets"]

    def _journal_membership(self, evidence, knowledge):
        records = evidence.accepted_records()
        source_events = {}
        observations = {}
        for record in records:
            rid = record["record_id"]
            observations[canonical(evidence.observation(rid))] = rid
            if (canonical(record["spec"]) == canonical(knowledge.spec)
                    and canonical(record.get("temporal_contract")) == canonical(knowledge.temporal_contract)
                    and canonical(record.get("public_ir")) == canonical(knowledge.public_ir)
                    and record["provenance"]["origin"] == knowledge.source):
                source_events[canonical(evidence.generator_evidence(rid))] = rid
        linked, source_linked = set(), set()
        for row in knowledge.snapshot()["journal"]:
            if row["action"] == "learn":
                events = row["evidence"]
            elif row["action"] == "import":
                snapshot = row["snapshot"]
                events = snapshot.get("temporal_evidence", snapshot.get("evidence", []))
            elif row["action"] == "observe":
                token = canonical(row["observation"])
                if token not in observations:
                    raise ValueError("knowledge observation lacks accepted development receipt")
                linked.add(observations[token]); continue
            else:
                continue
            for event in events:
                token = canonical(event)
                if token not in source_events:
                    raise ValueError("knowledge Source event lacks accepted development receipt")
                rid = source_events[token]; linked.add(rid); source_linked.add(rid)
        if not any(r["record_id"] in source_linked and r["observed_failure_or_refutation"]["status"] == "FAILURE" for r in records):
            raise ValueError("no accepted Source failure is present in the actual knowledge journal")
        return records, linked, source_linked

    def _counterevidence(self, evidence, knowledge, claims):
        """Recheck every accepted matching-scope observation, including omitted IDs.

        A subset archive or a different provenance label cannot erase already
        accepted counterevidence. Contract/invariant/family matching preserves
        the existing E7 failure-membership interpretation.
        """
        from .engine import family_of
        contradictions = {}
        for record in evidence.accepted_records():
            origin = record["provenance"]["origin"]
            if record["implementation_hash"] == knowledge.source.get("implementation_sha256"):
                # Relabeling the same code's provenance must not make its known
                # matching-contract counterevidence disappear from the scope.
                origin = {**origin, "semantics":knowledge.source["semantics"]}
            if _scope_reasons(knowledge.spec, knowledge.temporal_contract, knowledge.public_ir, knowledge.source,
                    record["spec"], record.get("temporal_contract"), record.get("public_ir"), origin):
                continue
            event = evidence.generator_evidence(record["record_id"])
            for claim in claims:
                if event["invariant"] != claim["family_id"].split("/", 1)[0]:
                    continue
                predicted = evaluate_claim(claim, event["inputs"], record["spec"],
                    temporal_contract=record.get("temporal_contract"), first_failure_index=event.get("first_failure_index"))
                observed = event["kind"] == "FAILURE" and family_of(event) == claim["family_id"]
                if predicted != observed:
                    contradictions.setdefault(claim["claim_id"], []).append(record["record_id"])
        return contradictions

    @staticmethod
    def _inconsistent_scope_history(evidence, knowledge):
        for row in evidence.snapshot()["journal"]:
            if "INCONSISTENT_REPLAY" not in row["decision"]["reasons"]:
                continue
            record = row["record"]
            origin = record["provenance"]["origin"]
            if record["implementation_hash"] == knowledge.source.get("implementation_sha256"):
                origin = {**origin, "semantics":knowledge.source["semantics"]}
            if not _scope_reasons(knowledge.spec, knowledge.temporal_contract, knowledge.public_ir, knowledge.source,
                    record["spec"], record.get("temporal_contract"), record.get("public_ir"), origin):
                return True
        return False

    def validate_evidence(self):
        try:
            negative = self._negative_snapshot()
            if negative is not None and negative["claims"] and all(
                    c.get("coordinate_only") or c.get("status") == "CONTRADICTED" for c in negative["claims"]):
                evidence = self._evidence_archive()
                failures = [r for r in evidence.accepted_records() if r["provenance"]["origin"] == negative.get("source")
                            and r["observed_failure_or_refutation"]["status"] == "FAILURE"]
                if failures:
                    return _diagnostic("NO_SURVIVING_HYPOTHESIS", ["captured-snapshot-has-no-surviving-structural-candidate"],
                        accepted_source_failures=len(failures), structural_survivors=0,
                        knowledge_journal_replayed=False, diagnosis_scope="NEGATIVE_METADATA_ONLY_NO_AUTHORIZATION")
            evidence, knowledge = self._archives()
            if self._inconsistent_scope_history(evidence, knowledge):
                return _diagnostic("NO_VALID_FAILURE", ["inconsistent-known-scope-development-history-cannot-be-omitted"])
            records, linked, source_linked = self._journal_membership(evidence, knowledge)
            failures = [r for r in records if r["record_id"] in source_linked and r["observed_failure_or_refutation"]["status"] == "FAILURE"]
            if not failures:
                return _diagnostic("NO_VALID_FAILURE", ["accepted-replayed-source-failure-missing"])
            claims = [c for c in knowledge.claims() if not c["coordinate_only"] and c["status"] != "CONTRADICTED"]
            counter = self._counterevidence(evidence, knowledge, claims)
            survivors = [c["claim_id"] for c in claims if c["claim_id"] not in counter]
            if not survivors:
                return _diagnostic("NO_SURVIVING_HYPOTHESIS", ["no-structural-candidate-survives-all-accepted-scope-evidence"],
                    accepted_source_failures=len(failures), structural_survivors=0, omitted_counterevidence=counter)
            if counter:
                return _diagnostic("NO_SURVIVING_HYPOTHESIS", ["snapshot-omits-known-counterevidence"], omitted_counterevidence=counter)
            return _diagnostic("NO_VALID_FAILURE", accepted_source_failures=len(failures),
                linked_development_records=len(linked), structural_survivors=len(survivors))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ImportError) as error:
            return _diagnostic("NO_VALID_FAILURE", ["invalid-or-missing-development-evidence:"+str(error)])

    def validate_corroboration(self):
        try:
            negative = self._negative_snapshot()
            if negative is not None and not any(c.get("independent_contrastive_origins") for c in negative["claims"]):
                return _diagnostic("NO_INDEPENDENT_CORROBORATION", ["captured-snapshot-has-no-independent-contrastive-support"],
                    independently_supported_claim_ids=[], knowledge_journal_replayed=False,
                    diagnosis_scope="NEGATIVE_METADATA_ONLY_NO_AUTHORIZATION")
            evidence, knowledge = self._archives()
            records, linked, _ = self._journal_membership(evidence, knowledge)
            reviews, _ = self._lineage(records)
            source = [r for r in records if r["provenance"]["origin"] == knowledge.source]
            if not source or any(r["record_id"] not in reviews for r in source):
                raise ValueError("Source lineage review is incomplete")
            source_tokens = set().union(*(identity_tokens(reviews[r["record_id"]]["identity"]) for r in source))
            events = {canonical(evidence.observation(r["record_id"])):r for r in records if r["record_id"] in linked}
            actual = [row["observation"] for row in knowledge.snapshot()["journal"] if row["action"] == "observe"]
            qualified = []
            counter = self._counterevidence(evidence, knowledge, [c for c in knowledge.claims() if c["status"] == "SUPPORTED_WITHIN_SCOPE"])
            for claim in knowledge.claims():
                if claim["coordinate_only"] or claim["status"] != "SUPPORTED_WITHIN_SCOPE" or claim["claim_id"] in counter:
                    continue
                grouped = {}
                for observation in actual:
                    receipt = observation["receipt_sha256"]
                    positive = receipt in claim["independent_positive"]
                    negative = receipt in claim["independent_negative"]
                    if not positive and not negative:
                        continue
                    record = events.get(canonical(observation))
                    if record is None or record["record_id"] not in reviews:
                        continue
                    reviewed = reviews[record["record_id"]]
                    if identity_tokens(reviewed["identity"]) & source_tokens:
                        continue
                    if not _independent(knowledge.source, observation["origin"], observation["implementation_sha256"]):
                        continue
                    # Both labels must bind the identical reviewed implementation,
                    # Oracle, lineage, and original E7 origin, not a mixed pair.
                    group = digest([observation["origin"], reviewed["identity"]])
                    grouped.setdefault(group, set()).add("positive" if positive else "negative")
                if any(labels == {"positive", "negative"} for labels in grouped.values()):
                    qualified.append(claim["claim_id"])
            return _diagnostic("NO_INDEPENDENT_CORROBORATION", [] if qualified else ["same-reviewed-independent-implementation-and-oracle-positive-negative-support-missing"],
                independently_supported_claim_ids=qualified)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ImportError) as error:
            return _diagnostic("NO_INDEPENDENT_CORROBORATION", ["invalid-corroboration:"+str(error)])

    def _target(self, target):
        from .knowledge import validate_provenance
        keys(target, TARGET_FIELDS, ("temporal_contract", "public_ir", "classification"))
        if not isinstance(target["target_id"], str) or not target["target_id"]:
            raise ValueError("target ID required")
        validate_spec(target["spec"]); validate_provenance(target["provenance"])
        identity_tokens(target["identity"])
        if target["identity"]["implementation_sha256"] != target["provenance"].get("implementation_sha256"):
            raise ValueError("target implementation differs from its reviewed identity")
        if target["scope"] not in ("REVIEWED_REAL_PROJECT", "AUTHORED_FUNCTIONAL_FIXTURE"):
            raise ValueError("explicit real-project or functional-fixture scope required")
        if target["evaluation_role"] not in ("POSITIVE_REPRODUCTION", "CLEAN_CONTROL"):
            raise ValueError("explicit reproduction or clean control role required")
        if target["control_group"] is not None and (not isinstance(target["control_group"], str) or not target["control_group"]):
            raise ValueError("explicit paired control group or null required")
        if "classification" in target and target["classification"] not in ("HISTORICAL_DEFECT_REDISCOVERY", "AUTHORED_FUNCTIONAL_FIXTURE"):
            raise ValueError("supported evaluation classification required")
        if target["scope"] == "REVIEWED_REAL_PROJECT" and target.get("classification") != "HISTORICAL_DEFECT_REDISCOVERY":
            raise ValueError("reviewed reproduction must identify historical defect rediscovery")
        identity_hash, spec_hash = digest(target["identity"]), digest(target["spec"])
        oracle_hash = target["provenance"].get("oracle_sha256")
        _sha(oracle_hash)
        oracle = target["oracle_validation"]
        keys(oracle, ("status", "target_identity_sha256", "public_spec_hash", "oracle_sha256", "receipt_sha256"))
        control = target["controls"]
        keys(control, ("status", "scope", "target_identity_sha256", "public_spec_hash", "oracle_sha256",
                       "known_positive_receipt_sha256", "clean_control_receipt_sha256"))
        for receipt in (oracle, control):
            if receipt["status"] != "VALIDATED" or (receipt["target_identity_sha256"], receipt["public_spec_hash"], receipt["oracle_sha256"]) != (identity_hash, spec_hash, oracle_hash):
                raise ValueError("ORACLE: independent validation/control is missing or bound to different target/spec/oracle")
        if control["scope"] != target["scope"]:
            raise ValueError("ORACLE: authored controls cannot stand in for reviewed real-project controls")
        _sha(oracle["receipt_sha256"])
        for field in ("known_positive_receipt_sha256", "clean_control_receipt_sha256"):
            if control[field] is not None:
                _sha(control[field])
        required_control = "known_positive_receipt_sha256" if target["evaluation_role"] == "POSITIVE_REPRODUCTION" else "clean_control_receipt_sha256"
        _sha(control[required_control])
        if control["known_positive_receipt_sha256"] is not None and control["known_positive_receipt_sha256"] == control["clean_control_receipt_sha256"]:
            raise ValueError("ORACLE: distinct positive and clean control receipts required")
        guard = target["public_guard"]
        keys(guard, ("kind", "predicates"))
        if guard["kind"] not in ("DECLARED_SPEC", "REVIEWED_PREDICATE") or not isinstance(guard["predicates"], list):
            raise ValueError("bounded reviewed public guard required")
        if len(guard["predicates"]) > 16 or (guard["kind"] == "DECLARED_SPEC" and guard["predicates"]):
            raise ValueError("invalid public guard predicate list")
        for predicate in guard["predicates"]:
            validate_predicate(predicate, target["spec"])
        return target

    def validate_target_contracts(self):
        try:
            targets = self._data.get("targets")
            if not isinstance(targets, list) or not targets:
                raise ValueError("no independently reviewed applicable final Target")
            evidence, knowledge = self._archives()
            records = evidence.accepted_records()
            reviews, consumed = self._lineage(records)
            if any(r["record_id"] not in reviews for r in records):
                raise ValueError("all accepted development identities must be reviewed before final use")
            forbidden = set()
            for row in reviews.values():
                forbidden.update(identity_tokens(row["identity"]))
            for identity in consumed:
                forbidden.update(identity_tokens(identity))
            if not isinstance(self._ledger, UsageLedger) or self._ledger.authority_id != self._authority:
                raise ValueError("fixed host usage authority is missing or changed")
            forbidden.update(self._ledger.inspect()["consumed_tokens"])
            roles = {t.get("evaluation_role") for t in targets}
            if roles != {"POSITIVE_REPRODUCTION", "CLEAN_CONTROL"}:
                raise ValueError("actual final batch requires both positive reproduction and clean control targets")
            batch_identity_tokens(targets)
            ids, applicable = set(), []
            corroboration = self.validate_corroboration()
            allowed_claims = set(corroboration.get("independently_supported_claim_ids", []))
            for row in targets:
                target = self._target(row)
                if target["target_id"] in ids:
                    raise ValueError("duplicate target ID")
                ids.add(target["target_id"])
                current = identity_tokens(target["identity"])
                if current & forbidden:
                    raise ValueError("target identity overlaps Source/Corroboration/consumed final identity")
                gate = knowledge.qualify(target["spec"], target_provenance=target["provenance"],
                    temporal_contract=target.get("temporal_contract"), public_ir=target.get("public_ir"))
                if gate["target_seen_in_development"]:
                    raise ValueError("target was already observed in development")
                gate_claims = {c["claim_id"] for c in gate["claims"]}
                if not (gate_claims & allowed_claims):
                    raise ValueError("no independently supported claim applies to target contract")
                if gate_claims - allowed_claims:
                    raise ValueError("target planner would consume claims without reviewed independent corroboration")
                applicable.append(target["target_id"])
            return _diagnostic("NO_APPLICABLE_TARGET", applicable_target_ids=applicable,
                scopes=sorted({t["scope"] for t in targets}))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, ImportError) as error:
            message = str(error)
            return _diagnostic("ORACLE" if "ORACLE:" in message else "NO_APPLICABLE_TARGET", ["invalid-target-contract:"+message])

    def _protocol(self):
        protocol = self._data.get("fixed_protocol")
        required = ("schema", "methods", "seeds", "budget", "pool_size", "guidance_budget", "product_hashes",
                    "versions", "metrics", "splits", "nonadaptive", "final_feedback_allowed", "authority_id", "protocol_revision", "comparison_policy")
        keys(protocol, required, ("decision_rules", "evaluator_mapping_sha256"))
        if "evaluator_mapping_sha256" in protocol:
            _sha(protocol["evaluator_mapping_sha256"])
        if protocol["schema"] != "tomolab-e8-fixed-protocol-v1" or protocol["methods"] != ["A", "B", "C", "D"]:
            raise ValueError("fixed A-D comparison protocol required")
        if protocol["nonadaptive"] is not True or protocol["final_feedback_allowed"] is not False:
            raise ValueError("nonadaptive information boundary required")
        if protocol["splits"] != {"source":"DEVELOPMENT", "corroboration":"DEVELOPMENT", "target":"FINAL"}:
            raise ValueError("fixed S/C/T splits required")
        policy = protocol["comparison_policy"]
        keys(policy, ("kind", "absolute_tolerance", "relative_tolerance", "undefined", "exceptions"))
        if policy["kind"] != "FINITE_JSON" or policy["undefined"] != "EXECUTION_ERROR" or policy["exceptions"] != "EXECUTION_ERROR":
            raise ValueError("fixed finite JSON outcome/error policy required")
        for field in ("absolute_tolerance", "relative_tolerance"):
            value = policy[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("finite nonnegative outcome tolerances required")
        if "decision_rules" in protocol:
            rules = protocol["decision_rules"]
            keys(rules, ("max_reuse_cost_ratio", "max_extra_discovery_cost_ratio", "source_costs"))
            costs = rules["source_costs"]
            keys(costs, ("S_seconds", "C_seconds", "archive_seconds", "receipt_sha256"))
            _sha(costs["receipt_sha256"])
            for value in [rules["max_reuse_cost_ratio"], rules["max_extra_discovery_cost_ratio"],
                          costs["S_seconds"], costs["C_seconds"], costs["archive_seconds"]]:
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("decision thresholds and measured Source/C/archive costs require finite nonnegative values")
        if protocol["authority_id"] != self._authority:
            raise ValueError("fixed usage authority differs from protocol")
        _sha(protocol["authority_id"])
        seeds = protocol["seeds"]
        if not isinstance(seeds, list) or not seeds or len(seeds) > 32 or len(set(seeds)) != len(seeds):
            raise ValueError("bounded unique preregistered seeds required")
        for seed in seeds:
            integer(seed, 0, 2**32-1)
        integer(protocol["budget"], 1, 4096); integer(protocol["pool_size"], 1, 4096)
        integer(protocol["guidance_budget"], 1, protocol["budget"]//2)
        if not protocol["metrics"] or not isinstance(protocol["metrics"], list) or not protocol["protocol_revision"]:
            raise ValueError("fixed metrics and protocol revision required")
        versions = protocol["versions"]
        if not isinstance(versions, dict) or not versions or any(not isinstance(v, str) or not v for v in versions.values()):
            raise ValueError("pinned runtime versions required")
        current = runtime_versions()
        if versions != current:
            raise ValueError("pinned runtime versions differ")
        root = Path(__file__).resolve().parents[2]
        hashes = protocol["product_hashes"]
        mandatory = set(planning_product_hashes())
        if not isinstance(hashes, dict) or not mandatory <= set(hashes):
            raise ValueError("complete readiness and planning product bindings required")
        for name, expected in hashes.items():
            _sha(expected); path = (root/name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("frozen product changed:"+name)
        return protocol

    @staticmethod
    def _accepted_plan(plan, target):
        accepted, seen = [], set()
        for row in plan["candidates"]:
            point = validate_inputs(row["inputs"], target["spec"])
            if not all(predicate_value(p, point, target["spec"]) is True for p in target["public_guard"]["predicates"]):
                continue
            token = canonical(point)
            if token in seen:
                continue
            seen.add(token); accepted.append(row)
        return accepted

    def validate_guidance(self):
        self._prepared = []
        try:
            evidence_check = self.validate_evidence()
            target_check = self.validate_target_contracts()
            if evidence_check["status"] != "PASS" or target_check["status"] != "PASS":
                raise ValueError("evidence/corroboration/target preconditions did not pass")
            _, knowledge = self._archives(); protocol = self._protocol()
            effective, prepared = [], []
            for target in self._data["targets"]:
                claims = {c["claim_id"]:c for c in knowledge.qualify(target["spec"], target_provenance=target["provenance"],
                    temporal_contract=target.get("temporal_contract"), public_ir=target.get("public_ir"))["claims"]}
                for seed in protocol["seeds"]:
                    settings = dict(target_provenance=target["provenance"], temporal_contract=target.get("temporal_contract"),
                        public_ir=target.get("public_ir"), seed=seed, budget=protocol["budget"],
                        pool_size=protocol["pool_size"], guidance_budget=protocol["guidance_budget"])
                    tick = time.perf_counter()
                    empty = plan_knowledge(None, target["spec"], **settings)
                    empty_wall = time.perf_counter()-tick
                    tick = time.perf_counter()
                    qualified = plan_knowledge(knowledge.snapshot(), target["spec"], **settings)
                    qualified_wall = time.perf_counter()-tick
                    left, right = self._accepted_plan(empty, target), self._accepted_plan(qualified, target)
                    a, b = [canonical(r["inputs"]) for r in left], [canonical(r["inputs"]) for r in right]
                    changed = []
                    for index, row in enumerate(right):
                        if index < len(a) and a[index] == b[index]:
                            continue
                        consumed = [cid for cid in row["claim_ids"] if cid in claims and evaluate_claim(claims[cid], row["inputs"], target["spec"], temporal_contract=target.get("temporal_contract"))]
                        if row["source"].startswith("QUALIFIED_") and consumed:
                            changed.append({"position":index, "claim_ids":consumed})
                    if a == b or not changed or not left or not right:
                        raise ValueError("empty/duplicate/rejected/fallback-only/or-identical-input-order-guidance:"+target["target_id"])
                    for method, plan, wall in (("B", empty, empty_wall), ("C", qualified, qualified_wall)):
                        if plan["oracle_calls"] or plan["target_calls"] or plan["final_feedback_allowed"] is not False:
                            raise ValueError("planning violated final information boundary")
                        prepared.append({"target_id":target["target_id"], "seed":seed, "method":method, "plan":plan,
                                         "parent_plan_wall_seconds":wall})
                    effective.append({"target_id":target["target_id"], "seed":seed, "changed_qualified_positions":changed,
                                      "B_unique_valid_inputs":len(left), "C_unique_valid_inputs":len(right)})
            fingerprint = plans_fingerprint(prepared)
            self._prepared = prepared
            return _diagnostic("NO_EFFECTIVE_GUIDANCE", effective_guidance=effective,
                plans_sha256=fingerprint, target_calls=0, oracle_calls=0)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, ImportError) as error:
            self._prepared = []
            return _diagnostic("NO_EFFECTIVE_GUIDANCE", ["invalid-or-ineffective-guidance:"+str(error)], target_calls=0, oracle_calls=0)

    def get_prepared_plans(self):
        """Only plans produced by successful live validation are returned."""
        return deepcopy(self._prepared)

    def get_execution_context(self):
        """Host runner access only; never send this evidence bundle to Generator."""
        return deepcopy(self._data)

    def get_usage_ledger(self):
        """The runner uses this fixed host handle, never a caller output alias."""
        return self._ledger

    def get_validation_metrics(self):
        """Actual outer validation wall time, separate from semantic authority."""
        return deepcopy(self._last_validation_metrics)

    def authorize_final_comparison(self):
        started = time.perf_counter()
        checks = {"evidence":self.validate_evidence(), "corroboration":self.validate_corroboration(),
                  "targets":self.validate_target_contracts(), "guidance":self.validate_guidance()}
        blockers = sorted({row["status"] for row in checks.values() if row["status"] != "PASS"})
        bindings = {"captured_inputs_sha256":digest(self._data), "authority_id":self._authority,
                    "prepared_plans_sha256":plans_fingerprint(self._prepared), "target_calls":0, "oracle_calls":0,
                    "attestation_scope":"REVIEWED_HOST_ATTESTATION_NOT_TRUTH_OR_INDEPENDENCE_PROOF"}
        if not blockers:
            try:
                protocol = self._protocol()
                bindings.update(protocol_sha256=digest(protocol), product_hashes=protocol["product_hashes"],
                    usage_history_sha256=digest(self._ledger.inspect()), evidence_sha256=self._data["evidence_bundle"]["receipt_sha256"],
                    archive_sha256=self._data["knowledge_snapshot"]["receipt"]["sha256"],
                    target_identities_sha256=digest([t["identity"] for t in self._data["targets"]]))
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
                blockers.append(BLOCK+"NO_EFFECTIVE_GUIDANCE")
                checks["authorization"] = {"status":BLOCK+"NO_EFFECTIVE_GUIDANCE", "reasons":[str(error)]}
        result = {"schema":SCHEMA, "status":"NOT_EXECUTED_READINESS_BLOCKED" if blockers else "PASS",
                  "blockers":blockers, "checks":checks, "bindings":bindings,
                  "final_execution_started":False}
        result["receipt_sha256"] = digest(result)
        self._last_validation_metrics = {"readiness_validation_wall_seconds":time.perf_counter()-started,
            "cost_scope":"NON_ADDITIVE_INCLUDES_EVIDENCE_CORROBORATION_TARGET_GATING_AND_PLAN_GENERATION",
            "target_calls":0, "oracle_calls":0}
        return result
