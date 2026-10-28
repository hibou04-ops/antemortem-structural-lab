"""Evidence-gated failure-membership knowledge, interpreted as bounded data.

Oracle and implementation independence are reviewed host attestations bound to
source hashes. Hashes protect identity/integrity, not semantic independence or
causality. No self-reported probability, LLM vote or final feedback is accepted.
"""
from copy import deepcopy
from collections import OrderedDict
import json
import re
from threading import RLock

from .schema import (canonical, digest, identifier, integer, keys, normalize_evidence,
                     type_subset, validate_inputs, validate_spec)
from .features import holds, measurements, transferable, validate_relation
from .predicates import validate_predicate, validate_public_ir

SCHEMA = "tomolab-knowledge-archive-v1"
SEMANTIC_SCHEMA = "tomolab-knowledge-archive-v2"
STATUSES = {"HYPOTHESIS", "SUPPORTED_WITHIN_SCOPE", "CONTRADICTED",
            "APPLICABILITY_UNKNOWN", "QUALIFIED_FOR_PROBING"}
PROVENANCE_FIELDS = ("project", "lineage", "revision", "oracle_id", "semantics")
HASH_FIELDS = ("implementation_sha256", "oracle_sha256")
MAX_EVENTS = 256
MAX_CLAIMS = 4096
MAX_GENERATIONS = 32
VALIDATION_CACHE_VERSION = "e7-knowledge-validation-v3"
_VALIDATED_ARCHIVES = OrderedDict()
_VALIDATION_CACHE_ENTRIES = 4
_VALIDATION_CACHE_BYTES = 16*1024*1024
_VALIDATION_CACHE_LOCK = RLock()


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("a pinned SHA-256 is required")
    return value


def validate_provenance(value):
    """Validate an explicit reviewed-host attestation; never infer ownership."""
    keys(value, PROVENANCE_FIELDS, (*HASH_FIELDS, "independence_id"))
    for name in PROVENANCE_FIELDS:
        identifier(value[name])
    for name in HASH_FIELDS:
        if name in value:
            _sha(value[name])
    if "independence_id" in value:
        identifier(value["independence_id"])
    return deepcopy(value)


def _context(spec, temporal_contract=None, public_ir=None):
    spec = validate_spec(spec)
    if temporal_contract is not None:
        from .temporal import validate_temporal_contract
        temporal_contract = validate_temporal_contract(temporal_contract, spec)
    if public_ir is not None:
        public_ir = validate_public_ir(public_ir, spec)
    return spec, deepcopy(temporal_contract), deepcopy(public_ir)


def _evidence(value, spec, temporal_contract):
    if temporal_contract is not None:
        from .temporal import normalize_temporal_evidence
        return normalize_temporal_evidence(value, spec, temporal_contract)
    return normalize_evidence(value, spec)


def normalize_observation(value):
    """Strict minimal development receipt. Caller approval remains necessary."""
    fields = ("spec", "temporal_contract", "public_ir", "evidence", "origin", "split",
              "implementation_sha256", "receipt_sha256")
    keys(value, fields)
    if value["split"] != "development":
        raise ValueError("only development observations are accepted; final feedback is forbidden")
    if value["receipt_sha256"] != digest({k:v for k,v in value.items() if k != "receipt_sha256"}):
        raise ValueError("observation receipt mismatch")
    spec, contract, ir = _context(value["spec"], value["temporal_contract"], value["public_ir"])
    origin = validate_provenance(value["origin"])
    implementation = _sha(value["implementation_sha256"])
    if origin.get("implementation_sha256", implementation) != implementation:
        raise ValueError("implementation identity differs from reviewed provenance")
    event = _evidence(value["evidence"], spec, contract)
    result = dict(spec=spec, temporal_contract=contract, public_ir=ir, evidence=event,
                  origin=origin, split="development", implementation_sha256=implementation)
    result["receipt_sha256"] = digest(result)
    if result != value:
        raise ValueError("observation must use canonical validated public data")
    return deepcopy(result)


def make_observation(spec, evidence, origin, *, temporal_contract=None, public_ir=None,
                     implementation_sha256=None):
    """Construct a receipt in the trusted evaluator after actual Oracle execution."""
    spec, temporal_contract, public_ir = _context(spec, temporal_contract, public_ir)
    origin = validate_provenance(origin)
    implementation = implementation_sha256 or origin.get("implementation_sha256")
    value = dict(spec=spec, temporal_contract=temporal_contract, public_ir=public_ir,
                 evidence=_evidence(evidence, spec, temporal_contract), origin=origin,
                 split="development", implementation_sha256=_sha(implementation))
    value["receipt_sha256"] = digest(value)
    return normalize_observation(value)


def normalize_semantic_observation(value):
    """Explicit R1 development envelope; legacy normalization stays unchanged."""
    from .claim_semantics import normalize_semantic_evidence
    fields=("spec","temporal_contract","public_ir","evidence","origin","split","implementation_sha256","receipt_sha256")
    keys(value,fields)
    if value["receipt_sha256"]!=digest({k:v for k,v in value.items() if k!="receipt_sha256"}):
        raise ValueError("observation receipt mismatch")
    if value["split"]!="development" or value["temporal_contract"] is not None:
        raise ValueError("R1 accepts stateless DEVELOPMENT only; final feedback is forbidden")
    spec,contract,ir=_context(value["spec"],None,value["public_ir"])
    origin=validate_provenance(value["origin"]);implementation=_sha(value["implementation_sha256"])
    if origin.get("implementation_sha256")!=implementation:
        raise ValueError("implementation identity differs from reviewed provenance")
    event=normalize_semantic_evidence(value["evidence"],spec)
    result=dict(spec=spec,temporal_contract=contract,public_ir=ir,evidence=event,origin=origin,
                split="development",implementation_sha256=implementation)
    result["receipt_sha256"]=digest(result)
    if result!=value:raise ValueError("canonical validated R1 observation required")
    return deepcopy(result)


def _validate_relation(relation, spec, temporal_contract):
    if isinstance(relation, dict) and isinstance(relation.get("term"), dict) and relation["term"].get("kind") == "temporal":
        from .temporal import temporal_hypotheses
        if temporal_contract is None or relation not in temporal_hypotheses(temporal_contract, spec).values():
            raise ValueError("temporal relation is outside the existing bounded public grammar")
    else:
        validate_relation(relation)
        roles = {item["role"] for item in spec["inputs"]}
        if not set(relation["term"]["roles"]) <= roles:
            raise ValueError("relation references undeclared roles")
        if relation["term"]["kind"] == "ast":
            validate_predicate(relation["term"]["expression"], spec)
    return deepcopy(relation)


def _coordinate_only(relation):
    term = relation["term"]
    if term["kind"] == "temporal":
        return term["relation_kind"] == "neutral-argument-boundary"
    if not transferable(relation):
        return True
    if term["kind"] == "ast":
        def arbitrary_constant(node):
            if type(node) in (int, float):
                return node not in (0, 1)
            if isinstance(node, str):
                return True
            if isinstance(node, dict):
                if "var" in node:
                    return False
                return any(arbitrary_constant(v) for k,v in node.items() if k != "op")
            return isinstance(node, list) and any(arbitrary_constant(v) for v in node)
        return arbitrary_constant(term["expression"])
    return False


def evaluate_claim(claim, inputs, spec, temporal_contract=None, first_failure_index=None):
    """Predict failure-family membership; a True result never proves a bug."""
    if not isinstance(claim, dict) or "typed_relation" not in claim:
        raise ValueError("typed structural claim required")
    if "claim_kind" in claim:
        from .claim_semantics import SEMANTIC_VERSION, relation_prediction
        if claim.get("semantic_version") != SEMANTIC_VERSION or temporal_contract is not None:
            raise ValueError("unsupported explicit structural claim semantics")
        return relation_prediction(claim["typed_relation"], inputs, validate_spec(spec), claim.get("semantic_policy"))
    spec, contract, _ = _context(spec, temporal_contract)
    point = validate_inputs(inputs, spec)
    relation = _validate_relation(claim["typed_relation"], spec, contract)
    if relation["term"]["kind"] == "temporal":
        from .temporal import simulate_trace, temporal_holds
        replay = simulate_trace(point, spec, contract)
        if not replay["valid"]:
            raise ValueError("claim prediction requires a valid public trace")
        if first_failure_index is not None:
            integer(first_failure_index, 0, len(replay["transitions"])-1)
        return bool(temporal_holds(relation, replay, first_failure_index))
    predicates = [relation["term"]["expression"]] if relation["term"]["kind"] == "ast" else []
    return bool(holds(relation, measurements(point, spec, predicates)))


