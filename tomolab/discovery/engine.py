"""Counterevidence-guided structural search over a real Hypothesis input pool."""
from copy import deepcopy
from collections import Counter

from .features import diversity_descriptor, grammar, holds, measurements, relation_id, transferable, validate_relation
from .hypothesis_adapter import generate_pool
from .schema import canonical, digest, identifier, integer, keys, normalize_evidence, type_subset, validate_inputs, validate_spec
from .predicates import predicate_roles, validate_predicate, validate_public_ir

SNAPSHOT_SCHEMA = "tomolab-discovery-snapshot-v2"
SEMANTIC_SNAPSHOT_SCHEMA = "tomolab-discovery-snapshot-v3"


def family_of(evidence):
    return evidence["invariant"]+"/"+evidence["category"]+"/"+evidence["signature"]


class DiscoveryEngine:
    def __init__(self,spec,*,seed=7,strategy="integrated",pool_size=512,seed_candidates=None,public_ir=None,
                 solver="enumeration",native_strategy=None,oracle_costs=None,_pool=None,
                 claim_kinds=None,semantic_policy=None,seed_relations=None):
        self.spec = validate_spec(spec)
        self.seed = integer(seed,0,2**32-1)
        self.pool_size = integer(pool_size,1,4096)
        if strategy not in ("integrated","hypothesis"):
            raise ValueError("strategy must be integrated or hypothesis")
        self.strategy = strategy
        if solver not in ("enumeration","z3"):
            raise ValueError("solver must be enumeration or z3")
        if native_strategy is not None and type(native_strategy) is not bool:
            raise ValueError("native_strategy must be Boolean")
        self.solver=solver
        self.native_strategy=(_pool is None) if native_strategy is None else native_strategy
        self.public_ir=validate_public_ir(public_ir,self.spec) if public_ir is not None else None
        self.public_predicates=deepcopy((self.public_ir or {}).get("predicates",[]))
        self.predicates=[]
        for predicate in self.public_predicates:
            for option in (predicate,{"op":"not","args":[predicate]}):
                if option not in self.predicates:
                    self.predicates.append(validate_predicate(option,self.spec))
        if oracle_costs is None:
            oracle_costs=[]
        if not isinstance(oracle_costs,list) or len(oracle_costs)>128:
            raise ValueError("bounded public static Oracle costs required")
        self.oracle_costs=[]
        self._costs={}
        import math
        for hint in oracle_costs:
            keys(hint,("inputs","cost"))
            point=validate_inputs(hint["inputs"],self.spec)
            cost=hint["cost"]
            if type(cost) not in (int,float) or not math.isfinite(cost) or not 0<cost<=1000000:
                raise ValueError("cost must be a positive public static number")
            key=canonical(point)
            if key in self._costs:
                raise ValueError("duplicate cost hint")
            self._costs[key]=cost
            self.oracle_costs.append({"inputs":point,"cost":cost})
        if seed_candidates is None:
            seed_candidates=[]
        if not isinstance(seed_candidates,list) or len(seed_candidates)>64:
            raise ValueError("at most 64 approved symbolic seed candidates")
        self.seed_candidates = [validate_inputs(x,self.spec) for x in seed_candidates]
        generated = generate_pool(self.spec,seed=seed,size=pool_size) if _pool is None else _pool
        if not isinstance(generated,list) or not 1 <= len(generated) <= 4096:
            raise ValueError("candidate pool empty or too large")
        self.pool=[]
        self._index={}
        for raw in (self.seed_candidates+generated if _pool is None else generated):
            point=validate_inputs(raw,self.spec)
            key=canonical(point)
            if key not in self._index:
                self._index[key]=len(self.pool)
                self.pool.append(point)
        if len(self.pool)>4096:
            raise ValueError("seed candidates exceed total pool cap")
        self.initial_pool=deepcopy(self.pool)
        self.pool_events=[]
        self.query_metrics={"native_rounds":0,"native_attempts":0,"native_duplicate_rejections":0,
                            "native_constraint_rejections":0,"solver_calls":0,"solver_sat":0}
        self._semantic = claim_kinds is not None or semantic_policy is not None
        self.claim_kinds = self.semantic_policy = None
        self.seed_relations = None
        if self._semantic:
            from .claim_semantics import normalize_claim_kinds, normalize_policy, semantic_grammar, validate_semantic_relation
            self.claim_kinds = normalize_claim_kinds(claim_kinds)
            self.semantic_policy = normalize_policy(semantic_policy)
            if seed_relations is not None:
                if not isinstance(seed_relations,list):
                    raise ValueError("frozen atomic relation list required")
                self.seed_relations=[validate_semantic_relation(r,self.spec,self.semantic_policy) for r in seed_relations]
                for relation in self.seed_relations:
                    term=relation["term"]
                    if term["kind"]=="ast" and term["expression"] not in self.predicates:
                        self.predicates.append(deepcopy(term["expression"]))
            self.measured,self.relations,self.masks,self.unknown_masks = semantic_grammar(
                self.pool,self.spec,self.predicates,self.semantic_policy,self.seed_relations)
        else:
            if seed_relations is not None:
                raise ValueError("frozen relation seeds require explicit R1 semantics")
            self.measured,self.relations,self.masks=grammar(self.pool,self.spec,self.predicates)
        self._prospective={relation_id({"term":{"kind":"ast","roles":sorted(predicate_roles(p)),"expression":p},"operator":"eq","value":1})
                           for p in self.public_predicates}
        self.seen=[]
        self._seen=set()
        self.evidence=[]
        self._ids=set()
        self.groups={}
        self.contradictions=[]
        self.history=[]
        self.prior=None
        self.gate=None
        self.version=0
        self.frozen=False
        self.inconsistent=False

    def _append_candidate(self,point,source):
        point=validate_inputs(point,self.spec)
        key=canonical(point)
        if key in self._index:
            return self._index[key]
        if len(self.pool)>=4096:
            return None
        index=len(self.pool)
        self._index[key]=index
        self.pool.append(point)
        if self._semantic:
            from .claim_semantics import measurements3
            row=measurements3(point,self.spec,self.predicates)
        else:
            row=measurements(point,self.spec,self.predicates)
        self.measured.append(row)
        for rid,relation in self.relations.items():
            if self._semantic:
                from .claim_semantics import relation_prediction
                prediction=relation_prediction(relation,point,self.spec,self.semantic_policy,measured=row)
                if prediction is None:self.unknown_masks[rid]|=1<<index
            else:
                prediction=holds(relation,row)
            if prediction is True:
                self.masks[rid]|=1<<index
        self.pool_events.append({"inputs":deepcopy(point),"source":source})
        return index

    def _candidate_ids(self):
        if self._semantic:
            return self._semantic_candidate_ids()
        raw=sorted({rid for group in self.groups.values() for rid in group["remaining"]}) if self.groups else sorted(self._prospective)
        # Equivalent truth columns have one vote; provenance and all alternative
        # syntax remain available in the version space and archive.
        by_mask={}
        for rid in sorted(raw,key=lambda r:(self.relations[r]["term"]["kind"]!="ast",r)):
            by_mask.setdefault(self.masks[rid],rid)
        return sorted(by_mask.values())

    def _predicate_for(self,rid):
        relation=self.relations[rid]
        term=relation["term"]
        if self._semantic and term["kind"]=="compound":
            # Public relation composition is useful for finite-pool ordering.
            # Do not weaken the old integer Solver's supported typed fragment.
            return None
        if term["kind"]=="ast":
            return term["expression"]
        variables=[{"var":role} for role in term["roles"]]
        kind=term["kind"]
        expression=variables[0] if kind=="value" else ({"op":{"absolute":"abs","length":"len","total":"sum","minimum":"min","maximum":"max"}[kind],"args":[variables[0]]}
                    if kind in {"absolute","length","total","minimum","maximum"} else
                    {"op":{"sum":"add","difference":"sub","absolute_difference":"abs"}.get(kind,"unsupported"),"args":variables})
        if kind=="absolute_difference":
            expression={"op":"abs","args":[{"op":"sub","args":variables}]}
        predicate={"op":relation["operator"],"left":expression,"right":relation["value"]}
        try:
            return validate_predicate(predicate,self.spec)
        except ValueError:
            return None

    def _cost(self,index):
        return self._costs.get(canonical(self.pool[index]),1)

    def _install_prior(self,prior,gate):
        if self._semantic:
            raise ValueError("R1 priors require the kind-checked KnowledgeArchive qualification path")
        if not isinstance(prior,list) or len(prior)>64:
            raise ValueError("invalid prior groups")
        if not isinstance(gate,dict) or gate.get("status") not in ("APPLICABLE_FOR_PROBING","UNKNOWN"):
            raise ValueError("invalid transfer gate")
        keys(gate,("status","reasons","mapping","source_snapshot_sha256","failure_recurrence","excluded_coordinate_constraints",
                   "claim","target_counterevidence_ids","target_contradictions","solver_checks"))
        if gate["failure_recurrence"]!="UNKNOWN" or gate["claim"]!="declared typed role, contract and graph correspondence permit probes; not a proof of repeated defects":
            raise ValueError("invalid transfer uncertainty claim")
        if not isinstance(gate["reasons"],list) or len(gate["reasons"])>32 or any(not isinstance(r,str) or len(r)>200 for r in gate["reasons"]):
            raise ValueError("invalid transfer reasons")
        if not isinstance(gate["mapping"],dict) or len(gate["mapping"])>6:
            raise ValueError("invalid transfer mapping")
        for name in [*gate["mapping"],*gate["mapping"].values()]: identifier(name)
        if not isinstance(gate["source_snapshot_sha256"],str) or len(gate["source_snapshot_sha256"])!=64 or any(c not in "0123456789abcdef" for c in gate["source_snapshot_sha256"]):
            raise ValueError("invalid transfer source digest")
        integer(gate["excluded_coordinate_constraints"],0,262144)
        if not isinstance(gate["target_counterevidence_ids"],list) or len(gate["target_counterevidence_ids"])>256:
            raise ValueError("invalid target counterevidence references")
        for evidence_id in gate["target_counterevidence_ids"]: identifier(evidence_id)
        if not isinstance(gate["target_contradictions"],list) or len(gate["target_contradictions"])>262144:
            raise ValueError("invalid target contradictions")
        for row in gate["target_contradictions"]:
            keys(row,("constraint_id","evidence_ids","reason")); identifier(row["constraint_id"])
            if row["reason"] not in {"target-development-counterexample","target-domain-unsatisfiable"} or not isinstance(row["evidence_ids"],list) or len(row["evidence_ids"])>256:
                raise ValueError("invalid target contradiction")
            for evidence_id in row["evidence_ids"]:
                identifier(evidence_id)
                if evidence_id not in gate["target_counterevidence_ids"]: raise ValueError("target contradiction reference missing")
        if not isinstance(gate["solver_checks"],list) or len(gate["solver_checks"])>262144:
            raise ValueError("invalid transfer solver checks")
        for row in gate["solver_checks"]:
            keys(row,("constraint_id","status")); identifier(row["constraint_id"])
            if row["status"] not in {"SAT","UNSAT","UNKNOWN","UNSUPPORTED"}: raise ValueError("invalid solver status")
        if prior and (gate["status"]!="APPLICABLE_FOR_PROBING" or gate.get("reasons")!=[]):
            raise ValueError("unapproved prior must not be installed")
        if len(canonical(prior))>2_000_000:
            raise ValueError("prior exceeds bounded transfer payload")
        families=set()
        for group in prior:
            keys(group,("family_id","invariant","relations","source_evidence"))
            if not isinstance(group["family_id"],str) or len(group["family_id"])>500 or group["family_id"] in families:
                raise ValueError("invalid or duplicate prior family")
            families.add(group["family_id"])
            if group["invariant"] not in self.spec["contract"]["invariants"] or not isinstance(group["relations"],list) or len(group["relations"])>4096:
                raise ValueError("invalid prior invariant or relation count")
            if not isinstance(group["source_evidence"],list) or len(group["source_evidence"])>64:
                raise ValueError("invalid source evidence references")
            for source in group["source_evidence"]:
                keys(source,("source_snapshot","evidence_ids"))
                if not isinstance(source["source_snapshot"],str) or len(source["source_snapshot"])!=64 or any(c not in "0123456789abcdef" for c in source["source_snapshot"]):
                    raise ValueError("invalid source snapshot reference")
                if source["source_snapshot"]!=gate.get("source_snapshot_sha256"):
                    raise ValueError("source evidence and gate disagree")
                if not isinstance(source["evidence_ids"],list) or len(source["evidence_ids"])>8192:
                    raise ValueError("invalid source evidence list")
                for evidence_id in source["evidence_ids"]:
                    identifier(evidence_id)
            remaining=set()
            for relation in group["relations"]:
                validate_relation(relation)
                if not transferable(relation):
                    raise ValueError("absolute numeric coordinates cannot be transferred")
                if not set(relation["term"]["roles"]) <= {v["role"] for v in self.spec["inputs"]}:
                    raise ValueError("prior role not present")
                if relation["term"]["kind"]=="ast":
                    predicate=validate_predicate(relation["term"]["expression"],self.spec)
                    if predicate not in self.predicates:
                        self.predicates.append(predicate)
                        self.measured=[measurements(point,self.spec,self.predicates) for point in self.pool]
                rid=relation_id(relation)
                self.relations[rid]=deepcopy(relation)
                self.masks[rid]=sum(1<<i for i,row in enumerate(self.measured) if holds(relation,row))
                remaining.add(rid)
            self.groups[group["family_id"]]={"invariant":group["invariant"],"remaining":remaining,"support":[],
                                             "source_evidence":deepcopy(group["source_evidence"])}
        self.prior=deepcopy(prior)
        self.gate=deepcopy(gate)

    def propose(self):
        native_indices=[]
        if self.native_strategy and len(self.seen)%8==0 and len(self.pool)<4096:
            from .hypothesis_adapter import guided_candidates
            ids=self._candidate_ids()
            predicates=[p for p in (self._predicate_for(rid) for rid in ids[:16]) if p is not None]
            if not self.groups:
                predicates=deepcopy(self.public_predicates)
            if self.strategy=="hypothesis" or self.inconsistent:
                predicates=[]
            generated=guided_candidates(self.spec,predicates=predicates,excluded=self.pool,
                                        seed=(self.seed+len(self.seen)*7919)%2**32,size=4,max_examples=96,
                                        relation_mode="disagreement" if len(predicates)>=2 else "any")
            self.query_metrics["native_rounds"]+=1
            self.query_metrics["native_attempts"]+=generated["attempts"]
            self.query_metrics["native_duplicate_rejections"]+=generated["duplicate_rejections"]
            self.query_metrics["native_constraint_rejections"]+=generated["constraint_rejections"]
            for point in generated["candidates"]:
                index=self._append_candidate(point,"NATIVE_HYPOTHESIS_STRATEGY")
                if index is not None and index not in self._seen:
                    native_indices.append(index)
        available=[i for i in range(len(self.pool)) if i not in self._seen]
        if not available:
            raise ValueError("Hypothesis candidate pool exhausted")
        candidates=self._candidate_ids()
        reason,objective="hypothesis-generation","failure-discovery"
        votes={}
        solver_check=None
        if native_indices:
            index=native_indices[0]
            reason="native-constraint-search" if candidates and self.strategy=="integrated" else "native-hypothesis-strategy"
        elif self.strategy=="hypothesis" or not candidates or self.inconsistent:
            index=available[0]
        elif len(self.seen)%4==3:
            occupancy=Counter(diversity_descriptor(self.measured[i]) for i in self.seen)
            index=min(available,key=lambda i:(occupancy[diversity_descriptor(self.measured[i])],self._cost(i),i))
            reason,objective="quality-diversity","coverage"
        else:
            votes={i:sum(bool(self.masks[rid]&(1<<i)) for rid in candidates) for i in available}
            if len(self.seen)%2==0:
                n=len(candidates)
                index=min(available,key=lambda i:(-votes[i]*(n-votes[i])/self._cost(i),-votes[i]/self._cost(i),i))
                reason,objective="active-disagreement","hypothesis-identification"
            else:
                # A per-family average prevents a large family of duplicate
                # predicates from consuming the whole exploitation budget.
                def support(i):
                    return (sum(sum(bool(self.masks[r]&(1<<i)) for r in g["remaining"])/len(g["remaining"])
                               for g in self.groups.values() if g["remaining"])
                            if self.groups else sum(bool(self.masks[r]&(1<<i)) for r in candidates))/self._cost(i)
                index=min(available,key=lambda i:(-support(i),i))
                reason="constraint-guided" if self.groups else "public-ast-probing"
        if self.strategy=="integrated" and candidates and not self.inconsistent and self.solver=="z3" and objective!="coverage":
            from .solver import solve_predicates
            pairs=[(rid,self._predicate_for(rid)) for rid in candidates]
            pairs=[(rid,p) for rid,p in pairs if p is not None]
            if pairs:
                selected=[pairs[0]]
                alternative=next((pair for pair in pairs[1:] if self.masks[pair[0]]!=self.masks[pairs[0][0]]),None)
                if alternative is not None:
                    selected.append(alternative)
                self.query_metrics["solver_calls"]+=1
                solver_check=solve_predicates(self.spec,[p for _,p in selected],mode="disagreement" if len(selected)==2 else "all",
                                             excluded=[self.pool[i] for i in self.seen],timeout_ms=1000)
                solver_check["hypothesis_ids"]=[rid for rid,_ in selected]
                if solver_check["status"]=="SAT":
                    chosen=self._append_candidate(solver_check["witness"],"Z3_DISAGREEMENT" if len(selected)==2 else "Z3_CONSTRAINT")
                    if chosen is not None and chosen not in self._seen:
                        index=chosen
                        self.query_metrics["solver_sat"]+=1
                        reason="smt-disagreement" if len(selected)==2 else "smt-constraint-witness"
                        objective="hypothesis-identification" if len(selected)==2 else "failure-discovery"
                    else:
                        solver_check={"status":"UNKNOWN","reason":"candidate-pool-cap","witness":None,"backend":"z3"}
        self.seen.append(index)
        self._seen.add(index)
        predicts=[rid for rid in candidates if self.masks[rid]&(1<<index)]
        result={"inputs":deepcopy(self.pool[index]),"reason":reason,"objective":objective,
                "predicted_constraints":predicts[:32],"competing_count":len(candidates),
                "hypothesis_ids":candidates[:32],"solver_check":solver_check,"declared_oracle_cost":self._cost(index),
                "positive_votes":len(predicts),"sequence":len(self.seen),"frozen":self.frozen}
        if self._semantic:
            from .claim_semantics import SEMANTIC_VERSION
            result.update(semantic_version=SEMANTIC_VERSION,claim_kinds=deepcopy(self.claim_kinds),
                candidate_source="NATIVE" if not candidates or reason.startswith("native-") or self.strategy=="hypothesis" else "PARTIAL_CONDITION_EXPLORATION",
                oracle_verdict_provided=False,empirical_guidance_adopted=False)
        return result

    def _outcome(self,e):
        return family_of(e) if e["kind"]=="FAILURE" else None

    def _semantic_prediction(self,rid,event):
        index=self._index[canonical(event["inputs"])]
        return None if self.unknown_masks[rid]&(1<<index) else bool(self.masks[rid]&(1<<index))

    def _semantic_candidate_ids(self):
        from .claim_semantics import EMPIRICAL, NECESSARY, classify, semantic_label
        selected=set()
        for family,group in self.groups.items():
            for kind,remaining in group["remaining_by_kind"].items():
                if kind==EMPIRICAL:
                    # Stored empirical hypotheses need a separate development
                    # utility receipt before any adoption. They do not acquire
                    # an active vote merely by tolerating individual errors.
                    continue
                for rid in remaining:
                    values=[(self._semantic_prediction(rid,e),semantic_label(e,family)) for e in self.evidence
                            if e["invariant"]==group["invariant"]]
                    if not any(classify(p,y,kind)["cell"]=="TP" for p,y in values):
                        continue
                    known=[p for p,y in values if p is not None and y is not None]
                    if not known or all(known) or not any(known):
                        continue
                    selected.add(rid)
        if not self.groups:
            selected=set(self._prospective)
        by_column={}
        for rid in sorted(selected):
            by_column.setdefault((self.masks[rid],self.unknown_masks[rid]),rid)
        return sorted(by_column.values())

    def _observe_semantic(self,evidence):
        from .claim_semantics import classify, normalize_semantic_evidence, semantic_label, semantic_claim_id
        if self.frozen:
            raise ValueError("frozen engine rejects final feedback")
        event=normalize_semantic_evidence(evidence,self.spec)
        key=canonical(event["inputs"])
        if key not in self._index or self._index[key] not in self._seen:
            raise ValueError("evidence must refer to a proposed candidate")
        if event["evidence_id"] in self._ids:
            raise ValueError("evidence ID already used")
        if len(self.evidence)>=self.semantic_policy["max_events"]:
            raise ValueError("R1 evidence record cap reached")
        valid_failure=event["kind"]=="FAILURE" and event.get("observation_status","VALID")=="VALID"
        new_family=valid_failure and family_of(event) not in self.groups
        if new_family and (len(self.groups)+1)*len(self.relations)*len(self.claim_kinds)>self.semantic_policy["max_claims"]:
            raise ValueError("R1 total semantic claim budget exceeded")
        families=set(self.groups)|({family_of(event)} if valid_failure else set())
        old=[e for e in self.evidence if e["invariant"]==event["invariant"] and e["inputs"]==event["inputs"]]
        # Different observed first failures are not automatically opposing
        # labels for families that were not measured in the other execution.
        if any(a is not None and b is not None and a!=b for e in old for family in families
               for a,b in [(semantic_label(e,family),semantic_label(event,family))]):
            self.inconsistent=True
        self.evidence.append(event);self._ids.add(event["evidence_id"]);self.version+=1
        if new_family:
            self.groups[family_of(event)]={"invariant":event["invariant"],"remaining":set(self.relations),
                "remaining_by_kind":{kind:set(self.relations) for kind in self.claim_kinds},"support":[],"source_evidence":[]}
        changed=[]
        scope={"spec":self.spec,"public_ir":self.public_ir,"semantic_policy":self.semantic_policy,
               "seed_relations_sha256":digest(self.seed_relations),
               "implementation_scope":"UNBOUND_GENERATOR_CANDIDATE_NOT_TRANSFER_AUTHORITY"}
        for family,group in sorted(self.groups.items()):
            relevant=[e for e in self.evidence if e["invariant"]==group["invariant"]]
            checked=(relevant if new_family and family==family_of(event) or self.inconsistent else
                     [event] if event["invariant"]==group["invariant"] else [])
            changes=[]
            for kind,remaining in group["remaining_by_kind"].items():
                eliminated={}
                for rid in remaining:
                    for observed_event in checked:
                        outcome=classify(self._semantic_prediction(rid,observed_event),semantic_label(observed_event,family),kind)
                        if self.inconsistent or outcome["refutes"]:
                            eliminated[rid]=(observed_event["evidence_id"],outcome["cell"]);break
                for rid,(eid,cell) in sorted(eliminated.items()):
                    self.contradictions.append({"family_id":family,"constraint_id":rid,
                        "claim_id":semantic_claim_id(self.relations[rid],kind,family,scope),"claim_kind":kind,
                        "evidence_id":eid,"cell":cell,"reason":"inconsistent-evidence" if self.inconsistent else "semantic-direction-counterexample"})
                remaining.difference_update(eliminated)
                changes.append({"claim_kind":kind,"eliminated":len(eliminated),"remaining":len(remaining)})
            group["remaining"]=set().union(*group["remaining_by_kind"].values())
            group["support"]=[e["evidence_id"] for e in relevant if semantic_label(e,family) is True]
            changed.append({"family_id":family,"kinds":changes,"remaining":len(group["remaining"])})
        self.history.append({"version":self.version,"evidence_id":event["evidence_id"],"groups":changed})
        return {"version":self.version,"status":self.status,"groups":changed}

    def _semantic_constraints(self):
        from .claim_semantics import SEMANTIC_VERSION, classify, semantic_label, semantic_claim_id, EMPIRICAL
        values=[]
        scope={"spec":self.spec,"public_ir":self.public_ir,"semantic_policy":self.semantic_policy,
               "seed_relations_sha256":digest(self.seed_relations),
               "implementation_scope":"UNBOUND_GENERATOR_CANDIDATE_NOT_TRANSFER_AUTHORITY"}
        for family,group in sorted(self.groups.items()):
            for kind,remaining in group["remaining_by_kind"].items():
                by_descriptor={}
                for rid in sorted(remaining):
                    descriptor=self.relations[rid]["term"]["kind"]
                    previous=by_descriptor.get(descriptor)
                    if previous is None or (self.masks[rid].bit_count(),rid)<(self.masks[previous].bit_count(),previous):
                        by_descriptor[descriptor]=rid
                for descriptor,rid in sorted(by_descriptor.items()):
                    cells={name:[] for name in ("TP","FP","FN","TN","UNKNOWN")}
                    for event in self.evidence:
                        if event["invariant"]==group["invariant"]:
                            cell=classify(self._semantic_prediction(rid,event),semantic_label(event,family),kind)["cell"]
                            cells[cell].append(event["evidence_id"])
                    trivial=not (cells["TP"] or cells["FP"]) or not (cells["FN"] or cells["TN"])
                    source_status=("EMPIRICAL_CANDIDATE" if kind==EMPIRICAL and cells["TP"] else
                        "HYPOTHESIS_NO_POSITIVE_SUPPORT" if not cells["TP"] else
                        "TRIVIAL_ON_OBSERVED_INPUTS" if trivial else "UNREFUTED_ON_OBSERVED_SCOPE")
                    values.append({"constraint_id":rid,"claim_id":semantic_claim_id(self.relations[rid],kind,family,scope),
                        "claim_kind":kind,"semantic_version":SEMANTIC_VERSION,"family_id":family,
                        "typed_relation":deepcopy(self.relations[rid]),"supporting_evidence":deepcopy(cells["TP"]),
                        "counterevidence":{name:deepcopy(cells[name]) for name in ("FP","FN")},
                        "unknown_evidence":deepcopy(cells["UNKNOWN"]),"evidence_cells":cells,
                        "source_failure":deepcopy(group["support"]),"source_evidence":deepcopy(group["source_evidence"]),
                        "source_claim_status":source_status,"trivial_on_observed_inputs":trivial,
                        "positive_support":len(cells["TP"]),
                        "source_validation_status":"NOT_SEPARATELY_VALIDATED",
                        "transfer_status":"NOT_QUALIFIED","empirical_adoption":"UTILITY_NOT_VALIDATED" if kind==EMPIRICAL else None,
                        "applicability":deepcopy(self.spec["contract"]),"version":self.version,
                        "provenance":deepcopy(scope)})
        return values

    def observe(self,evidence):
        if self._semantic:
            return self._observe_semantic(evidence)
        if self.frozen:
            raise ValueError("frozen engine rejects final feedback")
        event=normalize_evidence(evidence,self.spec)
        key=canonical(event["inputs"])
        if key not in self._index or self._index[key] not in self._seen:
            raise ValueError("evidence must refer to a proposed candidate")
        if event["evidence_id"] in self._ids:
            raise ValueError("evidence ID already used")
        if len(self.evidence)>=8192:
            raise ValueError("evidence record cap reached")
        new_family=event["kind"]=="FAILURE" and family_of(event) not in self.groups
        if new_family and len(self.groups)>=64:
            raise ValueError("failure family cap reached")
        old=[e for e in self.evidence if e["invariant"]==event["invariant"] and e["inputs"]==event["inputs"]]
        if any(self._outcome(e)!=self._outcome(event) for e in old):
            self.inconsistent=True
        self.evidence.append(event)
        self._ids.add(event["evidence_id"])
        self.version+=1
        if event["kind"]=="REFUTATION":
            i=self._index[key]
            self._prospective.difference_update({rid for rid in self._prospective if self.masks[rid]&(1<<i)})
        if new_family:
            self.groups[family_of(event)]={"invariant":event["invariant"],"remaining":set(self.relations),"support":[],"source_evidence":[]}
        changed=[]
        # Recompute new groups from all prior observations; do not lose early
        # checked non-violations when the first failure arrives.
        for family,group in sorted(self.groups.items()):
            relevant=[e for e in self.evidence if e["invariant"]==group["invariant"]]
            positive=[e["evidence_id"] for e in relevant if e["kind"]=="FAILURE" and family_of(e)==family]
            checked=relevant if (new_family and family==family_of(event)) or self.inconsistent else ([event] if event["invariant"]==group["invariant"] else [])
            eliminated={}
            for rid in group["remaining"]:
                for e in checked:
                    label=e["kind"]=="FAILURE" and family_of(e)==family
                    i=self._index[canonical(e["inputs"])]
                    if self.inconsistent or bool(self.masks[rid]&(1<<i))!=label:
                        eliminated[rid]=e["evidence_id"]
                        break
            for rid,eid in sorted(eliminated.items()):
                self.contradictions.append({"family_id":family,"constraint_id":rid,"evidence_id":eid,
                                            "reason":"inconsistent-evidence" if self.inconsistent else "membership-counterexample"})
            group["remaining"].difference_update(eliminated)
            group["support"]=positive
            changed.append({"family_id":family,"eliminated":len(eliminated),"remaining":len(group["remaining"])})
        self.history.append({"version":self.version,"evidence_id":event["evidence_id"],"groups":changed})
        return {"version":self.version,"status":self.status,"groups":changed}

    @property
    def status(self):
        if self.inconsistent:
            return "INCONSISTENT_EVIDENCE"
        if not self.groups:
            return "NO_FAILURE_EVIDENCE"
        return "HYPOTHESES_REMAIN" if any(g["remaining"] for g in self.groups.values()) else "OUT_OF_GRAMMAR"

    def _constraints(self):
        if self._semantic:
            return self._semantic_constraints()
        constraints=[]
        for family,group in sorted(self.groups.items()):
            descriptors=sorted({self.relations[r]["term"]["kind"] for r in group["remaining"]})
            for descriptor in descriptors:
                ids=sorted(r for r in group["remaining"] if self.relations[r]["term"]["kind"]==descriptor)
                rid=min(ids,key=lambda r:(self.masks[r].bit_count(),r))
                constraints.append({"constraint_id":rid,"family_id":family,"typed_relation":deepcopy(self.relations[rid]),
                                    "evidence_id":[e["evidence_id"] for e in self.evidence if e["invariant"]==group["invariant"]],
                                    "source_failure":deepcopy(group["support"]),"source_evidence":deepcopy(group["source_evidence"]),
                                    "applicability":deepcopy(self.spec["contract"]),"supporting_evidence":deepcopy(group["support"]),
                                    "contradiction":[],"competing_hypotheses":ids,
                                    "uncertainty":{"status":"UNCONFIRMED_MEMBERSHIP_HYPOTHESIS","probability":None,
                                                   "unknown_conditions":["outside-generated-pool","outside-feature-grammar","causality","target-recurrence"]},
                                    "version":self.version,"scope":{"task_id":self.spec["task_id"],"pool_sha256":digest(self.pool)},
                                    "provenance":{"spec_sha256":digest(self.spec),"source_snapshot":(self.gate or {}).get("source_snapshot_sha256")}})
        return constraints

    def snapshot(self):
        constraints=self._constraints()
        groups={family:{"invariant":g["invariant"],"remaining":sorted(g["remaining"]),"support":deepcopy(g["support"]),
                        "source_evidence":deepcopy(g["source_evidence"])} for family,g in sorted(self.groups.items())}
        if self._semantic:
            for family,g in self.groups.items():
                groups[family]["remaining_by_kind"]={kind:sorted(ids) for kind,ids in g["remaining_by_kind"].items()}
        payload={"schema":SEMANTIC_SNAPSHOT_SCHEMA if self._semantic else SNAPSHOT_SCHEMA,"spec":deepcopy(self.spec),"public_ir":deepcopy(self.public_ir),"seed":self.seed,"strategy":self.strategy,
                 "pool_size":self.pool_size,"seed_candidates":deepcopy(self.seed_candidates),"pool":deepcopy(self.pool),
                 "initial_pool":deepcopy(self.initial_pool),"pool_events":deepcopy(self.pool_events),
                 "solver":self.solver,"native_strategy":self.native_strategy,"oracle_costs":deepcopy(self.oracle_costs),
                 "query_metrics":deepcopy(self.query_metrics),"prospective":sorted(self._prospective),
                 "seen":list(self.seen),"evidence":deepcopy(self.evidence),"prior":deepcopy(self.prior),"gate":deepcopy(self.gate),
                 "groups":groups,"constraints":constraints,"relations":deepcopy(self.relations),
                 "archive":[{"descriptor":c["family_id"]+":"+c["typed_relation"]["term"]["kind"],"constraint_id":c["constraint_id"],
                             "quality":{"pool_support":self.masks[c["constraint_id"]].bit_count(),"meaning":"specificity-not-correctness"}} for c in constraints],
                 "contradictions":deepcopy(self.contradictions),"history":deepcopy(self.history),
                 "version":self.version,"status":self.status,"frozen":self.frozen}
        if self._semantic:
            from .claim_semantics import SEMANTIC_VERSION
            payload.update(semantic_version=SEMANTIC_VERSION,claim_kinds=deepcopy(self.claim_kinds),semantic_policy=deepcopy(self.semantic_policy),seed_relations=deepcopy(self.seed_relations))
        payload["receipt"]={"sha256":digest(payload),"oracle_calls":0,"authenticity":"CALLER_APPROVAL_REQUIRED"}
        return payload

    def freeze(self):
        self.frozen=True
        return self.snapshot()

    @classmethod
    def from_snapshot(cls,snapshot):
        required=("schema","spec","public_ir","seed","strategy","pool_size","seed_candidates","pool","initial_pool","pool_events",
                  "solver","native_strategy","oracle_costs","query_metrics","prospective","seen","evidence","prior","gate",
                  "groups","constraints","relations","archive","contradictions","history","version","status","frozen","receipt")
        semantic=isinstance(snapshot,dict) and snapshot.get("schema")==SEMANTIC_SNAPSHOT_SCHEMA
        keys(snapshot,required+(('semantic_version','claim_kinds','semantic_policy','seed_relations') if semantic else ()))
        if snapshot["schema"] not in (SNAPSHOT_SCHEMA,SEMANTIC_SNAPSHOT_SCHEMA) or type(snapshot["frozen"]) is not bool:
            raise ValueError("invalid snapshot schema")
        if semantic:
            from .claim_semantics import SEMANTIC_VERSION
            if snapshot["semantic_version"]!=SEMANTIC_VERSION:
                raise ValueError("unsupported explicit claim semantics")
        keys(snapshot["receipt"],("sha256","oracle_calls","authenticity"))
        if snapshot["receipt"]["sha256"]!=digest({k:v for k,v in snapshot.items() if k!="receipt"}):
            raise ValueError("snapshot digest mismatch")
        engine=cls(snapshot["spec"],seed=snapshot["seed"],strategy=snapshot["strategy"],pool_size=snapshot["pool_size"],
                   seed_candidates=snapshot["seed_candidates"],public_ir=snapshot["public_ir"],_pool=snapshot["initial_pool"],
                   solver=snapshot["solver"],native_strategy=snapshot["native_strategy"],oracle_costs=snapshot["oracle_costs"],
                   **({"claim_kinds":snapshot["claim_kinds"],"semantic_policy":snapshot["semantic_policy"],"seed_relations":snapshot["seed_relations"]} if semantic else {}))
        if not isinstance(snapshot["pool_events"],list) or len(snapshot["pool_events"])>4096:
            raise ValueError("invalid dynamic pool history")
        for event in snapshot["pool_events"]:
            keys(event,("inputs","source"))
            if event["source"] not in {"NATIVE_HYPOTHESIS_STRATEGY","Z3_DISAGREEMENT","Z3_CONSTRAINT"}:
                raise ValueError("unsupported candidate provenance")
            if canonical(validate_inputs(event["inputs"],engine.spec)) in engine._index:
                raise ValueError("duplicate dynamic candidate")
            engine._append_candidate(event["inputs"],event["source"])
        if engine.pool!=snapshot["pool"]:
            raise ValueError("pool does not match dynamic candidate history")
        if snapshot["prior"] is not None:
            if not isinstance(snapshot["gate"],dict):
                raise ValueError("prior without gate")
            engine._install_prior(snapshot["prior"],snapshot["gate"])
        elif snapshot["gate"] is not None:
            raise ValueError("gate without prior")
        if not isinstance(snapshot["seen"],list) or len(snapshot["seen"])>len(engine.pool):
            raise ValueError("invalid seen stream")
        for i in snapshot["seen"]:
            integer(i,0,len(engine.pool)-1)
            if i in engine._seen:
                raise ValueError("duplicate seen input")
            engine.seen.append(i)
            engine._seen.add(i)
        if not isinstance(snapshot["evidence"],list) or len(snapshot["evidence"])>8192:
            raise ValueError("invalid evidence size")
        for event in snapshot["evidence"]:
            engine.observe(event)
        keys(snapshot["query_metrics"],engine.query_metrics.keys())
        for name,value in snapshot["query_metrics"].items():
            integer(value,0,1000000)
        if snapshot["query_metrics"]["solver_sat"]>snapshot["query_metrics"]["solver_calls"]:
            raise ValueError("invalid solver counters")
        engine.query_metrics=deepcopy(snapshot["query_metrics"])
        engine.frozen=snapshot["frozen"]
        if engine.snapshot()!=snapshot:
            raise ValueError("snapshot derived state inconsistent with evidence")
        return engine


