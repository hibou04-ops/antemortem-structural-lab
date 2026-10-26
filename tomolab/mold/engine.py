"""Finite CEGIS, disagreement queries and a structural diversity archive.

This module receives typed data only. It never imports a target, opens a file,
accesses a network, or supplies its own truth labels. Surviving predicates are
membership hypotheses within a declared grammar, not causal explanations.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import random
import re

from .schema import (digest, exact_keys, integer, normalize_evidence,
                     point_from_inputs, point_to_inputs, roles, validate_spec)
from .relations import (bounds, holds, relation_id, solve, universe,
                        validate_relation)

SNAPSHOT_SCHEMA = "tomolab-mold-snapshot-v1"


class MoldEngine:
    def __init__(self, spec, *, seed=7, strategy="mold", solver="enumeration"):
        self.spec = validate_spec(spec)
        self.seed = integer(seed, 0, 2**32 - 1, "seed")
        if strategy not in ("mold", "uniform") or solver not in ("enumeration", "z3"):
            raise ValueError("unsupported strategy or solver")
        if solver == "z3":
            try:
                import z3  # noqa: F401 - verify requested backend before any query.
            except ImportError as exc:
                raise ValueError("Z3 backend requires the 'solver' package extra") from exc
        self.strategy, self.solver = strategy, solver
        self.points, relations, masks = universe(bounds(self.spec))
        self._point_index = {p: i for i, p in enumerate(self.points)}
        self._relations = {relation_id(r): dict(r) for r in relations}
        self._masks = dict(zip(self._relations, masks))
        self._remaining = set(self._relations)
        order = list(range(len(self.points)))
        random.Random(seed).shuffle(order)
        self._rank = {i: position for position, i in enumerate(order)}
        self._seen = []
        self._seen_set = set()
        self._evidence = []
        self._evidence_ids = set()
        self._contradictions = []
        self._history = []
        self._prior = None
        self._gate = None
        self.frozen = False
        self.version = 0
        self._inconsistent = False

    def _install_prior(self, relations, gate):
        """Install approved relation syntax, without relabeling source evidence."""
        exact_keys(gate, ("status", "reasons", "mapping", "source_task_id", "source_snapshot_sha256",
                          "evidence", "failure_recurrence", "claim"))
        if gate["status"] not in ("UNKNOWN", "APPLICABLE_FOR_PROBING") or gate["failure_recurrence"] != "UNKNOWN":
            raise ValueError("invalid applicability gate")
        if not isinstance(gate["reasons"], list) or len(gate["reasons"]) > 8 or any(not isinstance(r, str) or len(r) > 160 for r in gate["reasons"]):
            raise ValueError("invalid applicability reasons")
        if gate["status"] == "UNKNOWN" and relations:
            raise ValueError("unknown applicability cannot carry active prior relations")
        if not isinstance(gate["source_snapshot_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", gate["source_snapshot_sha256"]):
            raise ValueError("invalid source snapshot digest")
        if not isinstance(gate["mapping"], dict) or len(gate["mapping"]) != 2:
            raise ValueError("mapping must contain exactly two variable correspondences")
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name)
               for name in list(gate["mapping"]) + list(gate["mapping"].values())):
            raise ValueError("invalid variable mapping")
        clean = [validate_relation(r) for r in relations]
        if len(clean) > 2048 or len({relation_id(r) for r in clean}) != len(clean):
            raise ValueError("invalid prior relation count")
        self._prior = clean
        self._gate = deepcopy(gate)
        self._relations = {relation_id(r): r for r in clean}
        self._masks = {rid: sum(1 << i for i, p in enumerate(self.points) if holds(r, p))
                       for rid, r in self._relations.items()}
        self._remaining = set(self._relations)

    def _cell(self, point):
        a, b, c, d = bounds(self.spec)
        return (min(3, 4 * (point[0] - a) // (b - a + 1)),
                min(3, 4 * (point[1] - c) // (d - c + 1)))

    def _learned(self):
        return bool(self._prior) or any(e["kind"] == "FAILURE" for e in self._evidence)

    def propose(self):
        """Choose one novel point; frozen snapshots may propose but cannot learn."""
        available = [i for i in range(len(self.points)) if i not in self._seen_set]
        if not available:
            raise ValueError("finite domain exhausted")
        rank = self._rank
        candidates = sorted(self._remaining)
        voters = []
        reason = "uniform"
        witness = None
        if self.strategy == "uniform" or not self._learned() or not candidates:
            index = min(available, key=rank.__getitem__)
        elif len(self._seen) % 4 == 3:
            # A fixed one-in-four quota is not adapted to evaluation outcomes.
            occupancy = Counter(self._cell(self.points[i]) for i in self._seen)
            index = min(available, key=lambda i: (occupancy[self._cell(self.points[i])], rank[i]))
            reason = "diversity"
        else:
            counts = {i: sum(bool(self._masks[rid] & (1 << i)) for rid in candidates) for i in available}
            number = len(candidates)
            index = min(available, key=lambda i: (-counts[i] * (number - counts[i]), -counts[i], rank[i]))
            if 0 < counts[index] < number:
                reason = "active-disagreement"
                yes = next(rid for rid in candidates if self._masks[rid] & (1 << index))
                no = next(rid for rid in candidates if not self._masks[rid] & (1 << index))
                voters = [yes, no]
                # Both the finite selector and optional solver check this exact
                # query: a solver witness elsewhere cannot validate this point.
                point = self.points[index]
                singleton = deepcopy(self.spec)
                by_role = roles(singleton)
                for role, value in zip(("left", "right"), point):
                    by_role[role]["low"] = by_role[role]["high"] = value
                witness = solve(singleton, self._relations[yes], self._relations[no], backend=self.solver)
                if witness["status"] != "SAT":
                    raise ValueError("solver did not validate selected disagreement query")
            elif counts[index]:
                reason = "hypothesis-witness"
                voters = [candidates[0]]
            else:
                reason = "unmodeled-exploration"
        self._seen.append(index)
        self._seen_set.add(index)
        return {"inputs": point_to_inputs(self.points[index], self.spec), "reason": reason,
                "hypothesis_ids": voters, "solver_check": witness,
                "sequence": len(self._seen), "frozen": self.frozen}

    def observe(self, evidence):
        if self.frozen:
            raise ValueError("frozen engines reject all feedback")
        if len(self._evidence) >= 2 * len(self.points):
            raise ValueError("evidence exceeds bounded protocol limit")
        event = normalize_evidence(evidence, self.spec)
        index = self._point_index[point_from_inputs(event["inputs"], self.spec)]
        if index not in self._seen_set:
            raise ValueError("feedback must refer to a proposed input")
        if event["evidence_id"] in self._evidence_ids:
            raise ValueError("evidence_id must be unique")
        previous = [e for e in self._evidence if e["inputs"] == event["inputs"]]
        if previous and any(e["kind"] != event["kind"] for e in previous):
            self._inconsistent = True
        label = event["kind"] == "FAILURE"
        eliminated = sorted(rid for rid in self._remaining if bool(self._masks[rid] & (1 << index)) != label)
        if self._inconsistent:
            eliminated = sorted(self._remaining)
        for rid in eliminated:
            self._contradictions.append({"constraint_id": rid, "evidence_id": event["evidence_id"],
                                         "reason": "inconsistent-evidence" if self._inconsistent else "membership-counterexample"})
        self._remaining.difference_update(eliminated)
        self._evidence.append(event)
        self._evidence_ids.add(event["evidence_id"])
        self.version += 1
        self._history.append({"version": self.version, "evidence_id": event["evidence_id"],
                              "eliminated": eliminated, "remaining": len(self._remaining)})
        return {"version": self.version, "eliminated": len(eliminated),
                "remaining": len(self._remaining), "status": self.status}

    @property
    def status(self):
        if self._inconsistent:
            return "INCONSISTENT_EVIDENCE"
        if not self._learned():
            return "NO_FAILURE_EVIDENCE"
        if not self._remaining:
            return "OUT_OF_GRAMMAR"
        return "HYPOTHESES_REMAIN"

    def _constraints(self):
        if not self._learned():
            return []
        families = sorted({self._relations[rid]["family"] for rid in self._remaining})
        evidence_ids = [e["evidence_id"] for e in self._evidence]
        positives = [e["evidence_id"] for e in self._evidence if e["kind"] == "FAILURE"]
        result = []
        for family in families:
            competing = sorted(rid for rid in self._remaining if self._relations[rid]["family"] == family)
            # Quality means specificity among consistent models, not correctness.
            representative = min(competing, key=lambda rid: (self._masks[rid].bit_count(), rid))
            result.append({"constraint_id": representative,
                           "source_evidence": evidence_ids,
                           "applicability_contract": {"operation": self.spec["operation"],
                                                      "invariant": self.spec["invariant"],
                                                      "semantic_contract": self.spec["semantic_contract"],
                                                      "roles": ["left:int", "right:int"]},
                           "typed_structural_relation": deepcopy(self._relations[representative]),
                           "supporting_counterexamples": positives,
                           "contradictions": [c for c in self._contradictions if c["constraint_id"] == representative],
                           "competing_hypotheses": competing,
                           "scope": {"task_id": self.spec["task_id"], "bounds": list(bounds(self.spec)),
                                     "meaning": "candidate failure membership; no causal or universal proof"},
                           "version": self.version,
                           "provenance": {"engine": "finite-cegis-v1", "spec_sha256": digest(self.spec),
                                          "transferred_from": (self._gate or {}).get("source_snapshot_sha256")},
                           "confidence": {"status": "UNCONFIRMED_HYPOTHESIS", "probability": None,
                                          "uncertainty": "unobserved inputs, grammar incompleteness, and transfer recurrence"}})
        return result

    def snapshot(self):
        constraints = self._constraints()
        payload = {"schema": SNAPSHOT_SCHEMA, "spec": deepcopy(self.spec), "seed": self.seed,
                   "strategy": self.strategy, "solver": self.solver, "frozen": self.frozen,
                   "version": self.version, "seen": [point_to_inputs(self.points[i], self.spec) for i in self._seen],
                   "evidence": deepcopy(self._evidence), "prior": deepcopy(self._prior), "gate": deepcopy(self._gate),
                   "status": self.status,
                   "version_space": [{"constraint_id": rid, "relation": deepcopy(self._relations[rid])}
                                     for rid in sorted(self._remaining)],
                   "constraints": constraints,
                   "archive": [{"descriptor": c["typed_structural_relation"]["family"],
                                "constraint_id": c["constraint_id"],
                                "quality": {"bounded_positive_points": self._masks[c["constraint_id"]].bit_count(),
                                            "meaning": "specificity, not correctness"}} for c in constraints],
                   "contradictions": deepcopy(self._contradictions), "history": deepcopy(self._history)}
        payload["receipt"] = {"sha256": digest(payload), "oracle_calls": 0,
                              "claim": "generator receipt; independent oracle evidence is supplied by caller"}
        return payload

    def freeze(self):
        self.frozen = True
        return self.snapshot()

    @classmethod
    def from_snapshot(cls, snapshot):
        required = ("schema", "spec", "seed", "strategy", "solver", "frozen", "version", "seen", "evidence",
                    "prior", "gate", "status", "version_space", "constraints", "archive", "contradictions", "history", "receipt")
        exact_keys(snapshot, required)
        if snapshot["schema"] != SNAPSHOT_SCHEMA or type(snapshot["frozen"]) is not bool:
            raise ValueError("invalid snapshot schema/frozen state")
        integer(snapshot["version"], 0, 8450, "version")
        raw = {k: v for k, v in snapshot.items() if k != "receipt"}
        exact_keys(snapshot["receipt"], ("sha256", "oracle_calls", "claim"))
        if snapshot["receipt"]["sha256"] != digest(raw):
            raise ValueError("snapshot digest mismatch")
        engine = cls(snapshot["spec"], seed=snapshot["seed"], strategy=snapshot["strategy"], solver=snapshot["solver"])
        if snapshot["prior"] is not None:
            if not isinstance(snapshot["prior"], list) or not isinstance(snapshot["gate"], dict):
                raise ValueError("invalid transferred prior")
            engine._install_prior(snapshot["prior"], snapshot["gate"])
        elif snapshot["gate"] is not None:
            raise ValueError("gate without prior")
        if not isinstance(snapshot["seen"], list) or len(snapshot["seen"]) > len(engine.points):
            raise ValueError("invalid proposed inputs")
        for inputs in snapshot["seen"]:
            index = engine._point_index[point_from_inputs(inputs, engine.spec)]
            if index in engine._seen_set:
                raise ValueError("duplicate proposed input")
            engine._seen.append(index)
            engine._seen_set.add(index)
        if not isinstance(snapshot["evidence"], list) or len(snapshot["evidence"]) > 2 * len(engine.points):
            raise ValueError("evidence exceeds bound")
        for evidence in snapshot["evidence"]:
            engine.observe(evidence)
        engine.frozen = snapshot["frozen"]
        if engine.snapshot() != snapshot:
            raise ValueError("derived snapshot state does not match its evidence")
        return engine


def transfer(snapshot, target_spec, mapping=None, *, seed=7, budget=None, solver=None):
    """Check a declared structural correspondence; never assert bug recurrence.

    Frozen source observations stay in their original snapshot. They are not
    recast as target observations. A renamed target gets a frozen probe policy.
    """
    source = MoldEngine.from_snapshot(snapshot)
    if not source.frozen:
        raise ValueError("transfer requires a frozen source snapshot")
    target_spec = validate_spec(target_spec)
    left, right = roles(source.spec), roles(target_spec)
    expected = {left[role]["name"]: right[role]["name"] for role in ("left", "right")}
    mapping = expected if mapping is None else mapping
    reasons = []
    if not isinstance(mapping, dict) or mapping != expected:
        reasons.append("variable mapping must preserve declared roles bijectively")
    for field in ("operation", "invariant", "semantic_contract"):
        if source.spec[field] != target_spec[field]:
            reasons.append(f"{field} differs")
    # Numeric thresholds are reused only inside the learned role-value range.
    # Extending to a larger domain requires additional evidence, not extrapolation.
    for role in ("left", "right"):
        if right[role]["low"] < left[role]["low"] or right[role]["high"] > left[role]["high"]:
            reasons.append(f"{role} target domain extends beyond source scope")
    if not source._learned() or not source._remaining:
        reasons.append("source has no consistent supported hypothesis")
    gate = {"status": "UNKNOWN" if reasons else "APPLICABLE_FOR_PROBING", "reasons": reasons,
            "mapping": deepcopy(mapping), "source_task_id": source.spec["task_id"],
            "source_snapshot_sha256": snapshot["receipt"]["sha256"],
            "evidence": "declared typed operation/invariant/semantic-contract and bounded role correspondence",
            "failure_recurrence": "UNKNOWN", "claim": "applicability permits probing; it does not establish target failures"}
    engine = MoldEngine(target_spec, seed=seed, strategy=source.strategy, solver=solver or source.solver)
    prior = [source._relations[rid] for rid in sorted(source._remaining)] if not reasons else []
    engine._install_prior(prior, gate)
    engine.frozen = True
    candidates = []
    if budget is not None:
        integer(budget, 1, len(engine.points), "budget")
        candidates = [engine.propose() for _ in range(budget)]
    return {"gate": gate, "snapshot": engine.snapshot(), "candidates": candidates}