def _shape(contract):
    if contract is None:
        return None
    return {"state": sorted([{k:v for k,v in s.items() if k != "name"} for s in contract["state"]],key=lambda s:s["role"]),
            "actions": sorted([{k:v for k,v in a.items() if k != "name"} for a in contract["actions"]],key=lambda a:a["role"]),
            "invariants": sorted(contract["invariants"],key=canonical),
            "disabled_action":contract.get("disabled_action","REJECT")}


def _scope_reasons(source_spec, source_contract, source_ir, source_origin,
                   target_spec, target_contract, target_ir, target_origin):
    reasons=[]
    if source_origin["semantics"] != target_origin["semantics"]:
        reasons.append("declared-operation-semantics-differ")
    left={i["role"]:i["type"] for i in source_spec["inputs"]}
    right={i["role"]:i["type"] for i in target_spec["inputs"]}
    if left.keys() != right.keys():
        reasons.append("semantic-roles-differ")
    elif any(not type_subset(right[k],left[k]) for k in left):
        reasons.append("target-outside-typed-source-scope")
    for name in ("id","operation","preconditions","invariants","state_model"):
        if source_spec["contract"][name] != target_spec["contract"][name]:
            reasons.append("contract-"+name+"-differs")
    if _shape(source_contract) != _shape(target_contract):
        reasons.append("state-transition-semantics-differ")
    # Missing graph information is not fabricated. Explicit reviewed semantics
    # plus typed contracts can authorize a bounded probe; AST claims separately
    # require approved corresponding IR before qualification.
    for name in ("graph_signature",):
        a,b=source_spec["contract"][name],target_spec["contract"][name]
        if a != b:
            reasons.append("operation-graph-differs")
    return reasons


def _independent(source, origin, implementation):
    required=(*HASH_FIELDS,"independence_id")
    return (all(name in source and name in origin for name in required)
            and source["implementation_sha256"] != implementation
            and origin["implementation_sha256"] == implementation
            and source["oracle_sha256"] != origin["oracle_sha256"]
            and source["oracle_id"] != origin["oracle_id"]
            and source["lineage"] != origin["lineage"]
            and source["independence_id"] != origin["independence_id"])