def transfer(snapshot,target_spec,*,seed=7,budget=64,pool_size=512,target_ir=None,mapping=None,
             target_evidence=(),solver=None,native_strategy=None,oracle_costs=None):
    source=DiscoveryEngine.from_snapshot(snapshot)
    if source._semantic:
        raise ValueError("R1 transfer requires independently qualified kind-checked KnowledgeArchive guidance")
    if not source.frozen:
        raise ValueError("transfer requires frozen source")
    target=validate_spec(target_spec)
    left={v["role"]:v for v in source.spec["inputs"]}
    right={v["role"]:v for v in target["inputs"]}
    reasons=[]
    from .transfer import validate_transfer
    ir_gate=validate_transfer(source.spec,target,source.public_ir,target_ir,mapping)
    reasons.extend(ir_gate["reasons"])
    if set(left)!=set(right):
        reasons.append("semantic roles do not correspond")
    else:
        for role in left:
            if not type_subset(right[role]["type"],left[role]["type"]):
                reasons.append("type or scope differs: "+role)
    for field in ("id","operation","preconditions","invariants","state_model","graph_signature"):
        if source.spec["contract"][field]!=target["contract"][field]:
            reasons.append("contract differs: "+field)
    if source.spec["contract"]["graph_signature"]=="UNKNOWN" or target["contract"]["graph_signature"]=="UNKNOWN":
        reasons.append("operation graph correspondence unknown")
    if source.inconsistent or not any(g["remaining"] for g in source.groups.values()):
        reasons.append("no consistent supported source relation")
    if not any(g["support"] for g in source.groups.values()):
        reasons.append("source has no local development failure evidence")
    transferable_ids={family:[rid for rid in sorted(group["remaining"]) if transferable(source.relations[rid])]
                      for family,group in source.groups.items()}
    excluded_coordinates=sum(len(group["remaining"])-len(transferable_ids[family]) for family,group in source.groups.items())
    if not isinstance(target_evidence,(list,tuple)) or len(target_evidence)>256:
        raise ValueError("bounded approved target development evidence required")
    target_events=[normalize_evidence(event,target) for event in target_evidence]
    if len({event["evidence_id"] for event in target_events})!=len(target_events):
        raise ValueError("target evidence IDs must be unique")
    labels={}
    for event in target_events:
        key=(event["invariant"],canonical(event["inputs"]))
        value=family_of(event) if event["kind"]=="FAILURE" else None
        if key in labels and labels[key]!=value:
            reasons.append("target development evidence is inconsistent")
        labels[key]=value
    target_contradictions=[]
    solver_checks=[]
    chosen_solver=source.solver if solver is None else solver
    if chosen_solver not in ("enumeration","z3"):
        raise ValueError("solver must be enumeration or z3")
    for family,ids in transferable_ids.items():
        kept=[]
        for rid in ids:
            relation=source.relations[rid]
            if relation["term"]["kind"]=="ast":
                validate_predicate(relation["term"]["expression"],target)
            contradicted=[event["evidence_id"] for event in target_events
                          if event["invariant"]==source.groups[family]["invariant"]
                          and holds(relation,measurements(event["inputs"],target,source.predicates)) !=
                              (event["kind"]=="FAILURE" and family_of(event)==family)]
            if contradicted:
                target_contradictions.append({"constraint_id":rid,"evidence_ids":contradicted,"reason":"target-development-counterexample"})
                continue
            predicate=source._predicate_for(rid)
            if chosen_solver=="z3" and predicate is not None:
                from .solver import solve_predicates
                check=solve_predicates(target,[predicate],mode="all",timeout_ms=500)
                solver_checks.append({"constraint_id":rid,"status":check["status"]})
                if check["status"]=="UNSAT":
                    target_contradictions.append({"constraint_id":rid,"evidence_ids":[],"reason":"target-domain-unsatisfiable"})
                    continue
            kept.append(rid)
        transferable_ids[family]=kept
    if not any(transferable_ids.values()):
        reasons.append("no structural hypothesis survives coordinate-copy exclusion")
    gate={"status":"UNKNOWN" if reasons else "APPLICABLE_FOR_PROBING","reasons":reasons,
          "mapping":{left[r]["name"]:right[r]["name"] for r in set(left)&set(right)},
          "source_snapshot_sha256":snapshot["receipt"]["sha256"],"failure_recurrence":"UNKNOWN",
          "target_counterevidence_ids":[event["evidence_id"] for event in target_events],
          "target_contradictions":target_contradictions,"solver_checks":solver_checks,
          "excluded_coordinate_constraints":excluded_coordinates,
          "claim":"declared typed role, contract and graph correspondence permit probes; not a proof of repeated defects"}
    prior=[]
    if not reasons:
        for family,group in sorted(source.groups.items()):
            if transferable_ids[family]:
                prior.append({"family_id":family,"invariant":group["invariant"],
                              "relations":[source.relations[rid] for rid in transferable_ids[family]],
                              "source_evidence":[{"source_snapshot":snapshot["receipt"]["sha256"],"evidence_ids":group["support"]}]})
    engine=DiscoveryEngine(target,seed=seed,strategy=source.strategy,pool_size=pool_size,public_ir=target_ir,
                           solver=chosen_solver,native_strategy=native_strategy,oracle_costs=oracle_costs)
    engine._install_prior(prior,gate)
    engine.frozen=True
    integer(budget,1,len(engine.pool))
    candidates=[engine.propose() for _ in range(budget)]
    return {"gate":gate,"snapshot":engine.snapshot(),"candidates":candidates}
