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
    def __init__(self, spec, *, source=None, provenance=None, temporal_contract=None, public_ir=None):
        if source is not None and provenance is not None:
            raise ValueError("provide one source provenance")
        self.spec,self.temporal_contract,self.public_ir=_context(spec,temporal_contract,public_ir)
        self.source=validate_provenance(source if source is not None else provenance)
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
    def from_failure_log(cls, spec, evidence, provenance, *, temporal_contract=None, public_ir=None):
        archive=cls(spec,source=provenance,temporal_contract=temporal_contract,public_ir=public_ir)
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
        archive=cls(engine.spec,source=provenance,temporal_contract=getattr(engine,"temporal_contract",None),public_ir=engine.public_ir)
        archive._import(engine)
        archive._journal.append({"action":"import","snapshot":deepcopy(snapshot)})
        return archive

    def _open(self):
        if self.frozen:
            raise ValueError("frozen knowledge rejects learning and final feedback")

    def _import(self, engine):
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
        parent=self.snapshot()["receipt"]["sha256"]
        child=deepcopy(self)
        child._journal.append({"action":"fork","generation_id":generation_id,"parent_sha256":parent})
        child.frozen=False
        return child

    def snapshot(self):
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
        if len(encoded)>8*1024*1024:
            raise ValueError("knowledge snapshot exceeds eight MiB")
        # Bind validation and cache eligibility to the exact bytes used by the
        # key. The caller may mutate its dictionary while replay is in flight.
        # A canonical JSON round trip removes every shared mutable reference.
        captured=json.loads(encoded)
        key=(cls,VALIDATION_CACHE_VERSION,encoded)
        cached=None
        with _VALIDATION_CACHE_LOCK:
            if captured.get("frozen") is True and key in _VALIDATED_ARCHIVES:
                _VALIDATED_ARCHIVES.move_to_end(key)
                cached=_VALIDATED_ARCHIVES[key]
        if cached is not None:
            return deepcopy(cached)
        archive=cls._restore_snapshot(captured)
        if archive.frozen:
            cached=deepcopy(archive)
            with _VALIDATION_CACHE_LOCK:
                _VALIDATED_ARCHIVES[key]=cached
                while (len(_VALIDATED_ARCHIVES)>_VALIDATION_CACHE_ENTRIES or
                       sum(len(k[2]) for k in _VALIDATED_ARCHIVES)>_VALIDATION_CACHE_BYTES):
                    _VALIDATED_ARCHIVES.popitem(last=False)
        return archive

    @classmethod
    def _restore_snapshot(cls, snapshot):
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