class KnowledgeArchive:
    """Append-only, replayable development knowledge over E5/E6 candidates."""
    def __init__(self, spec, *, source=None, provenance=None, temporal_contract=None, public_ir=None,
                 semantic_policy=None, claim_kinds=None, derived_from=None):
        if source is not None and provenance is not None:
            raise ValueError("provide one source provenance")
        self.spec,self.temporal_contract,self.public_ir=_context(spec,temporal_contract,public_ir)
        self.source=validate_provenance(source if source is not None else provenance)
        self.semantic_policy = None
        self.claim_kinds = None
        self._derived_from = None
        self._source_validation = []
        self._utility_journal = []
        self._semantic_rows_cache = None
        self._semantic_rows_binding = None
        self._r1_receipt_cache = None
        self._r1_replaying = False
        if semantic_policy is not None or claim_kinds is not None:
            from .claim_semantics import normalize_policy, normalize_claim_kinds
            if temporal_contract is not None:
                raise ValueError("R1 partial-claim semantics currently supports stateless contracts only")
            self.semantic_policy = normalize_policy(semantic_policy)
            self.claim_kinds = normalize_claim_kinds(claim_kinds)
            self._derived_from = self._r1_parent_metadata(derived_from)
        elif derived_from is not None:
            raise ValueError("legacy claims cannot silently reinterpret a parent archive")
        self._r1_bound_scope=(digest({"scope":self._r1_scope(),"claim_kinds":self.claim_kinds})
                              if self.semantic_policy is not None else None)
        self._journal=[]
        self._events=[]
        self._relations={}
        self._families={}
        self._source_evidence=[]
        self._source_ids={}
        self._observation_ids={}
        self._claim_cache=None
        self._prediction_cache={}
        self.frozen=False

    @classmethod
    def from_failure_log(cls, spec, evidence, provenance, *, temporal_contract=None, public_ir=None,
                         semantic_policy=None, claim_kinds=None, derived_from=None):
        archive=cls(spec,source=provenance,temporal_contract=temporal_contract,public_ir=public_ir,
                    semantic_policy=semantic_policy,claim_kinds=claim_kinds,derived_from=derived_from)
        archive.learn(evidence)
        return archive

    @classmethod
    def from_engine_snapshot(cls, snapshot, provenance):
        from .engine import DiscoveryEngine
        if isinstance(snapshot,dict) and snapshot.get("schema")=="tomolab-temporal-snapshot-v1":
            from .temporal_engine import TemporalEngine
            engine=TemporalEngine.from_snapshot(snapshot)
        else:
            engine=DiscoveryEngine.from_snapshot(snapshot)
        if not engine.frozen:
            raise ValueError("source engine snapshot must be frozen")
        archive=cls(engine.spec,source=provenance,temporal_contract=getattr(engine,"temporal_contract",None),public_ir=engine.public_ir,
                    semantic_policy=getattr(engine,"semantic_policy",None),claim_kinds=getattr(engine,"claim_kinds",None))
        archive._import(engine)
        archive._journal.append({"action":"import","snapshot":deepcopy(snapshot)})
        return archive

    def _open(self):
        if self.frozen:
            raise ValueError("frozen knowledge rejects learning and final feedback")

    def _import(self, engine):
        if self.semantic_policy is not None:
            return self._r1_import(engine)
        from .engine import family_of
        if len(engine.groups)>8:
            raise ValueError("narrow to at most eight source failure families")
        relations=deepcopy(self._relations);families=deepcopy(self._families)
        for family, group in engine.groups.items():
            identifier(group["invariant"])
            families[family]={"invariant":group["invariant"]}
            for rid,relation in engine.relations.items():
                relation=_validate_relation(relation,self.spec,self.temporal_contract)
                cid="K-"+digest({"relation":relation,"family":family,"source":self.source,"spec":self.spec})[:24]
                relations[cid]={"claim_id":cid,"family_id":family,"typed_relation":relation,
                                      "source_relation_id":rid,"coordinate_only":_coordinate_only(relation)}
        if len(relations)>MAX_CLAIMS:
            raise ValueError("knowledge candidate cap exceeded; narrow the public grammar")
        self._relations=relations;self._families=families
        self._source_evidence=deepcopy(engine.temporal_evidence if hasattr(engine,"temporal_evidence") else engine.evidence)
        self._source_ids={e["evidence_id"]:e for e in self._source_evidence}
        self._claim_cache=None
        self._prediction_cache={}

    def learn(self, evidence):
        if self.semantic_policy is not None:
            return self._r1_learn(evidence)
        self._open()
        if self.generation_id is not None:
            raise ValueError("resumed generations accept only reviewed development observation receipts")
        if not isinstance(evidence,list) or not 1<=len(evidence)<=MAX_EVENTS:
            raise ValueError("a bounded nonempty source failure log is required")
        pending=[]
        for value in evidence:
            event=_evidence(value,self.spec,self.temporal_contract)
            eid=event["evidence_id"]
            if eid in self._source_ids:
                if self._source_ids[eid]!=event:
                    raise ValueError("source evidence ID conflict")
                continue
            if any(e["evidence_id"]==eid for e in pending):
                raise ValueError("duplicate source evidence ID")
            pending.append(event)
        if not pending:
            return self.snapshot()
        events=self._source_evidence+pending
        if len(events)>MAX_EVENTS:
            raise ValueError("source evidence cap exceeded")
        pool=list({canonical(e["inputs"]):e["inputs"] for e in events}.values())
        from .engine import DiscoveryEngine
        if self.temporal_contract is None:
            engine=DiscoveryEngine(self.spec,public_ir=self.public_ir,native_strategy=False,_pool=pool,pool_size=len(pool))
            for event in events:
                index=engine._index[canonical(event["inputs"])]
                if index not in engine._seen:
                    engine._seen.add(index);engine.seen.append(index)
                engine.observe(event)
        else:
            from .temporal_engine import TemporalEngine
            engine=TemporalEngine(self.spec,self.temporal_contract,candidate_pool=pool,pool_size=len(pool),budget=MAX_EVENTS,public_ir=self.public_ir)
            for event in events:
                engine.admit_native(event["inputs"]);engine.observe(event)
        self._import(engine)
        self._journal.append({"action":"learn","evidence":deepcopy(pending)})
        return self.snapshot()

    def observe(self, event, *, trusted_observation=False):
        if self.semantic_policy is not None:
            return self._r1_observe(event,trusted_observation=trusted_observation)
        self._open()
        if trusted_observation is not True:
            raise PermissionError("reviewed independent Oracle receipt requires explicit trusted-host approval")
        value=normalize_observation(event)
        identity=(value["origin"]["project"],value["origin"]["lineage"],value["implementation_sha256"],value["evidence"]["evidence_id"])
        key=canonical(identity)
        if key in self._observation_ids:
            if self._observation_ids[key]!=value:
                raise ValueError("independent observation ID conflict")
            return self.snapshot()
        if len(self._events)>=MAX_EVENTS:
            raise ValueError("independent observation cap exceeded")
        self._events.append(value);self._observation_ids[key]=value
        self._claim_cache=None
        self._journal.append({"action":"observe","observation":deepcopy(value)})
        return self.snapshot()

    def _claim(self, cid):
        if self.semantic_policy is not None:
            return self._r1_claim(cid)
        from .engine import family_of
        base=deepcopy(self._relations[cid]);family=base["family_id"]
        supports=[];contradictions=[];independent_positive=[];independent_negative=[];ignored=[]
        seen_labels={}
        rows=[(self.spec,self.temporal_contract,self.public_ir,self.source,event,None) for event in self._source_evidence]
        rows += [(v["spec"],v["temporal_contract"],v["public_ir"],v["origin"],v["evidence"],v) for v in self._events]
        for spec,contract,ir,origin,event,receipt in rows:
            if event["invariant"]!=self._families[family]["invariant"]:
                continue
            eid=event["evidence_id"]
            token="source:"+eid if receipt is None else receipt["receipt_sha256"]
            reasons=_scope_reasons(self.spec,self.temporal_contract,self.public_ir,self.source,spec,contract,ir,origin)
            if reasons:
                ignored.append({"evidence":token,"reasons":reasons});continue
            cache_key=digest({"spec":spec,"contract":contract,"inputs":event["inputs"],"first":event.get("first_failure_index")})
            context=self._prediction_cache.get(cache_key)
            if context is None:
                from .temporal import simulate_trace
                context={"measured":measurements(event["inputs"],spec),"ast":{},
                         "replay":simulate_trace(event["inputs"],spec,contract) if contract is not None else None}
                self._prediction_cache[cache_key]=context
            relation=base["typed_relation"];term=relation["term"]
            if term["kind"]=="temporal":
                from .temporal import temporal_holds
                predicted=bool(temporal_holds(relation,context["replay"],event.get("first_failure_index")))
            elif term["kind"]=="ast":
                from .predicates import predicate_value
                ast_key=canonical(term["expression"])
                if ast_key not in context["ast"]:
                    context["ast"][ast_key]=int(bool(predicate_value(term["expression"],event["inputs"],spec)))
                predicted=bool(holds(relation,{canonical(term):context["ast"][ast_key]}))
            else:
                predicted=bool(holds(relation,context["measured"]))
            observed=event["kind"]=="FAILURE" and family_of(event)==family
            label_key=canonical([origin.get("implementation_sha256"),digest(spec),event["inputs"]])
            actual_label=(family_of(event) if event["kind"]=="FAILURE" else None,event.get("first_failure_index"))
            inconsistent=label_key in seen_labels and seen_labels[label_key]!=actual_label
            seen_labels[label_key]=actual_label
            if predicted!=observed or inconsistent:
                contradictions.append(token)
            else:
                supports.append(token)
                if receipt is not None and _independent(self.source,origin,receipt["implementation_sha256"]):
                    (independent_positive if observed else independent_negative).append(token)
        positive_origins={digest([v["origin"],v["implementation_sha256"]]) for v in self._events if v["receipt_sha256"] in independent_positive}
        negative_origins={digest([v["origin"],v["implementation_sha256"]]) for v in self._events if v["receipt_sha256"] in independent_negative}
        contrastive_origins=positive_origins & negative_origins
        status="CONTRADICTED" if contradictions else "SUPPORTED_WITHIN_SCOPE" if contrastive_origins and not base["coordinate_only"] else "HYPOTHESIS"
        base.update(status=status,supporting_evidence=supports,contradicting_evidence=contradictions,
                    independent_positive=independent_positive,independent_negative=independent_negative,
                    independent_contrastive_origins=sorted(contrastive_origins),
                    ignored_evidence=ignored,
                    competing_group=family,
                    source_scope={"spec":deepcopy(self.spec),"temporal_contract":deepcopy(self.temporal_contract),
                                  "public_ir":deepcopy(self.public_ir),"origin":deepcopy(self.source)},
                    uncertainty={"causality":"UNKNOWN","target_recurrence":"UNKNOWN","scope":"OBSERVED_DEVELOPMENT_ONLY"})
        return base

    def claims(self):
        if self._claim_cache is None:
            self._claim_cache=[self._claim(cid) for cid in sorted(self._relations)]
        return deepcopy(self._claim_cache)

    def status(self, claim_id):
        if claim_id not in self._relations:
            raise ValueError("unknown structural claim")
        return self._claim(claim_id)["status"]

    def qualify(self, target_spec, *, target_provenance=None, target=None, temporal_contract=None, public_ir=None):
        if self.semantic_policy is not None:
            return self._r1_qualify(target_spec,target_provenance=target_provenance,target=target,
                                    temporal_contract=temporal_contract,public_ir=public_ir)
        if not self.frozen:
            raise ValueError("probing requires a frozen knowledge archive")
        if target is not None and target_provenance is not None:
            raise ValueError("provide one target provenance")
        target=validate_provenance(target if target is not None else target_provenance)
        spec,contract,ir=_context(target_spec,temporal_contract,public_ir)
        reasons=_scope_reasons(self.spec,self.temporal_contract,self.public_ir,self.source,spec,contract,ir,target)
        if target["lineage"]==self.source["lineage"] or target.get("implementation_sha256")==self.source.get("implementation_sha256"):
            reasons.append("target-implementation-independence-unestablished")
        if target.get("independence_id")==self.source.get("independence_id"):
            reasons.append("target-reviewed-lineage-independence-unestablished")
        if not all(k in target for k in (*HASH_FIELDS,"independence_id")):
            reasons.append("target-reviewed-source-and-oracle-identities-missing")
        decisions=[];qualified=[]
        for claim in self.claims():
            why=list(reasons)
            if claim["coordinate_only"]:
                why.append("coordinate-only-hypothesis")
            if claim["typed_relation"]["term"]["kind"]=="ast":
                from .transfer import validate_transfer
                gate=validate_transfer(self.spec,spec,self.public_ir,ir)
                if gate["status"]!="APPLICABLE_FOR_PROBING":
                    why.append("approved-AST-graph-correspondence-unestablished")
            if claim["status"]=="CONTRADICTED":
                status="CONTRADICTED";why.append("archived-counterevidence")
            elif why:
                status="APPLICABILITY_UNKNOWN"
            elif claim["status"]!="SUPPORTED_WITHIN_SCOPE":
                status="HYPOTHESIS";why.append("independent-contrastive-support-insufficient")
            else:
                status="QUALIFIED_FOR_PROBING"
                value=deepcopy(claim);value["status"]=status;qualified.append(value)
            decisions.append({"claim_id":claim["claim_id"],"status":status,"reasons":sorted(set(why))})
        target_seen=any(v["implementation_sha256"]==target.get("implementation_sha256") for v in self._events)
        return {"status":"QUALIFIED_FOR_PROBING" if qualified else "APPLICABILITY_UNKNOWN",
                "claims":qualified,"decisions":decisions,"source_archive_sha256":self.snapshot()["receipt"]["sha256"],
                "final_feedback_allowed":False,"failure_recurrence":"UNKNOWN",
                "target_seen_in_development":target_seen,
                "authority":"REVIEWED_HOST_ATTESTATION_NOT_CRYPTOGRAPHIC_INDEPENDENCE_PROOF"}

    def freeze(self):
        if not self.frozen:
            self._journal.append({"action":"freeze"})
            self.frozen=True
            if self.semantic_policy is not None:self._r1_receipt_cache=None
        if self.semantic_policy is not None and self._r1_replaying:return None
        return self.snapshot()

    @property
    def generation_id(self):
        return next((row["generation_id"] for row in reversed(self._journal) if row["action"]=="fork"),None)

    def fork(self, generation_id):
        """Resume reviewed development in a new copy with all old evidence intact.

        The explicit fork is part of the replayed journal and binds the complete
        frozen parent receipt. It cannot turn final observations into development
        data or discard older counterevidence. Existing total event caps remain.
        """
        identifier(generation_id)
        if not self.frozen or not self._journal or self._journal[-1]["action"]!="freeze":
            raise ValueError("a new generation requires a terminal frozen parent")
        used={row["generation_id"] for row in self._journal if row["action"]=="fork"}
        if generation_id in used:
            raise ValueError("generation ID was already used in this archive lineage")
        if len(used)>=MAX_GENERATIONS:
            raise ValueError("knowledge generation cap exceeded")
        parent=(self._r1_current_receipt() if self.semantic_policy is not None else self.snapshot()["receipt"]["sha256"])
        if self.semantic_policy is None:
            child=deepcopy(self)
        else:
            child=deepcopy(self,{id(self._claim_cache):None,id(self._prediction_cache):{},id(self._semantic_rows_cache):None})
            child._r1_receipt_cache=None;child._semantic_rows_binding=None
        child._journal.append({"action":"fork","generation_id":generation_id,"parent_sha256":parent})
        child.frozen=False
        if child.semantic_policy is not None:child._r1_receipt_cache=None
        return child

    def snapshot(self):
        if self.semantic_policy is not None:
            return self._r1_snapshot()
        value={"schema":SCHEMA,"spec":deepcopy(self.spec),"temporal_contract":deepcopy(self.temporal_contract),
               "public_ir":deepcopy(self.public_ir),"source":deepcopy(self.source),
               "journal":deepcopy(self._journal),"claims":self.claims(),"frozen":self.frozen,
               "generation_id":self.generation_id,
               "competing_groups":{family:sorted(cid for cid,c in self._relations.items() if c["family_id"]==family) for family in sorted(self._families)},
               "source_observations":len(self._source_evidence),"independent_observations":len(self._events),
               "final_feedback_allowed":False}
        value["receipt"]={"sha256":digest(value),"authenticity":"REVIEWED_HOST_ATTESTATION_REQUIRED"}
        return value

    @classmethod
    def from_snapshot(cls, snapshot):
        """Reuse only fully replay-validated frozen bytes; return isolated copies.

        Full canonical bytes and validation version form the key. An edited or
        rehashed claim/journal cannot reuse an earlier successful validation.
        This is a computation cache, never an independence/Oracle authority.
        """
        if not isinstance(snapshot,dict):
            raise ValueError("knowledge snapshot must be an object")
        try:
            encoded=canonical(snapshot)
        except (TypeError,ValueError) as error:
            raise ValueError("knowledge snapshot requires finite JSON data") from error
        limit=(128 if snapshot.get("schema")==SEMANTIC_SCHEMA else 8)*1024*1024
        if len(encoded)>limit:
            raise ValueError("R1 knowledge snapshot exceeds 128 MiB" if snapshot.get("schema")==SEMANTIC_SCHEMA else "knowledge snapshot exceeds eight MiB")
        # Bind validation and cache eligibility to the exact bytes used by the
        # key. The caller may mutate its dictionary while replay is in flight.
        # A canonical JSON round trip removes every shared mutable reference.
        captured=json.loads(encoded)
        key=(cls,VALIDATION_CACHE_VERSION+("-r1" if snapshot.get("schema")==SEMANTIC_SCHEMA else ""),encoded)
        cached=None
        with _VALIDATION_CACHE_LOCK:
            if captured.get("frozen") is True and key in _VALIDATED_ARCHIVES:
                _VALIDATED_ARCHIVES.move_to_end(key)
                cached=_VALIDATED_ARCHIVES[key]
        if cached is not None:
            return deepcopy(cached)
        archive=cls._restore_snapshot(captured)
        if archive.frozen and len(encoded)<=_VALIDATION_CACHE_BYTES:
            cached=deepcopy(archive)
            with _VALIDATION_CACHE_LOCK:
                _VALIDATED_ARCHIVES[key]=cached
                while (len(_VALIDATED_ARCHIVES)>_VALIDATION_CACHE_ENTRIES or
                       sum(len(k[2]) for k in _VALIDATED_ARCHIVES)>_VALIDATION_CACHE_BYTES):
                    _VALIDATED_ARCHIVES.popitem(last=False)
        return archive

    @classmethod
    def _restore_snapshot(cls, snapshot):
        if snapshot.get("schema")==SEMANTIC_SCHEMA:
            return cls._r1_restore_snapshot(snapshot)
        fields=("schema","spec","temporal_contract","public_ir","source","journal","claims","frozen","generation_id","competing_groups",
                "source_observations","independent_observations","final_feedback_allowed","receipt")
        keys(snapshot,fields)
        if snapshot["schema"]!=SCHEMA or type(snapshot["frozen"]) is not bool or snapshot["final_feedback_allowed"] is not False:
            raise ValueError("invalid knowledge snapshot schema or feedback policy")
        keys(snapshot["receipt"],("sha256","authenticity"))
        if snapshot["receipt"]["authenticity"]!="REVIEWED_HOST_ATTESTATION_REQUIRED" or snapshot["receipt"]["sha256"]!=digest({k:v for k,v in snapshot.items() if k!="receipt"}):
            raise ValueError("knowledge snapshot receipt mismatch")
        if not isinstance(snapshot["journal"],list) or len(snapshot["journal"])>2*MAX_EVENTS+2*MAX_GENERATIONS+1:
            raise ValueError("bounded knowledge journal required")
        archive=cls(snapshot["spec"],source=snapshot["source"],temporal_contract=snapshot["temporal_contract"],public_ir=snapshot["public_ir"])
        for row in snapshot["journal"]:
            if not isinstance(row,dict):
                raise ValueError("journal entries must be data")
            if row.get("action")=="learn":
                keys(row,("action","evidence"));archive.learn(row["evidence"])
            elif row.get("action")=="observe":
                keys(row,("action","observation"));archive.observe(row["observation"],trusted_observation=True)
            elif row.get("action")=="import":
                keys(row,("action","snapshot"))
                if archive._journal:
                    raise ValueError("engine import is allowed only at archive genesis")
                archive=cls.from_engine_snapshot(row["snapshot"],archive.source)
            elif row.get("action")=="freeze":
                keys(row,("action",))
                if archive.frozen:
                    raise ValueError("duplicate terminal freeze event")
                archive.freeze()
            elif row.get("action")=="fork":
                keys(row,("action","generation_id","parent_sha256"))
                _sha(row["parent_sha256"])
                child=archive.fork(row["generation_id"])
                if child._journal[-1]!=row:
                    raise ValueError("knowledge fork does not identify its complete frozen parent")
                archive=child
            else:
                raise ValueError("unsupported knowledge journal action")
        if canonical(archive.snapshot())!=canonical(snapshot):
            raise ValueError("knowledge derived state is inconsistent with its evidence journal")
        return archive

    @staticmethod
    def _r1_parent_metadata(parent):
        if parent is None:
            return None
        if not isinstance(parent,dict):
            raise ValueError("explicit legacy parent snapshot or derived metadata required")
        if "schema" in parent:
            if parent.get("schema") not in (SCHEMA,SEMANTIC_SCHEMA):
                raise ValueError("unsupported parent archive schema")
            receipt=parent.get("receipt",{})
            if receipt.get("sha256")!=digest({k:v for k,v in parent.items() if k!="receipt"}):
                raise ValueError("parent archive integrity mismatch")
            # Parent status supplies no new authority. Every R1 claim is freshly
            # classified from the complete provided observations.
            rows=[]
            for claim in parent.get("claims",[]):
                rows.append({"claim_id":identifier(claim["claim_id"]),"family_id":claim["family_id"],
                             "expression_sha256":digest(claim["typed_relation"]),"typed_relation":deepcopy(claim["typed_relation"])})
            return {"parent_archive_sha256":_sha(receipt["sha256"]),"claims":rows}
        keys(parent,("parent_archive_sha256","claims"))
        _sha(parent["parent_archive_sha256"])
        if not isinstance(parent["claims"],list) or len(parent["claims"])>MAX_CLAIMS:
            raise ValueError("bounded parent claim references required")
        for claim in parent["claims"]:
            keys(claim,("claim_id","family_id","expression_sha256","typed_relation"))
            identifier(claim["claim_id"]);_sha(claim["expression_sha256"])
            if digest(claim["typed_relation"])!=claim["expression_sha256"]:raise ValueError("parent expression identity differs")
            if not isinstance(claim["family_id"],str) or len(claim["family_id"])>500:
                raise ValueError("invalid parent family reference")
        return deepcopy(parent)

    def _r1_scope(self):
        return {"implementation_scope":self.source,"domain_and_contract_scope":{
            "spec":self.spec,"temporal_contract":self.temporal_contract,"public_ir":self.public_ir},
            "semantic_policy":self.semantic_policy}

    def _r1_import(self,engine):
        from .claim_semantics import SEMANTIC_VERSION, semantic_claim_id, semantic_coordinate_only, validate_semantic_relation
        if len(engine.groups)>8:
            raise ValueError("narrow to at most eight source failure families")
        relations={};families={};scope=self._r1_scope()
        parent=self._derived_from or {"claims":[]}
        for family,group in sorted(engine.groups.items()):
            families[family]={"invariant":group["invariant"]}
            for rid,raw in sorted(engine.relations.items()):
                relation=validate_semantic_relation(raw,self.spec,self.semantic_policy)
                derived=[row["claim_id"] for row in parent["claims"]
                         if row["family_id"]==family and row["expression_sha256"]==digest(relation)]
                for kind in self.claim_kinds:
                    cid=semantic_claim_id(relation,kind,family,scope)
                    relations[cid]={"claim_id":cid,"family_id":family,"failure_family":family,
                        "typed_relation":relation,"expression":relation,"source_relation_id":rid,
                        "coordinate_only":semantic_coordinate_only(relation),"claim_kind":kind,
                        "semantic_version":SEMANTIC_VERSION,"semantic_policy":deepcopy(self.semantic_policy),
                        "derived_from":derived,"parent_archive_sha256":parent.get("parent_archive_sha256")}
        if len(relations)>self.semantic_policy["max_claims"]:
            raise ValueError("R1 semantic claim cap exceeded; no candidates were discarded")
        self._relations,self._families=relations,families
        self._source_evidence=deepcopy(engine.evidence)
        self._source_ids={event["evidence_id"]:event for event in self._source_evidence}
        self._r1_invalidate()

    def _r1_invalidate(self):
        self._claim_cache=None;self._semantic_rows_cache=None;self._semantic_rows_binding=None;self._prediction_cache={};self._r1_receipt_cache=None

    def _r1_result(self):
        # Replay validates the final derived snapshot and every fork hash. It
        # need not materialize discarded 63-MB return values between actions.
        return None if self._r1_replaying else self.snapshot()

    def _r1_observation_count(self):
        return len(self._source_evidence)+len(self._events)+sum(len(batch["observations"]) for batch in self._source_validation)

    def _r1_claim_view(self):
        if self._claim_cache is None:self._claim_cache=[self._claim(cid) for cid in sorted(self._relations)]
        return self._claim_cache

    def _r1_receipt_stamp(self):
        if self._r1_bound_scope!=digest({"scope":self._r1_scope(),"claim_kinds":self.claim_kinds}):
            raise ValueError("bound R1 implementation, Oracle, domain or claim kinds changed")
        return digest({"scope":self._r1_scope(),"journal":self._journal,"derived_from":self._derived_from,
                       "claim_kinds":self.claim_kinds,"frozen":self.frozen})

    def _r1_current_receipt(self):
        stamp=self._r1_receipt_stamp()
        if self._r1_receipt_cache is not None and self._r1_receipt_cache[0]==stamp:
            return self._r1_receipt_cache[1]
        return self.snapshot()["receipt"]["sha256"]

    def _r1_learn(self,evidence):
        from .claim_semantics import normalize_semantic_evidence
        self._open()
        if self.generation_id is not None:
            raise ValueError("resumed generations retain their frozen grammar and accept development receipts only")
        if not isinstance(evidence,list) or not evidence:
            raise ValueError("nonempty source observations required")
        pending=[];ids=set()
        for raw in evidence:
            event=normalize_semantic_evidence(raw,self.spec);eid=event["evidence_id"]
            if eid in self._source_ids:
                if self._source_ids[eid]!=event:raise ValueError("source evidence ID conflict")
                continue
            if eid in ids:raise ValueError("duplicate source evidence ID")
            ids.add(eid);pending.append(event)
        if not pending:return self._r1_result()
        events=self._source_evidence+pending
        if len(events)+len(self._events)+sum(len(batch["observations"]) for batch in self._source_validation)>self.semantic_policy["max_events"]:
            raise ValueError("R1 source observation cap exceeded; no rows were discarded")
        pool=list({canonical(event["inputs"]):event["inputs"] for event in events}.values())
        from .engine import DiscoveryEngine
        engine=DiscoveryEngine(self.spec,public_ir=self.public_ir,native_strategy=False,
            _pool=pool,pool_size=len(pool),semantic_policy=self.semantic_policy,claim_kinds=self.claim_kinds,
            **({"seed_relations":list({canonical(row["typed_relation"]):row["typed_relation"] for row in self._derived_from["claims"]}.values())} if self._derived_from else {}))
        for event in events:
            index=engine._index[canonical(event["inputs"])]
            if index not in engine._seen:engine._seen.add(index);engine.seen.append(index)
            engine.observe(event)
        self._r1_import(engine)
        self._journal.append({"action":"learn","evidence":deepcopy(pending)})
        return self._r1_result()

    def _r1_observation(self,value):
        return normalize_semantic_observation(value)

    def _r1_observe(self,event,*,trusted_observation=False):
        self._open()
        if trusted_observation is not True:
            raise PermissionError("reviewed development receipt requires trusted-host approval")
        value=self._r1_observation(event)
        key=canonical([value["origin"],value["implementation_sha256"],value["evidence"]["evidence_id"]])
        if key in self._observation_ids:
            if self._observation_ids[key]!=value:raise ValueError("development observation ID conflict")
            return self._r1_result()
        if self._r1_observation_count()>=self.semantic_policy["max_events"]:
            raise ValueError("bounded R1 additional observations required")
        self._events.append(value);self._observation_ids[key]=value
        self._journal.append({"action":"observe","observation":deepcopy(value)})
        self._r1_invalidate()
        return self._r1_result()

    def _r1_same_source(self,origin,implementation):
        return (implementation==self.source.get("implementation_sha256") and
                all(origin.get(name)==self.source.get(name) for name in ("oracle_id","oracle_sha256","lineage","semantics")))

    def _r1_rows(self):
        if self._semantic_rows_cache is not None:return self._semantic_rows_cache
        from .claim_semantics import measurements3
        predicates=[]
        def collect(relation):
            term=relation["term"]
            if term["kind"]=="compound":
                for child in term["expression"]["args"]:collect(child)
            elif term["kind"]=="ast" and term["expression"] not in predicates:predicates.append(term["expression"])
        for base in self._relations.values():collect(base["typed_relation"])
        rows=[];measured={}
        raw=[(self.spec,self.public_ir,self.source,event,None,"SOURCE") for event in self._source_evidence]
        for value in self._events:
            phase="SOURCE" if self._r1_same_source(value["origin"],value["implementation_sha256"]) else "CORROBORATION"
            raw.append((value["spec"],value["public_ir"],value["origin"],value["evidence"],value,phase))
        for batch in self._source_validation:
            for value in batch["observations"]:
                raw.append((value["spec"],value["public_ir"],value["origin"],value["evidence"],value,"SOURCE_VALIDATION"))
        for spec,ir,origin,event,receipt,phase in raw:
            token="source:"+event["evidence_id"] if receipt is None else receipt["receipt_sha256"]
            reasons=_scope_reasons(self.spec,None,self.public_ir,self.source,spec,None,ir,origin)
            if phase=="CORROBORATION" and not _independent(self.source,origin,origin.get("implementation_sha256")):
                reasons.append("independent-implementation-or-oracle-unestablished")
            cache_key=digest({"semantic_policy":self.semantic_policy,"spec":spec,"origin":origin,"inputs":event["inputs"]})
            if cache_key not in measured and not reasons:
                measured[cache_key]=measurements3(event["inputs"],spec,predicates)
            spec_sha=digest(spec)
            binding=(spec_sha,origin.get("implementation_sha256"),origin.get("oracle_id"),origin.get("oracle_sha256"),canonical(event["inputs"]))
            rows.append(dict(token=token,event=event,spec=spec,origin=origin,receipt=receipt,phase=phase,
                             reasons=reasons,measured=measured.get(cache_key),binding=binding,
                             label_key=canonical([origin.get("implementation_sha256"),spec_sha,event["inputs"]]),
                             origin_key=digest([origin,origin.get("implementation_sha256")])))
        self._semantic_rows_cache=rows
        self._semantic_rows_binding=digest([row["binding"] for row in rows])
        return rows

    def _r1_claim(self,cid):
        from .claim_semantics import classify, semantic_label, _relation_value, EMPIRICAL, SEMANTIC_VERSION
        base=deepcopy(self._relations[cid]);kind=base["claim_kind"];family=base["family_id"]
        cells={name:[] for name in ("TP","FP","FN","TN","UNKNOWN")}
        source_cells={name:[] for name in cells};validation_cells={name:[] for name in cells};corroboration_cells={name:[] for name in cells}
        supports=[];source_counter=[];c_counter=[];unknown=[];ignored=[];ind_pos=[];ind_neg=[]
        c_positive_origins=set();c_negative_origins=set();seen={};inconsistent=[];source_inconsistent=[];c_inconsistent=[];known_predictions=[]
        rows=self._r1_rows()
        # A warm authored profile showed repeated canonicalization dominating
        # this loop. The truth column is shared; classification/authority keys
        # still include kind, version, domain and each Oracle identity.
        column_key=("R1_TRUTH_COLUMN",SEMANTIC_VERSION,digest(self.semantic_policy),digest(base["typed_relation"]),self._semantic_rows_binding)
        if column_key not in self._prediction_cache:
            self._prediction_cache[column_key]=tuple(None if row["reasons"] else _relation_value(base["typed_relation"],row["measured"]) for row in rows)
        authority_key=("R1_KIND_COLUMN",kind,*column_key[1:])
        self._prediction_cache[authority_key]=self._prediction_cache[column_key]
        for row,predicted in zip(rows,self._prediction_cache[authority_key]):
            token=row["token"]
            if row["reasons"]:
                ignored.append({"evidence":token,"reasons":row["reasons"]});continue
            observed=semantic_label(row["event"],family)
            label_key=row["label_key"]
            if observed is not None and label_key in seen and seen[label_key]!=observed:
                inconsistent.append(token)
                (c_inconsistent if row["phase"]=="CORROBORATION" else source_inconsistent).append(token)
            if observed is not None:seen[label_key]=observed
            result=classify(predicted,observed,kind);cell=result["cell"]
            cells[cell].append(token)
            phase=row["phase"]
            destination=corroboration_cells if phase=="CORROBORATION" else source_cells
            destination[cell].append(token)
            if phase=="SOURCE_VALIDATION":validation_cells[cell].append(token)
            if phase!="CORROBORATION" and predicted is not None:known_predictions.append(predicted)
            if cell=="UNKNOWN":unknown.append(token)
            if result["supports"]:supports.append(token)
            if result["refutes"]:(c_counter if phase=="CORROBORATION" else source_counter).append(token)
            if phase=="CORROBORATION":
                origin_key=row["origin_key"]
                if cell=="TP":ind_pos.append(token);c_positive_origins.add(origin_key)
                if cell=="TN":ind_neg.append(token);c_negative_origins.add(origin_key)
        tp=len(source_cells["TP"]);trivial=not known_predictions or len(set(known_predictions))<2
        source_status=("INCONSISTENT_EVIDENCE" if source_inconsistent else "CONTRADICTED" if source_counter else
                       "EMPIRICAL_CANDIDATE" if kind==EMPIRICAL and tp else "OBSERVED_WITHIN_SOURCE" if tp else "HYPOTHESIS")
        contrastive=c_positive_origins & c_negative_origins
        c_status="INCONSISTENT_EVIDENCE" if c_inconsistent else "CONTRADICTED" if c_counter else "SUPPORTED_WITHIN_SCOPE" if contrastive else "NOT_ESTABLISHED"
        validation_status=("NOT_EXECUTED" if not self._source_validation else "MEASURED_EMPIRICAL" if kind==EMPIRICAL else
            "CONTRADICTED" if any(classify(cell=="TP" or cell=="FP",cell=="TP" or cell=="FN",kind)["refutes"] and values
                                      for cell,values in validation_cells.items() if cell!="UNKNOWN") else
            "SUPPORTED_WITHIN_SOURCE_BATCH" if validation_cells["TP"] else "NO_POSITIVE_SUPPORT_IN_SOURCE_BATCH")
        useful=self._r1_utility_status(cid)
        eligible=source_status in ("OBSERVED_WITHIN_SOURCE","EMPIRICAL_CANDIDATE") and tp>0 and not trivial and not base["coordinate_only"]
        qualified=eligible and c_status=="SUPPORTED_WITHIN_SCOPE" and (kind!=EMPIRICAL or useful=="UTILITY_SUPPORTED")
        status="CONTRADICTED" if source_status=="CONTRADICTED" else "SUPPORTED_WITHIN_SCOPE" if qualified else "HYPOTHESIS"
        base.update(status=status,source_claim_status=source_status,source_validation_status=validation_status,
            corroboration_status=c_status,target_applicability="NOT_ASSESSED",transfer_validation_status="NOT_EXECUTED_READINESS_BLOCKED",
            supporting_evidence=supports,contradicting_evidence=source_counter+c_counter,
            counterevidence={"source":source_counter,"corroboration":c_counter},unknown_evidence=unknown,
            confusion={cell:len(values) for cell,values in cells.items()},confusion_evidence=cells,
            source_statistics={cell:len(values) for cell,values in source_cells.items()},
            source_validation_statistics={cell:len(values) for cell,values in validation_cells.items()},
            corroboration_statistics={cell:len(values) for cell,values in corroboration_cells.items()},
            independent_positive=ind_pos,independent_negative=ind_neg,independent_contrastive_origins=sorted(contrastive),
            ignored_evidence=ignored,inconsistent_evidence=inconsistent,positive_support=tp,trivial=trivial,
            utility_status=useful,competing_group=family,implementation_scope=deepcopy(self.source),
            domain_and_contract_scope={"spec":deepcopy(self.spec),"temporal_contract":None,"public_ir":deepcopy(self.public_ir)},
            source_scope={"spec":deepcopy(self.spec),"temporal_contract":None,"public_ir":deepcopy(self.public_ir),"origin":deepcopy(self.source)},
            validation_scope={"meaning":"OBSERVED_DEVELOPMENT_ONLY_NOT_GLOBAL_PROOF","source_validation_batches":len(self._source_validation),
                              "observations_are_independent_statistical_samples":False},
            provenance={"source":deepcopy(self.source),"parent_archive_sha256":base["parent_archive_sha256"],"new_independent_discovery":False},
            uncertainty={"causality":"UNKNOWN","target_recurrence":"UNKNOWN","scope":"OBSERVED_DEVELOPMENT_ONLY"})
        if any(cid in row["claim_ids"] for row in self._utility_journal):
            base["utility_attribution"]="ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT"
        if inconsistent:
            base["inconsistent_evidence_by_scope"]={"source":source_inconsistent,"corroboration":c_inconsistent}
        return base

    def _r1_utility_status(self,cid):
        rows=[row for row in self._utility_journal if cid in row["claim_ids"]]
        if not rows:return "NOT_VALIDATED"
        latest=rows[-1];b,g=latest["baseline"],latest["guided"]
        supported=(latest["selection_changed"] and latest["novel_guided_candidates"]>0 and g["found"] and latest["first_discovery_new_guided"] and
            g["target_calls"]+g["oracle_calls"] <= (b["target_calls"]+b["oracle_calls"])*latest["criteria"]["max_call_ratio"] and
            g["wall_seconds"] <= b["wall_seconds"]*latest["criteria"]["max_wall_ratio"])
        return "UTILITY_SUPPORTED" if supported else "NO_UTILITY_DEMONSTRATED"

    def source_guidance(self,spec,*,target_provenance,purpose="DEVELOPMENT_VALIDATION",allow_unvalidated_empirical=False):
        from .claim_semantics import EMPIRICAL
        if self.semantic_policy is None:raise ValueError("explicit R1 semantic archive required for Source guidance")
        if not self.frozen:raise ValueError("Source planning requires a frozen archive")
        self._r1_receipt_stamp()
        if purpose!="DEVELOPMENT_VALIDATION" or type(allow_unvalidated_empirical) is not bool:
            raise ValueError("Source-only development purpose and explicit empirical policy required")
        target=validate_provenance(target_provenance);spec=validate_spec(spec)
        reasons=_scope_reasons(self.spec,None,self.public_ir,self.source,spec,None,self.public_ir,target)
        if not self._r1_same_source(target,target.get("implementation_sha256")):reasons.append("different-source-implementation-or-oracle")
        selected=[];decisions=[]
        for claim in self._r1_claim_view():
            why=list(reasons)
            if claim["source_claim_status"] not in ("OBSERVED_WITHIN_SOURCE","EMPIRICAL_CANDIDATE"):why.append("source-claim-not-supported")
            if claim["positive_support"]<1:why.append("no-positive-observed-support")
            if claim["trivial"]:why.append("trivial-or-vacuous-rule")
            if claim["coordinate_only"]:why.append("coordinate-only-rule")
            if claim["claim_kind"]==EMPIRICAL and claim["utility_status"]!="UTILITY_SUPPORTED" and not allow_unvalidated_empirical:
                why.append("empirical-utility-not-validated")
            status="SOURCE_DEVELOPMENT_CANDIDATE" if not why else "SOURCE_GUIDANCE_BLOCKED"
            if not why:
                value=deepcopy(claim);value.update(status="EMPIRICAL_TEST_CANDIDATE" if claim["claim_kind"]==EMPIRICAL and claim["utility_status"]!="UTILITY_SUPPORTED" else status,
                    qualified=False,target_applicability="SAME_SOURCE_DEVELOPMENT_ONLY")
                selected.append(value)
            decisions.append({"claim_id":claim["claim_id"],"status":status,"reasons":sorted(set(why))})
        return {"status":"SOURCE_DEVELOPMENT_GUIDANCE" if selected else "APPLICABILITY_UNKNOWN","claims":selected,"decisions":decisions,
                "source_archive_sha256":self._r1_current_receipt(),"final_feedback_allowed":False,
                "purpose":purpose,"independent_transfer_authorized":False,"allow_unvalidated_empirical":allow_unvalidated_empirical}

    def _r1_qualify(self,target_spec,*,target_provenance=None,target=None,temporal_contract=None,public_ir=None):
        from .claim_semantics import EMPIRICAL
        if not self.frozen:raise ValueError("probing requires a frozen archive")
        if target is not None and target_provenance is not None:raise ValueError("provide one target provenance")
        origin=validate_provenance(target if target is not None else target_provenance)
        spec,contract,ir=_context(target_spec,temporal_contract,public_ir)
        reasons=_scope_reasons(self.spec,None,self.public_ir,self.source,spec,contract,ir,origin)
        if not _independent(self.source,origin,origin.get("implementation_sha256")):reasons.append("target-implementation-independence-unestablished")
        if any(v["implementation_sha256"]==origin.get("implementation_sha256") for v in self._events):reasons.append("target-seen-in-development")
        qualified=[];decisions=[]
        for claim in self._r1_claim_view():
            why=list(reasons)
            def has_ast(relation):
                term=relation["term"]
                return term["kind"]=="ast" or term["kind"]=="compound" and any(has_ast(arg) for arg in term["expression"]["args"])
            if has_ast(claim["typed_relation"]):
                from .transfer import validate_transfer
                if validate_transfer(self.spec,spec,self.public_ir,ir)["status"]!="APPLICABLE_FOR_PROBING":
                    why.append("approved-AST-graph-correspondence-unestablished")
            if claim["source_claim_status"] in ("CONTRADICTED","INCONSISTENT_EVIDENCE"):why.append("source-counterevidence")
            if claim["corroboration_status"]!="SUPPORTED_WITHIN_SCOPE":why.append("independent-contrastive-support-insufficient")
            if claim["coordinate_only"] or claim["trivial"] or not claim["positive_support"]:why.append("vacuous-coordinate-or-unsupported-rule")
            if claim["claim_kind"]==EMPIRICAL and claim["utility_status"]!="UTILITY_SUPPORTED":why.append("empirical-utility-not-validated")
            status="QUALIFIED_FOR_PROBING" if not why else "CONTRADICTED" if claim["source_claim_status"]=="CONTRADICTED" or claim["corroboration_status"]=="CONTRADICTED" else "APPLICABILITY_UNKNOWN"
            if not why:
                value=deepcopy(claim);value.update(status=status,target_applicability="REVIEWED_CONTRACT_PROBES_ONLY")
                qualified.append(value)
            decisions.append({"claim_id":claim["claim_id"],"status":status,"reasons":sorted(set(why))})
        return {"status":"QUALIFIED_FOR_PROBING" if qualified else "APPLICABILITY_UNKNOWN","claims":qualified,"decisions":decisions,
            "source_archive_sha256":self._r1_current_receipt(),"final_feedback_allowed":False,"failure_recurrence":"UNKNOWN",
            "target_seen_in_development":any(v["implementation_sha256"]==origin.get("implementation_sha256") for v in self._events),
            "authority":"REVIEWED_HOST_ATTESTATION_NOT_CRYPTOGRAPHIC_INDEPENDENCE_PROOF"}

    def _r1_parent_binding(self,sha):
        _sha(sha)
        fork=next((row for row in reversed(self._journal) if row["action"]=="fork"),None)
        if fork is None or fork["parent_sha256"]!=sha:raise ValueError("development validation must identify the complete frozen fork parent")

    def record_source_validation(self,observations,*,frozen_before_sha256,trusted_observation=False,batch_receipt_sha256=None):
        self._open()
        if self.semantic_policy is None or trusted_observation is not True:raise PermissionError("explicit R1 trusted Source validation required")
        self._r1_parent_binding(frozen_before_sha256)
        if not isinstance(observations,list) or not observations:raise ValueError("nonempty additional Source batch required")
        values=[self._r1_observation(value) for value in observations]
        if self._r1_observation_count()+len(values)>self.semantic_policy["max_events"]:
            raise ValueError("R1 Source development capacity exceeded; no observations were dropped")
        used={canonical([row["evidence"]["evidence_id"],row["origin"]]) for batch in self._source_validation for row in batch["observations"]}
        for value in values:
            if not self._r1_same_source(value["origin"],value["implementation_sha256"]) or _scope_reasons(self.spec,None,self.public_ir,self.source,value["spec"],None,value["public_ir"],value["origin"]):
                raise ValueError("Source validation cannot substitute an independent or differently scoped implementation")
            token=canonical([value["evidence"]["evidence_id"],value["origin"]])
            if token in used:raise ValueError("Source validation observation identity already consumed")
            used.add(token)
        batch={"frozen_before_sha256":frozen_before_sha256,"observations":values,
               "batch_receipt_sha256":_sha(batch_receipt_sha256) if batch_receipt_sha256 is not None else digest(values)}
        self._source_validation.append(batch);self._journal.append({"action":"source_validation",**deepcopy(batch)})
        self._r1_invalidate();return self._r1_result()

    def record_guidance_utility(self,receipt,*,trusted_host=False):
        import math
        from .claim_semantics import SEMANTIC_VERSION
        self._open()
        if self.semantic_policy is None or trusted_host is not True:raise PermissionError("reviewed R1 host utility receipt required")
        fields=("schema","semantic_version","source_archive_sha256","validation_scope","comparison_contract_sha256","batch_receipt_sha256",
                "claim_ids","baseline","guided","selection_changed","novel_guided_candidates","first_discovery_new_guided","batch_attribution","criteria","receipt_sha256")
        keys(receipt,fields)
        if (receipt["schema"]!="tomolab-e8r1-guidance-utility-v1" or receipt["semantic_version"]!=SEMANTIC_VERSION or
                receipt["validation_scope"]!="SOURCE_DEVELOPMENT_ONLY" or receipt["receipt_sha256"]!=digest({k:v for k,v in receipt.items() if k!="receipt_sha256"})):
            raise ValueError("invalid Source utility receipt contract")
        self._r1_parent_binding(receipt["source_archive_sha256"])
        for name in ("comparison_contract_sha256","batch_receipt_sha256","receipt_sha256"):_sha(receipt[name])
        if not any(batch["batch_receipt_sha256"]==receipt["batch_receipt_sha256"] for batch in self._source_validation):
            raise ValueError("utility requires a separately recorded Source validation batch")
        if not isinstance(receipt["claim_ids"],list) or len(receipt["claim_ids"])>64 or len(set(receipt["claim_ids"]))!=len(receipt["claim_ids"]) or any(cid not in self._relations for cid in receipt["claim_ids"]):
            raise ValueError("utility receipt must identify actual bounded claim IDs")
        if type(receipt["selection_changed"]) is not bool:raise ValueError("explicit candidate change required")
        if type(receipt["first_discovery_new_guided"]) is not bool or receipt["batch_attribution"]!="ASSOCIATED_METHOD_BATCH_NOT_INDIVIDUAL_RULE_CAUSAL_EFFECT":
            raise ValueError("explicit new-guided first discovery and batch-only attribution required")
        integer(receipt["novel_guided_candidates"],0,4096)
        for name in ("baseline","guided"):
            result=receipt[name];keys(result,("found","target_calls","oracle_calls","wall_seconds"))
            if type(result["found"]) is not bool:raise ValueError("explicit observed discovery required")
            integer(result["target_calls"],0,10**9);integer(result["oracle_calls"],0,10**9)
            if result["found"] and min(result["target_calls"],result["oracle_calls"])<1:raise ValueError("a discovery needs actual Target and Oracle calls")
            if type(result["wall_seconds"]) not in (float,int) or not math.isfinite(result["wall_seconds"]) or result["wall_seconds"]<0:raise ValueError("finite measured wall time required")
        keys(receipt["criteria"],("max_wall_ratio","max_call_ratio"))
        for value in receipt["criteria"].values():
            if type(value) not in (float,int) or not math.isfinite(value) or value<0:raise ValueError("finite preregistered utility criteria required")
        if receipt["first_discovery_new_guided"] and (not receipt["guided"]["found"] or not receipt["selection_changed"] or receipt["novel_guided_candidates"]<1 or not receipt["claim_ids"]):
            raise ValueError("new-guided discovery lacks a changed executed claim-bound candidate")
        if any(row["comparison_contract_sha256"]==receipt["comparison_contract_sha256"] and row["batch_receipt_sha256"]==receipt["batch_receipt_sha256"] for row in self._utility_journal):
            raise ValueError("utility comparison batch was already consumed")
        self._utility_journal.append(deepcopy(receipt));self._journal.append({"action":"guidance_utility","receipt":deepcopy(receipt)})
        self._r1_invalidate();return self._r1_result()

    def _r1_snapshot(self):
        value={"schema":SEMANTIC_SCHEMA,"spec":deepcopy(self.spec),"temporal_contract":None,"public_ir":deepcopy(self.public_ir),
            "source":deepcopy(self.source),"semantic_policy":deepcopy(self.semantic_policy),"claim_kinds":deepcopy(self.claim_kinds),
            "derived_from":deepcopy(self._derived_from),"journal":deepcopy(self._journal),"claims":self.claims(),"frozen":self.frozen,
            "generation_id":self.generation_id,"competing_groups":{family:sorted(cid for cid,c in self._relations.items() if c["family_id"]==family) for family in sorted(self._families)},
            "source_observations":len(self._source_evidence),"independent_observations":len(self._events),
            "source_validation_observations":sum(len(v["observations"]) for v in self._source_validation),
            "source_validation_journal":deepcopy(self._source_validation),"utility_journal":deepcopy(self._utility_journal),"final_feedback_allowed":False}
        value["receipt"]={"sha256":digest(value),"authenticity":"REVIEWED_HOST_ATTESTATION_REQUIRED"}
        if self.frozen:self._r1_receipt_cache=(self._r1_receipt_stamp(),value["receipt"]["sha256"])
        return value

    @classmethod
    def _r1_restore_snapshot(cls,snapshot):
        fields=("schema","spec","temporal_contract","public_ir","source","semantic_policy","claim_kinds","derived_from","journal","claims","frozen",
            "generation_id","competing_groups","source_observations","independent_observations","source_validation_observations","source_validation_journal","utility_journal","final_feedback_allowed","receipt")
        keys(snapshot,fields)
        if snapshot["schema"]!=SEMANTIC_SCHEMA or type(snapshot["frozen"]) is not bool or snapshot["final_feedback_allowed"] is not False:
            raise ValueError("invalid R1 snapshot contract")
        keys(snapshot["receipt"],("sha256","authenticity"))
        if snapshot["receipt"]["authenticity"]!="REVIEWED_HOST_ATTESTATION_REQUIRED" or snapshot["receipt"]["sha256"]!=digest({k:v for k,v in snapshot.items() if k!="receipt"}):raise ValueError("R1 snapshot receipt mismatch")
        if not isinstance(snapshot["journal"],list) or len(snapshot["journal"])>2048:raise ValueError("bounded R1 journal required")
        archive=cls(snapshot["spec"],source=snapshot["source"],public_ir=snapshot["public_ir"],semantic_policy=snapshot["semantic_policy"],claim_kinds=snapshot["claim_kinds"],derived_from=snapshot["derived_from"])
        archive._r1_replaying=True
        for row in snapshot["journal"]:
            action=row.get("action")
            if action=="learn":keys(row,("action","evidence"));archive.learn(row["evidence"])
            elif action=="observe":keys(row,("action","observation"));archive.observe(row["observation"],trusted_observation=True)
            elif action=="import":
                keys(row,("action","snapshot"))
                if archive._journal:raise ValueError("engine import is allowed only at archive genesis")
                archive=cls.from_engine_snapshot(row["snapshot"],archive.source)
                archive._r1_replaying=True
            elif action=="freeze":keys(row,("action",));archive.freeze()
            elif action=="fork":
                keys(row,("action","generation_id","parent_sha256"));archive=archive.fork(row["generation_id"])
                if archive._journal[-1]!=row:raise ValueError("R1 fork parent mismatch")
            elif action=="source_validation":
                keys(row,("action","frozen_before_sha256","observations","batch_receipt_sha256"));archive.record_source_validation(row["observations"],frozen_before_sha256=row["frozen_before_sha256"],trusted_observation=True,batch_receipt_sha256=row["batch_receipt_sha256"])
            elif action=="guidance_utility":keys(row,("action","receipt"));archive.record_guidance_utility(row["receipt"],trusted_host=True)
            else:raise ValueError("unsupported R1 archive journal action")
        archive._r1_replaying=False
        if canonical(archive.snapshot())!=canonical(snapshot):raise ValueError("R1 derived state is inconsistent with its complete journal")
        return archive
