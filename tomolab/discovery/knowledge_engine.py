"""Bounded public-only planning with independently qualified failure hypotheses.

Hypothesis supplies every ordinary candidate. Knowledge may reorder at most
half a plan and contribute a checked integer-SMT witness. It never replaces
the declared input strategy or receives an execution callback.
"""
from copy import deepcopy
import math
import time

from .features import diversity_descriptor, measurements
from .hypothesis_adapter import generate_pool
from .predicates import validate_public_ir
from .schema import canonical, digest, integer, keys, validate_inputs, validate_spec


SCHEMA = "tomolab-knowledge-engine-v1"


class KnowledgeEngine:
    def __init__(self, spec, *, archive=None, temporal_contract=None,
                 target_provenance=None, public_ir=None, seed=7, budget=64,
                 pool_size=128, guidance_budget=16):
        from .knowledge import KnowledgeArchive, validate_provenance
        tick = time.perf_counter()
        self.spec = validate_spec(spec)
        self.seed = integer(seed, 0, 2**32-1)
        self.budget = integer(budget, 1, 4096)
        self.pool_size = integer(pool_size, 1, 4096)
        self.guidance_budget = integer(guidance_budget, 0, 2048)
        if self.guidance_budget > self.budget//2:
            self.guidance_budget = self.budget//2
        self.temporal_contract = None
        if temporal_contract is not None:
            from .temporal import validate_temporal_contract
            self.temporal_contract = validate_temporal_contract(temporal_contract, self.spec)
        self.public_ir = validate_public_ir(public_ir, self.spec) if public_ir is not None else None
        self.target_provenance = validate_provenance(target_provenance) if target_provenance is not None else None
        self.archive = None
        self.gate = {"status":"APPLICABILITY_UNKNOWN", "claims":[], "decisions":[],
                     "reason":"NO_ARCHIVE", "final_feedback_allowed":False}
        if archive is not None:
            source = KnowledgeArchive.from_snapshot(archive)
            self.archive = source.snapshot()
            self.gate = source.qualify(self.spec, target_provenance=target_provenance,
                temporal_contract=self.temporal_contract, public_ir=self.public_ir)
        self.active = {claim["claim_id"]:deepcopy(claim) for claim in self.gate["claims"][:64]}
        self.metrics = {"gating_seconds":time.perf_counter()-tick,
            "native_generation_seconds":0.0, "knowledge_selection_seconds":0.0,
            "solver_seconds":0.0, "solver_calls":0, "solver_sat":0,
            "native_candidates":0, "guided_candidates":0, "duplicate_candidates":0,
            "qualified_claims":len(self.gate["claims"]), "active_claims":len(self.active),
            "refuted_claims":0, "guidance_activations":0, "native_pool_builds":0,
            "prediction_cache_hits":0, "qualified_claims_outside_active_cap":max(0,len(self.gate["claims"])-64),
            "oracle_calls":0, "target_calls":0}
        self.native_pool = None
        self.seen, self.descriptors, self.proposals = set(), set(), []
        self.observations, self.history, self.refutations = [], [], []
        self.observation_ids = {}
        self.solver = None
        self.solver_attempted = set()
        self.guidance_exhausted = set()
        self._prediction_cache = {}
        self._scope_key = digest({"spec":self.spec,"contract":self.temporal_contract,
                                  "archive":digest(self.archive)})
        self.version = 0
        self.frozen = False

    @property
    def qualified(self):
        return bool(self.active) and self.guidance_budget > 0

    def _ensure_pool(self):
        if self.native_pool is not None:
            return
        before = time.perf_counter()
        size = min(4096, max(self.budget, self.pool_size))
        if self.temporal_contract is None:
            self.native_pool = generate_pool(self.spec, seed=self.seed, size=size)
        else:
            from .efficient import generate_temporal_pool
            self.native_pool = generate_temporal_pool(self.spec, self.temporal_contract,
                                                     seed=self.seed, size=size)
        self.metrics["native_generation_seconds"] += time.perf_counter()-before
        self.metrics["native_pool_builds"] += 1

    def _votes(self, point):
        from .knowledge import evaluate_claim
        votes = {}
        for cid, claim in sorted(self.active.items()):
            key = (self._scope_key,cid,canonical(point))
            if key in self._prediction_cache:
                self.metrics["prediction_cache_hits"] += 1
                votes[cid] = self._prediction_cache[key]
            else:
                votes[cid] = evaluate_claim(claim,point,self.spec,
                                            temporal_contract=self.temporal_contract)
                if len(self._prediction_cache) >= 8192:
                    self._prediction_cache.pop(next(iter(self._prediction_cache)))
                self._prediction_cache[key] = votes[cid]
        return votes

    def _descriptor(self, point):
        return diversity_descriptor(measurements(point, self.spec))

    def _solver_point(self):
        if self.temporal_contract is not None:
            return None
        predicates = [c["typed_relation"]["term"]["expression"] for c in self.active.values()
                      if c["typed_relation"]["term"]["kind"] == "ast"]
        if not predicates or any(i["type"]["kind"] != "int" for i in self.spec["inputs"]):
            return None
        # One solver attempt per active version; failed guidance is not retried
        # for every candidate. Version/contract/archive bind the cache identity.
        signature = digest({"spec":self.spec,"contract":self.temporal_contract,
                            "archive":digest(self.archive),"version":self.version,
                            "predicates":predicates})
        if signature in self.solver_attempted:
            return None
        self.solver_attempted.add(signature)
        from .efficient import IncrementalIntSolver
        if self.solver is None:
            self.solver = IncrementalIntSolver(self.spec, timeout_ms=100)
        before = time.perf_counter()
        result = self.solver.solve(predicates, mode="any",
            excluded=[p["inputs"] for p in self.proposals], version=self.version)
        self.metrics["solver_seconds"] += time.perf_counter()-before
        self.metrics["solver_calls"] += 1
        if result["status"] == "SAT" and result.get("witness") is not None:
            point = validate_inputs(result["witness"], self.spec)
            if canonical(point) not in self.seen and any(self._votes(point).values()):
                self.metrics["solver_sat"] += 1
                return point
        return None

    def propose(self):
        if self.frozen:
            raise ValueError("frozen knowledge engine cannot propose or learn")
        if len(self.proposals) >= self.budget:
            return None
        self._ensure_pool()
        before = time.perf_counter()
        guided = (self.qualified and self.metrics["guided_candidates"] < self.guidance_budget
                  and len(self.proposals) % 2 == 0 and self.version not in self.guidance_exhausted)
        point, source, votes = None, "NATIVE_HYPOTHESIS", {}
        if guided:
            self.metrics["guidance_activations"] += 1
            point = self._solver_point()
            if point is not None:
                source, votes = "QUALIFIED_Z3_WITNESS", self._votes(point)
            else:
                ranked = []
                for index, candidate in enumerate(self.native_pool):
                    if canonical(candidate) in self.seen:
                        continue
                    predictions = self._votes(candidate)
                    if not any(predictions.values()):
                        continue
                    disagreement = len(set(predictions.values())) > 1
                    novel = self._descriptor(candidate) not in self.descriptors
                    ranked.append((int(disagreement), int(novel), -index, candidate, predictions))
                if ranked:
                    *_, point, votes = max(ranked, key=lambda row:row[:3])
                    source = "QUALIFIED_STRUCTURAL_PROBE"
            if point is None:
                self.guidance_exhausted.add(self.version)
        if point is None:
            for candidate in self.native_pool:
                if canonical(candidate) not in self.seen:
                    point = candidate
                    break
        self.metrics["knowledge_selection_seconds"] += time.perf_counter()-before
        if point is None:
            return None
        point = validate_inputs(point, self.spec)
        key = canonical(point)
        if key in self.seen:
            raise ValueError("duplicate planned input")
        self.seen.add(key)
        self.descriptors.add(self._descriptor(point))
        is_guided = source.startswith("QUALIFIED_")
        self.metrics["guided_candidates" if is_guided else "native_candidates"] += 1
        proposal = {"inputs":point,"source":source,"claim_ids":sorted(cid for cid,v in votes.items() if v),
                    "predictions":votes,"frozen":False,"version":self.version,
                    "scope_sha256":digest({"spec":self.spec,"contract":self.temporal_contract,
                                           "archive":digest(self.archive)})}
        self.proposals.append(deepcopy(proposal))
        self.history.append({"kind":"proposal","value":deepcopy(proposal)})
        return deepcopy(proposal)

    def observe(self, observation):
        if self.frozen:
            raise ValueError("frozen knowledge engine cannot observe")
        from .knowledge import evaluate_claim, normalize_observation
        event = normalize_observation(observation)
        if canonical(event["spec"]) != canonical(self.spec) or canonical(event["temporal_contract"]) != canonical(self.temporal_contract):
            raise ValueError("observation belongs to a different target contract")
        if canonical(event["origin"]) != canonical(self.target_provenance):
            raise ValueError("observation target provenance mismatch")
        evidence = event["evidence"]
        if canonical(evidence["inputs"]) not in self.seen:
            raise ValueError("observation input was not proposed by this engine")
        eid = evidence["evidence_id"]
        if eid in self.observation_ids:
            if canonical(event) != canonical(self.observation_ids[eid]):
                raise ValueError("evidence id reused with changed data")
            return {"status":"IDEMPOTENT","version":self.version}
        from .engine import family_of
        removed = []
        for cid, claim in sorted(self.active.items()):
            prediction = evaluate_claim(claim,evidence["inputs"],self.spec,
                temporal_contract=self.temporal_contract,
                first_failure_index=evidence.get("first_failure_index"))
            observed = evidence["kind"] == "FAILURE" and family_of(evidence) == claim["family_id"]
            if prediction != observed:
                removed.append(cid)
        for cid in removed:
            del self.active[cid]
            self.refutations.append({"claim_id":cid,"evidence_id":eid,"status":"CONTRADICTED"})
        self.observation_ids[eid] = deepcopy(event)
        self.observations.append(deepcopy(event))
        self.history.append({"kind":"observation","value":deepcopy(event)})
        self.version += 1
        self.metrics["active_claims"] = len(self.active)
        self.metrics["refuted_claims"] += len(removed)
        return {"status":"OBSERVED","version":self.version,"refuted_claim_ids":removed}

    def snapshot(self):
        payload = {"schema":SCHEMA,"spec":self.spec,"archive":self.archive,
            "temporal_contract":self.temporal_contract,"public_ir":self.public_ir,
            "target_provenance":self.target_provenance,"seed":self.seed,"budget":self.budget,
            "pool_size":self.pool_size,"guidance_budget":self.guidance_budget,
            "gate":self.gate,"history":self.history,"active_claim_ids":sorted(self.active),
            "refutations":self.refutations,"version":self.version,"frozen":self.frozen,
            "metrics":self.metrics,"final_feedback_allowed":False}
        return deepcopy({**payload,"receipt":{"sha256":digest(payload)}})

    def freeze(self):
        if not self.frozen:
            self.history.append({"kind":"freeze","value":None})
        self.frozen = True
        return self.snapshot()

    @classmethod
    def from_snapshot(cls, snapshot):
        required = ("schema","spec","archive","temporal_contract","public_ir","target_provenance",
                    "seed","budget","pool_size","guidance_budget","gate","history",
                    "active_claim_ids","refutations","version","frozen","metrics",
                    "final_feedback_allowed","receipt")
        keys(snapshot, required)
        if snapshot["schema"] != SCHEMA or snapshot["final_feedback_allowed"] is not False:
            raise ValueError("unsupported knowledge engine snapshot")
        keys(snapshot["receipt"], ("sha256",))
        payload = {k:v for k,v in snapshot.items() if k != "receipt"}
        if digest(payload) != snapshot["receipt"]["sha256"]:
            raise ValueError("knowledge snapshot digest mismatch")
        if type(snapshot["frozen"]) is not bool or not isinstance(snapshot["history"],list) or len(snapshot["history"]) > 8193:
            raise ValueError("bounded strict replay history required")
        result = cls(snapshot["spec"], **{k:snapshot[k] for k in
            ("archive","temporal_contract","target_provenance","public_ir","seed","budget","pool_size","guidance_budget")})
        for entry in snapshot["history"]:
            keys(entry, ("kind","value"))
            if entry["kind"] == "proposal":
                if canonical(result.propose()) != canonical(entry["value"]):
                    raise ValueError("knowledge proposal replay differs")
            elif entry["kind"] == "observation":
                result.observe(entry["value"])
            elif entry["kind"] == "freeze" and entry["value"] is None:
                result.freeze()
            else:
                raise ValueError("unsupported replay event")
        if snapshot["frozen"]:
            result.freeze()
        rebuilt = result.snapshot()
        for field in required:
            if field not in {"metrics","receipt"} and canonical(rebuilt[field]) != canonical(snapshot[field]):
                raise ValueError("knowledge snapshot semantic replay differs: "+field)
        # Timings are measurements, not input to decisions or promotion.
        if set(snapshot["metrics"]) != set(result.metrics):
            raise ValueError("unsupported knowledge metrics")
        for name,value in snapshot["metrics"].items():
            if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
                raise ValueError("knowledge metrics require nonnegative finite numbers")
            if not name.endswith("_seconds") and value != result.metrics[name]:
                raise ValueError("knowledge counter differs from semantic replay")
        result.metrics = deepcopy(snapshot["metrics"])
        return result


def plan_knowledge(archive, spec, *, target_provenance, temporal_contract=None,
                   public_ir=None, budget=64, seed=7, pool_size=128, guidance_budget=16):
    """Make and freeze a public plan without target/source/Oracle callbacks."""
    engine = KnowledgeEngine(spec, archive=archive, target_provenance=target_provenance,
        temporal_contract=temporal_contract, public_ir=public_ir, budget=budget,
        seed=seed, pool_size=pool_size, guidance_budget=guidance_budget)
    candidates = []
    for _ in range(budget):
        point = engine.propose()
        if point is None:
            break
        point["frozen"] = True
        candidates.append(point)
    snapshot = engine.freeze()
    return {"schema":"tomolab-knowledge-plan-v1","candidates":candidates,
            "snapshot":snapshot,"gate":engine.gate,"candidate_sha256":digest(candidates),
            "oracle_calls":0,"target_calls":0,"final_feedback_allowed":False,
            "generalization":"UNKNOWN"}
