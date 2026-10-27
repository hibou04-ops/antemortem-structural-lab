"""Stateful relations in E5's actual shared Version Space and active selector."""
from copy import deepcopy
import math
import time

from .engine import DiscoveryEngine
from .schema import canonical, digest, identifier, integer, keys, validate_inputs
from .temporal import (normalize_temporal_evidence, simulate_trace, temporal_holds,
                       temporal_hypotheses, trace_layout, validate_temporal_contract)
from .predicates import predicate_roles
from .features import grammar, holds, measurements

SNAPSHOT_SCHEMA = "tomolab-temporal-snapshot-v1"


class TemporalEngine(DiscoveryEngine):
    """Reuse E5 masks, groups, counterexample elimination, history and selection.

    The temporal grammar is lazy: no stateful hypothesis work before a checked
    failure or a qualified frozen prior. Static/AST and temporal terms inhabit
    the same groups and undergo the same deterministic elimination loop.
    """
    def __init__(self, spec, temporal_contract, *, budget=64, seed=7, pool_size=128,
                 strategy="integrated", candidate_pool=None, public_ir=None):
        pool_started = time.perf_counter()
        pool_seconds = 0.0
        self.temporal_contract = validate_temporal_contract(temporal_contract, spec)
        self.budget = integer(budget, 1, 4096)
        integer(pool_size, 1, 4096)
        self.lazy_pool = candidate_pool is None
        if candidate_pool is None:
            name, _, _ = trace_layout(spec)
            if spec["inputs"][0]["type"]["min_size"] == 0:
                candidate_pool = [{name: []}]
            else:
                # A nonempty minimum genuinely requires one feasible model
                # prefix; do not precompute a fixed search pool in cold init.
                from .efficient import generate_temporal_pool
                generation_started = time.perf_counter()
                candidate_pool = generate_temporal_pool(spec, self.temporal_contract, seed=seed, size=1)
                pool_seconds = time.perf_counter()-generation_started
        if isinstance(candidate_pool, dict):
            candidate_pool = candidate_pool["candidates"]
        if not isinstance(candidate_pool, list) or not candidate_pool:
            raise ValueError("valid native temporal candidate pool required")
        for point in candidate_pool:
            if not simulate_trace(point, spec, self.temporal_contract)["valid"]:
                raise ValueError("initial candidate violates public state preconditions")
        super().__init__(spec, seed=seed, strategy=strategy, pool_size=pool_size,
                         public_ir=public_ir, native_strategy=False, _pool=candidate_pool)
        self.temporal_relations = set()
        self.temporal_evidence = []
        self.temporal_prior = None
        self.temporal_gate = None
        self.temporal_metrics = {"activation_count": 0, "guided_rounds": 0,
                                 "fresh_candidates": 0, "guided_queries": 0,
                                 "native_queries": 0, "feedback_records": 0,
                                 "pool_generation_seconds": pool_seconds,
                                 "version_update_seconds": time.perf_counter()-pool_started-pool_seconds, "solver_seconds": 0.0,
                                 "selection_seconds": 0.0, "solver_calls": 0, "solver_sat": 0}
        self.proposal_history = []
        replay_started = time.perf_counter()
        self._replays = {canonical(point): simulate_trace(point, self.spec, self.temporal_contract) for point in self.pool}
        self.temporal_metrics["version_update_seconds"] += time.perf_counter()-replay_started
        self._guidance_version = None
        self._argument_solver = None
        self._solver_version = None
        self.activation_pool_size = None
        self._restoring = False
        self._native_expanded = False

    def _extend_native_pool(self, source, size):
        from .efficient import generate_temporal_pool
        started = time.perf_counter()
        generated = generate_temporal_pool(self.spec, self.temporal_contract,
            seed=self.seed, size=size, excluded=self.pool)
        self.temporal_metrics["pool_generation_seconds"] += time.perf_counter()-started
        for point in generated:
            self._append_candidate(point, source)
        self.temporal_metrics["fresh_candidates"] = len(self.pool_events)

    def _activate_temporal(self):
        if self.temporal_relations:
            return
        started = time.perf_counter()
        pool_before = self.temporal_metrics["pool_generation_seconds"]
        if self.lazy_pool:
            if not self._restoring:
                if not self._native_expanded:
                    self._extend_native_pool("TEMPORAL_LAZY_ACTIVATION", self.pool_size)
                    self._native_expanded = True
                self.activation_pool_size = len(self.pool)
            cutoff = self.activation_pool_size
            integer(cutoff, 1, len(self.pool))
            # A one-seed cold grammar must not erase static relations. Compile
            # once from actual observed prefixes plus the qualified native
            # pool; E5 observe then rechecks every earlier refutation.
            measured, relations, masks = grammar(self.pool[:cutoff], self.spec, self.predicates)
            measured.extend(measurements(point, self.spec, self.predicates) for point in self.pool[cutoff:])
            for rid, relation in relations.items():
                for index in range(cutoff, len(self.pool)):
                    if holds(relation, measured[index]):
                        masks[rid] |= 1 << index
            self.measured, self.relations, self.masks = measured, relations, masks
        relations = temporal_hypotheses(self.temporal_contract, self.spec)
        for rid, relation in relations.items():
            self.relations[rid] = relation
            self.masks[rid] = sum(1 << i for i, point in enumerate(self.pool)
                                  if temporal_holds(relation, self._replays[canonical(point)]))
        self.temporal_relations = set(relations)
        for group in self.groups.values():
            group["remaining"].update(relations)
        self.temporal_metrics["activation_count"] += 1
        self.temporal_metrics["version_update_seconds"] += max(0.0, time.perf_counter()-started
            -(self.temporal_metrics["pool_generation_seconds"]-pool_before))

    def _append_candidate(self, point, source):
        # E5's method owns input deduplication, static masks and pool history.
        point = validate_inputs(point, self.spec)
        replay = simulate_trace(point, self.spec, self.temporal_contract)
        if not replay["valid"]:
            return None
        key = canonical(point)
        if key in self._index:
            return self._index[key]
        # E5 holds() handles static terms; temporal terms use approved trace IR.
        temporal = {rid: self.relations.pop(rid) for rid in self.temporal_relations}
        try:
            index = super()._append_candidate(point, source)
        finally:
            self.relations.update(temporal)
        if index is not None:
            self._replays[key] = replay
            for rid, relation in temporal.items():
                if temporal_holds(relation, replay):
                    self.masks[rid] |= 1 << index
        return index

    def _candidate_ids(self):
        raw = super()._candidate_ids()
        if not getattr(self, "temporal_relations", None):
            return raw
        # Preserve all explanations/provenance, but give equivalent truth
        # columns one active vote and prefer their temporal description.
        eligible = sorted({rid for group in self.groups.values() for rid in group["remaining"]})
        ordered = [rid for rid in eligible if rid in self.temporal_relations] + raw
        columns, result = set(), []
        for rid in ordered:
            if self.masks[rid] not in columns:
                result.append(rid); columns.add(self.masks[rid])
        return result

    def _qualified(self):
        if self.inconsistent or self.strategy != "integrated":
            return False
        active = [rid for rid in self._candidate_ids() if rid in self.temporal_relations]
        available = [i for i in range(len(self.pool)) if i not in self._seen]
        return len(active) >= 2 and any(0 < sum(bool(self.masks[r] & (1 << i)) for r in active) < len(active)
                                         for i in available)

    def propose(self):
        selection_started = time.perf_counter()
        previous_solver_seconds = self.temporal_metrics["solver_seconds"]
        previous_pool_seconds = self.temporal_metrics["pool_generation_seconds"]
        if len(self.seen) >= self.budget:
            raise ValueError("temporal candidate budget exhausted")
        if (self.lazy_pool and not self._native_expanded and not self.temporal_relations
                and (not any(i not in self._seen for i in range(len(self.pool))) or (self.frozen and not self.seen))):
            self._extend_native_pool("NATIVE_LAZY_QUERY", self.pool_size)
            self._native_expanded = True
        qualified = self._qualified()
        solver_choice, solver_check = self._argument_witness() if qualified else (None, None)
        if (qualified and solver_choice is None and self._guidance_version != self.version and len(self.pool) < 4096
                and sum(i not in self._seen for i in range(len(self.pool))) <= 4):
            from .efficient import generate_temporal_pool
            relations = [self.relations[r] for r in self._candidate_ids() if r in self.temporal_relations][:16]
            generation_started = time.perf_counter()
            generated = generate_temporal_pool(self.spec, self.temporal_contract,
                seed=(self.seed + self.version * 7919) % 2**32, size=min(8, 4096-len(self.pool)),
                relations=relations, excluded=self.pool)
            self.temporal_metrics["pool_generation_seconds"] += time.perf_counter()-generation_started
            if isinstance(generated, dict):
                generated = generated["candidates"]
            for point in generated:
                before = len(self.pool)
                self._append_candidate(point, "TEMPORAL_NATIVE_DISAGREEMENT")
                self.temporal_metrics["fresh_candidates"] += len(self.pool)-before
            self.temporal_metrics["guided_rounds"] += 1
            self._guidance_version = self.version
        original = self.strategy
        if not qualified:
            self.strategy = "hypothesis"
        try:
            if solver_choice is None:
                try:
                    proposal = super().propose()
                except ValueError as error:
                    if str(error) != "Hypothesis candidate pool exhausted":
                        raise
                    proposal = None
            else:
                self.seen.append(solver_choice); self._seen.add(solver_choice)
                ids = self._candidate_ids()
                predicts = [rid for rid in ids if self.masks[rid] & (1 << solver_choice)]
                proposal = {"inputs": deepcopy(self.pool[solver_choice]), "reason": "incremental-temporal-witness",
                    "objective": "hypothesis-identification", "predicted_constraints": predicts[:32],
                    "competing_count": len(ids), "hypothesis_ids": ids[:32], "solver_check": solver_check,
                    "declared_oracle_cost": 1, "positive_votes": len(predicts), "sequence": len(self.seen), "frozen": self.frozen}
        finally:
            self.strategy = original
        if proposal is None:
            self.temporal_metrics["selection_seconds"] += max(0.0, time.perf_counter()-selection_started
                -(self.temporal_metrics["solver_seconds"]-previous_solver_seconds)
                -(self.temporal_metrics["pool_generation_seconds"]-previous_pool_seconds))
            return None
        mode = "TEMPORAL_DISAGREEMENT" if qualified else "NATIVE_HYPOTHESIS"
        self.temporal_metrics["guided_queries" if qualified else "native_queries"] += 1
        proposal["temporal_guidance"] = mode
        proposal["temporal_hypothesis_ids"] = [rid for rid in proposal["hypothesis_ids"] if rid in self.temporal_relations]
        self.proposal_history.append({"index": self.seen[-1], "mode": mode, "version": self.version})
        self.temporal_metrics["selection_seconds"] += max(0.0, time.perf_counter()-selection_started
            -(self.temporal_metrics["solver_seconds"]-previous_solver_seconds)
            -(self.temporal_metrics["pool_generation_seconds"]-previous_pool_seconds))
        return proposal

    def _argument_witness(self):
        """Reuse one incremental integer solver to distinguish action contexts.

        Public pre-state is fixed from a valid model trace. Only the bounded
        argument is symbolic; SAT is read back as an actual valid novel trace.
        """
        name, _, argument_type = trace_layout(self.spec)
        if argument_type["kind"] != "int" or self._solver_version == self.version:
            return None, None
        self._solver_version = self.version
        # Preserve syntactically distinct hypotheses even when they agree on
        # the current pool: a fresh symbolic argument can separate them.
        remaining = sorted({r for group in self.groups.values() for r in group["remaining"]})
        active = [self.relations[r] for r in remaining if r in self.temporal_relations
                  and self.relations[r]["term"]["relation_kind"] in {"resource", "neutral-argument-boundary"}]
        for point in self.pool:
            replay = self._replays[canonical(point)]
            for row in replay["transitions"]:
                matching = [r for r in active if r["term"]["action"] == row["role"]]
                if len(matching) < 2:
                    continue
                context = row["context"]
                def specialize(node):
                    if isinstance(node, dict) and "var" in node:
                        return node if node["var"] == "arg" else deepcopy(context[node["var"]])
                    if isinstance(node, dict):
                        return {k: specialize(v) for k, v in node.items()}
                    if isinstance(node, list):
                        return [specialize(v) for v in node]
                    return node
                predicates = []
                for relation in matching:
                    predicate = specialize(relation["term"]["predicate"])
                    if predicate not in predicates:
                        predicates.append(predicate)
                if len(predicates) < 2:
                    continue
                started = time.perf_counter()
                if self._argument_solver is None:
                    from .efficient import IncrementalIntSolver
                    argument_spec = deepcopy(self.spec)
                    argument_spec["inputs"] = [{"name": "argument", "role": "arg", "type": argument_type}]
                    argument_spec["task_id"] = "temporal-argument-disagreement"
                    self._argument_solver = IncrementalIntSolver(argument_spec)
                check = self._argument_solver.solve(predicates[:8], mode="disagreement", version=self.version)
                self.temporal_metrics["solver_seconds"] += time.perf_counter()-started
                self.temporal_metrics["solver_calls"] += 1
                if check["status"] != "SAT":
                    return None, check
                candidate = {name: deepcopy(point[name][:row["index"]+1])}
                candidate[name][-1][1] = check["witness"]["argument"]
                candidate_replay = simulate_trace(candidate, self.spec, self.temporal_contract)
                if not candidate_replay["valid"]:
                    return None, {"status": "UNKNOWN", "reason": "public-precondition-rejected-witness"}
                votes = [temporal_holds(relation, candidate_replay) for relation in matching]
                if not (any(votes) and not all(votes)):
                    return None, {"status": "UNKNOWN", "reason": "concrete-trace-not-discriminating"}
                index = self._append_candidate(candidate, "INCREMENTAL_TEMPORAL_WITNESS")
                if index is None or index in self._seen:
                    return None, {"status": "UNKNOWN", "reason": "duplicate-or-capped-trace"}
                self.temporal_metrics["fresh_candidates"] = len(self.pool_events)
                self.temporal_metrics["solver_sat"] += 1
                return index, check
        return None, None

    def admit_native(self, inputs):
        """Register native state-machine input before its independent execution."""
        if self.frozen:
            raise ValueError("frozen engine rejects native registration")
        inputs = validate_inputs(inputs, self.spec)
        key = canonical(inputs)
        if key in self._index and self._index[key] in self._seen:
            return {"inputs": deepcopy(inputs), "duplicate": True, "frozen": False,
                    "sequence": self.seen.index(self._index[key])+1, "reason": "native-stateful-repeat"}
        if len(self.seen) >= self.budget:
            raise ValueError("temporal candidate budget exhausted")
        before = len(self.pool)
        index = self._append_candidate(inputs, "NATIVE_STATEFUL_PREFIX")
        if index is None:
            raise ValueError("native prefix violates temporal contract or candidate cap")
        self.temporal_metrics["fresh_candidates"] += len(self.pool)-before
        self.seen.append(index); self._seen.add(index)
        self.temporal_metrics["native_queries"] += 1
        self.proposal_history.append({"index": index, "mode": "NATIVE_HYPOTHESIS", "version": self.version})
        return {"inputs": deepcopy(inputs), "duplicate": False, "frozen": False,
                "sequence": len(self.seen), "reason": "native-stateful-registration",
                "objective": "failure-discovery", "temporal_guidance": "NATIVE_HYPOTHESIS",
                "hypothesis_ids": [], "temporal_hypothesis_ids": [], "solver_check": None}

    def observe(self, evidence):
        update_started = time.perf_counter()
        previous_update_seconds = self.temporal_metrics["version_update_seconds"]
        previous_pool_seconds = self.temporal_metrics["pool_generation_seconds"]
        if self.frozen:
            raise ValueError("frozen engine rejects final feedback")
        event = normalize_temporal_evidence(evidence, self.spec, self.temporal_contract)
        key = canonical(event["inputs"])
        if key not in self._index or self._index[key] not in self._seen or event["evidence_id"] in self._ids:
            raise ValueError("temporal evidence must be a new observation of a proposal")
        if event["kind"] == "FAILURE":
            self._activate_temporal()
        index = self._index[key]
        # A positive label identifies its first failed transition, rather than
        # supporting unrelated actions elsewhere in the same trace.
        replay = self._replays[key]
        for rid in self.temporal_relations:
            if temporal_holds(self.relations[rid], replay, event["first_failure_index"]):
                self.masks[rid] |= 1 << index
            else:
                self.masks[rid] &= ~(1 << index)
        result = super().observe({k: v for k, v in event.items() if k != "first_failure_index"})
        self.temporal_evidence.append(event)
        self.temporal_metrics["feedback_records"] += 1
        self.temporal_metrics["version_update_seconds"] = previous_update_seconds + max(0.0,
            time.perf_counter()-update_started-(self.temporal_metrics["pool_generation_seconds"]-previous_pool_seconds))
        result["temporal_remaining"] = sum(len(g["remaining"] & self.temporal_relations) for g in self.groups.values())
        return result

    def install_temporal_prior(self, prior, gate):
        """Internal validated role-based prior; transferred coordinates are absent."""
        if self.evidence or self.groups or self.seen:
            raise ValueError("prior requires a fresh engine")
        self._activate_temporal()
        from .temporal_transfer import validate_temporal_gate
        gate = validate_temporal_gate(gate)
        if gate["status"] != "APPLICABLE_FOR_PROBING":
            raise ValueError("only applicable structural priors may be installed")
        keys(prior, ("families", "source_snapshot_sha256"))
        if (not isinstance(prior["source_snapshot_sha256"], str) or len(prior["source_snapshot_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in prior["source_snapshot_sha256"])
                or prior["source_snapshot_sha256"] != gate["source_snapshot_sha256"]
                or not isinstance(prior["families"], list) or len(prior["families"]) > 64):
            raise ValueError("invalid bounded temporal prior")
        for family in prior["families"]:
            keys(family, ("family_id", "invariant", "relation_ids", "evidence_ids"))
            if family["invariant"] not in self.spec["contract"]["invariants"] or family["family_id"] in self.groups:
                raise ValueError("invalid prior failure family")
            parts = family["family_id"].split("/")
            if len(parts) != 3 or parts[0] != family["invariant"]:
                raise ValueError("invalid prior family identity")
            for part in parts:
                identifier(part)
            if not isinstance(family["relation_ids"], list) or set(family["relation_ids"]) - self.temporal_relations:
                raise ValueError("prior contains unsupported structural relations")
            if len(set(family["relation_ids"])) != len(family["relation_ids"]):
                raise ValueError("duplicate prior relation")
            if not isinstance(family["evidence_ids"], list) or len(family["evidence_ids"]) > 8192:
                raise ValueError("invalid prior evidence IDs")
            for evidence_id in family["evidence_ids"]:
                identifier(evidence_id)
            if not set(family["evidence_ids"]) <= set(gate["source_evidence_ids"]):
                raise ValueError("prior evidence is not in the validated source scope")
            self.groups[family["family_id"]] = {"invariant": family["invariant"], "remaining": set(family["relation_ids"]),
                "support": [], "source_evidence": [{"source_snapshot": prior["source_snapshot_sha256"],
                                                    "evidence_ids": deepcopy(family["evidence_ids"])}]}
        self.temporal_prior, self.temporal_gate = deepcopy(prior), deepcopy(gate)
        if sum(len(g["remaining"]) for g in self.groups.values()) != gate["transferred_relations"]:
            raise ValueError("transfer relation count differs from validated prior")

    def snapshot(self):
        payload = super().snapshot()
        payload.pop("receipt")
        payload.update(schema=SNAPSHOT_SCHEMA, temporal_contract=deepcopy(self.temporal_contract),
            temporal_evidence=deepcopy(self.temporal_evidence), temporal_prior=deepcopy(self.temporal_prior),
            temporal_gate=deepcopy(self.temporal_gate), temporal_metrics=deepcopy(self.temporal_metrics),
            proposal_history=deepcopy(self.proposal_history), budget=self.budget,
            temporal_relations=sorted(self.temporal_relations), lazy_pool=self.lazy_pool,
            activation_pool_size=self.activation_pool_size, native_expanded=self._native_expanded,
            guidance_version=self._guidance_version, solver_version=self._solver_version)
        payload["receipt"] = {"sha256": digest(payload), "meaning": "consistency-not-authorship-or-causality"}
        return payload

    @classmethod
    def from_snapshot(cls, snapshot):
        if not isinstance(snapshot, dict) or snapshot.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError("unsupported temporal snapshot")
        raw = {k: v for k, v in snapshot.items() if k != "receipt"}
        keys(snapshot["receipt"], ("sha256", "meaning"))
        if digest(raw) != snapshot["receipt"]["sha256"] or len(canonical(snapshot)) > 4000000:
            raise ValueError("temporal snapshot digest/size mismatch")
        engine = cls(snapshot["spec"], snapshot["temporal_contract"], seed=snapshot["seed"],
            strategy=snapshot["strategy"], pool_size=snapshot["pool_size"], budget=snapshot["budget"],
            candidate_pool=snapshot["initial_pool"], public_ir=snapshot["public_ir"])
        if type(snapshot["lazy_pool"]) is not bool:
            raise ValueError("invalid lazy pool provenance")
        engine.lazy_pool = snapshot["lazy_pool"]
        engine.activation_pool_size = snapshot["activation_pool_size"]
        if engine.lazy_pool and engine.spec["inputs"][0]["type"]["min_size"] == 0:
            if snapshot["initial_pool"] != [{engine.spec["inputs"][0]["name"]: []}]:
                raise ValueError("lazy initial pool differs from public empty seed")
        if engine.activation_pool_size is not None:
            integer(engine.activation_pool_size, 1, len(snapshot["pool"]))
        engine._restoring = True
        for entry in snapshot["pool_events"]:
            keys(entry, ("inputs", "source"))
            if entry["source"] not in {"TEMPORAL_NATIVE_DISAGREEMENT", "NATIVE_STATEFUL_PREFIX", "INCREMENTAL_TEMPORAL_WITNESS",
                                       "TEMPORAL_LAZY_ACTIVATION", "NATIVE_LAZY_QUERY"}:
                raise ValueError("unsupported temporal pool source")
            if engine._append_candidate(entry["inputs"], entry["source"]) is None:
                raise ValueError("invalid dynamic temporal candidate")
        if type(snapshot["native_expanded"]) is not bool:
            raise ValueError("invalid native expansion provenance")
        engine._native_expanded = snapshot["native_expanded"]
        expansion_sources = {"NATIVE_LAZY_QUERY", "TEMPORAL_LAZY_ACTIVATION"}
        if not engine._native_expanded and any(row["source"] in expansion_sources for row in snapshot["pool_events"]):
            raise ValueError("native pool history requires an expansion attempt")
        if not engine.lazy_pool and (engine._native_expanded or engine.activation_pool_size is not None):
            raise ValueError("explicit pool cannot claim lazy expansion")
        if snapshot["temporal_prior"] is not None:
            engine.install_temporal_prior(snapshot["temporal_prior"], snapshot["temporal_gate"])
        if len(snapshot["seen"]) > engine.budget or len(set(snapshot["seen"])) != len(snapshot["seen"]):
            raise ValueError("invalid temporal query history")
        for index in snapshot["seen"]:
            integer(index, 0, len(engine.pool)-1)
        # Reuse observe itself for replay: neither Oracle nor target is called.
        engine.seen, engine._seen = list(snapshot["seen"]), set(snapshot["seen"])
        for event in snapshot["temporal_evidence"]:
            engine.observe(event)
        if type(snapshot["frozen"]) is not bool:
            raise ValueError("invalid frozen state")
        engine.frozen = snapshot["frozen"]
        metrics = snapshot["temporal_metrics"]
        keys(metrics, ("activation_count", "guided_rounds", "fresh_candidates", "guided_queries", "native_queries", "feedback_records",
                       "pool_generation_seconds", "version_update_seconds", "solver_seconds", "selection_seconds", "solver_calls", "solver_sat"))
        for key, value in metrics.items():
            if key.endswith("_seconds"):
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e9:
                    raise ValueError("invalid measured temporal cost")
            else:
                integer(value, 0, 1000000)
        if metrics["activation_count"] != engine.temporal_metrics["activation_count"] or metrics["feedback_records"] != len(engine.evidence):
            raise ValueError("temporal metrics disagree with evidence")
        if engine.lazy_pool and bool(metrics["activation_count"]) != (engine.activation_pool_size is not None):
            raise ValueError("activation cutoff disagrees with lazy activation state")
        if engine.lazy_pool and metrics["activation_count"] and not engine._native_expanded:
            raise ValueError("lazy activation requires an attempted native expansion")
        if metrics["fresh_candidates"] != len(engine.pool_events) or metrics["guided_queries"] + metrics["native_queries"] != len(engine.seen):
            raise ValueError("temporal metrics disagree with pool/history")
        history = snapshot["proposal_history"]
        if not isinstance(history, list) or len(history) != len(engine.seen):
            raise ValueError("proposal history differs from seen candidates")
        last_version = 0
        for index, row in zip(engine.seen, history):
            keys(row, ("index", "mode", "version"))
            integer(row["version"], last_version, engine.version)
            last_version = row["version"]
            if row["index"] != index or row["mode"] not in {"TEMPORAL_DISAGREEMENT", "NATIVE_HYPOTHESIS"}:
                raise ValueError("invalid proposal mode/index")
        engine.temporal_metrics = deepcopy(metrics)
        engine.proposal_history = deepcopy(history)
        for field in ("guidance_version", "solver_version"):
            if snapshot[field] is not None:
                integer(snapshot[field], 0, engine.version)
        if bool(metrics["guided_rounds"]) != (snapshot["guidance_version"] is not None):
            raise ValueError("guidance cache version disagrees with native guidance attempts")
        engine._guidance_version = snapshot["guidance_version"]
        engine._solver_version = snapshot["solver_version"]
        engine._restoring = False
        if set(snapshot) != set(engine.snapshot()) or engine.snapshot() != snapshot:
            raise ValueError("temporal snapshot derived state mismatch")
        return engine


def validate_temporal_snapshot(snapshot):
    return TemporalEngine.from_snapshot(snapshot).snapshot()
