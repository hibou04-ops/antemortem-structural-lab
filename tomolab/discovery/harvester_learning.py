"""Qualified harvest evidence -> existing M0/selector/generation APIs.

The real-data path has no host external-code execution fallback.
"""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess
import time

from .harvester_registry import HarvestRegistry
from .harvester_service import save_new
from .harvester_review import assess_candidate, build_consumed_registry, development_lineage
from .recursive_api import update_generation
from .recursive_store import GenerationStore
from .recursive_policy import make_development_manifest, validate_development_manifest
from .recursive_observe import validate_pair_receipt
from .schema import digest, keys

FROZEN_MOLD_DIGEST = "8524b488e51ad145e9c9d544522a54a2bc2f4371b3baebf0d51108bfd998e24e"


def review_candidate(workspace,candidate_id,review,*,execution_receipt=None,allow_reviewed_development=False):
    if allow_reviewed_development is not True:
        raise PermissionError("explicit accountable development review required")
    registry=HarvestRegistry(workspace)
    candidate=registry.candidates().get(candidate_id)
    if candidate is None:
        raise ValueError("register the actual candidate first")
    assessment=assess_candidate(candidate,consumed_registry=build_consumed_registry(),review=review,
        execution_receipt=execution_receipt,trusted_review=True)
    registry.review(candidate_id,assessment,review,execution_receipt,batch_id="review-"+digest(assessment)[:24])
    return dict(schema="tomolab-harvest-review-result-v1",status="COMPLETE",assessment=assessment,
        policy_updated=False,real_external_execution=False)


def _qualified_rows(registry,candidate_ids):
    if type(candidate_ids) is not list or len(candidate_ids)!=4 or len(set(candidate_ids))!=4:
        raise PermissionError("M0 requires exactly four distinct reviewed development candidates")
    consumed=build_consumed_registry()
    rows=[]
    for candidate_id in candidate_ids:
        row=registry.reviewed(candidate_id)
        if row["review"] is None or row["execution_receipt"] is None:
            raise PermissionError("reviewed Oracle, reset and buggy/fixed reproduction evidence required")
        assessment=assess_candidate(row["candidate"],consumed_registry=consumed,
            review=row["review"],execution_receipt=row["execution_receipt"],trusted_review=True)
        if assessment["status"]!="DEVELOPMENT_ELIGIBLE":
            raise PermissionError("candidate is not development eligible")
        row["assessment"]=assessment
        row["lineage"]=development_lineage(row["candidate"],assessment,row["review"])
        rows.append(row)
    lineages=[row["lineage"] for row in rows]
    if len({r["independence_id"] for r in lineages})!=4 or len({r["project_id"] for r in lineages})<2 or len({r["mechanism_id"] for r in lineages})<2:
        raise PermissionError("four independent lineages, two projects and two mechanisms required")
    return rows


def m0_verdict(receipts,lineage_ids,*,measurement_complete=True,within_budget=True,unknown_external_calls=0):
    if not isinstance(receipts,list) or len(set(lineage_ids))!=4:
        raise ValueError("four registered M0 lineages required")
    stats={lineage:dict(gain=0,loss=0,resolved=0,unknown=0) for lineage in lineage_ids}
    reservations,receipt_ids=set(),set()
    for receipt in receipts:
        validate_pair_receipt(receipt)
        if receipt["reservation_id"] in reservations or receipt["pair_receipt_sha256"] in receipt_ids:
            raise ValueError("duplicated M0 execution cannot create local signal")
        reservations.add(receipt["reservation_id"])
        receipt_ids.add(receipt["pair_receipt_sha256"])
        if receipt["source_lineage_id"] not in stats:
            raise ValueError("M0 receipt belongs to an unregistered lineage")
        row=stats[receipt["source_lineage_id"]]
        if receipt["label"]=="UNKNOWN":
            row["unknown"]+=1
        else:
            row["resolved"]+=1
            if receipt["label"] in ("gain","loss"):
                row[receipt["label"]]+=1
    unknown=sum(row["unknown"] for row in stats.values())
    complete=measurement_complete is True and within_budget is True and unknown_external_calls==0
    complete=complete and bool(receipts) and all(row["resolved"]>0 for row in stats.values())
    complete=complete and Fraction(unknown,len(receipts) or 1)<=Fraction(1,4)
    utility=sum((Fraction(row["gain"]-row["loss"],row["resolved"]) for row in stats.values() if row["resolved"]),Fraction())/4 if complete else None
    status="HOLD_MEASUREMENT" if not complete else ("LOCAL_SIGNAL_OBSERVED" if utility>0 and sum(row["gain"]>0 for row in stats.values())>=2 else "HOLD_NO_LOCAL_SIGNAL")
    return dict(status=status,lineages=stats,unknown_fraction=float(Fraction(unknown,len(receipts) or 1)),
        equal_lineage_utility=float(utility) if utility is not None else None,
        scope="LOCAL_CONDITIONAL_DIAGNOSTIC_NOT_POLICY_SUPERIORITY")


def _append_update(registry,receipts,manifest,generation_store,*,generation_id,m0_record,cost_ledger=None):
    validate_development_manifest(manifest)
    if manifest["experiment_contract_sha256"]!=m0_record["experiment_contract_sha256"]:
        raise ValueError("development manifest differs from the frozen M0 record")
    expected=set(m0_record["paired_receipt_digests"])
    if {r["pair_receipt_sha256"] for r in receipts}!=expected:
        raise ValueError("only the complete preserved M0 receipt batch may update the selector")
    for receipt in receipts:
        validate_pair_receipt(receipt)
    if not receipts:
        raise ValueError("actual paired development experience is required")
    generations=GenerationStore(generation_store).records()
    if not generations:
        raise ValueError("create G0 before learning harvest experience")
    consumed={r["pair_receipt_sha256"] for r in generations[-1]["generation"]["selector"]["evidence"]}
    if expected & consumed:
        if not expected <= consumed:
            raise ValueError("partially consumed M0 batch needs explicit cost reconciliation")
        original=next(r["generation"] for r in generations if expected <= {
            e["pair_receipt_sha256"] for e in r["generation"]["selector"]["evidence"]})
        return dict(schema="tomolab-harvest-learning-result-v1",status="COMPLETE",
            update_status="ALREADY_CONSUMED",generation_id=original["generation_id"],
            generation_digest=original["sha256"],selector_digest=original["selector"]["selector_digest"],
            additional_observation_cost=0,new_generation_created=False,
            evidence_class=manifest["evidence_class"],transfer_utility="NOT_ESTABLISHED",default_adoption="HOLD")
    if cost_ledger is None and m0_record.get("development_cost_ledger") is not None:
        parent=GenerationStore(generation_store).latest()
        if parent is None:
            raise ValueError("create G0 before learning harvest experience")
        cost_ledger=deepcopy(parent["cost_ledger"])
        for name,value in m0_record["development_cost_ledger"].items():
            cost_ledger[name]+=value
        consumed={row["source_lineage_id"] for row in parent["selector"]["evidence"]}
        for lineage,qualification_cost in m0_record.get("qualification_cost_by_lineage",{}).items():
            if lineage not in consumed:
                for name,value in qualification_cost.items():
                    cost_ledger[name]+=value
    generation=update_generation(generation_store,receipts,manifest,generation_id=generation_id,
        cost_ledger=cost_ledger)
    registry.append("LEARNING",dict(generation_id=generation_id,generation_digest=generation["sha256"],
        manifest_digest=manifest["manifest_digest"],paired_receipt_digests=sorted(expected),
        evidence_class=manifest["evidence_class"],default_adoption="HOLD"),batch_id="learn-"+generation_id)
    return dict(schema="tomolab-harvest-learning-result-v1",status="COMPLETE",
        generation_id=generation_id,generation_digest=generation["sha256"],
        selector_digest=generation["selector"]["selector_digest"],recursive_update="RECURSIVE_UPDATE_FUNCTIONAL",
        evidence_class=manifest["evidence_class"],transfer_utility="NOT_ESTABLISHED",oos="NOT_ESTABLISHED",default_adoption="HOLD")


def learn_from_harvest(workspace,candidate_ids,receipts,manifest,generation_store,*,generation_id,
                       allow_reviewed_development=False):
    if allow_reviewed_development is not True:
        raise PermissionError("explicit reviewed development update required")
    registry=HarvestRegistry(workspace)
    rows=_qualified_rows(registry,candidate_ids)
    validate_development_manifest(manifest)
    if manifest["evidence_class"]!="REVIEWED_REAL_DEVELOPMENT":
        raise PermissionError("real harvest learning does not accept synthetic or final evidence")
    if manifest["lineages"]!=[r["lineage"] for r in rows]:
        raise ValueError("manifest does not preserve the qualified candidate identities")
    m0=next((r["payload"] for r in reversed(registry.records()) if r["kind"]=="M0"
        and r["payload"].get("phase")=="COMPLETE"
        and r["payload"].get("experiment_contract_sha256")==manifest["experiment_contract_sha256"]),None)
    if m0 is None or m0.get("evidence_class")!="REVIEWED_REAL_DEVELOPMENT" or m0.get("measurement_verdict",{}).get("status")!="LOCAL_SIGNAL_OBSERVED":
        raise PermissionError("preserved actual M0 development execution required")
    return _append_update(registry,receipts,manifest,generation_store,generation_id=generation_id,
        m0_record=m0,cost_ledger=m0.get("cumulative_cost_ledger"))


def _local_json(workspace,relative):
    if type(relative) is not str or Path(relative).is_absolute():
        raise ValueError("workspace-relative reviewed artifact required")
    base=Path(workspace).resolve()
    path=(base/relative).resolve()
    if not path.is_relative_to(base) or path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024*1024:
        raise ValueError("bounded reviewed artifact must remain in its workspace")
    return json.loads(path.read_text(encoding="utf-8"))


def _reserve_research_budget(registry,rows):
    records=[r["payload"] for r in registry.records() if r["kind"]=="M0"
             and r["payload"].get("evidence_class")=="REVIEWED_REAL_DEVELOPMENT"]
    started={r["experiment_contract_sha256"] for r in records if r.get("phase")=="START"}
    complete={r["experiment_contract_sha256"] for r in records if r.get("phase")=="COMPLETE"}
    if started-complete:
        raise PermissionError("unresolved prior M0 costs require explicit recovery")
    prior=[r for r in records if r.get("phase")=="COMPLETE"]
    if any(r.get("unknown_external_call_records",0) for r in prior):
        raise PermissionError("unknown prior external execution costs prevent another budget reservation")
    target=sum(r["adapter_target_attempts"] for r in prior)
    oracle=sum(r["adapter_oracle_attempts"] for r in prior)
    wall=sum(r["wall_seconds"] for r in prior)
    qualification={}
    for record in prior:
        qualification.update(record.get("qualification_cost_by_lineage",{}))
    for row in rows:
        lineage=row["lineage"]["source_lineage_id"]
        receipt=row["execution_receipt"]
        qualification.setdefault(lineage,dict(target_calls=receipt["external_target_calls"],
            oracle_calls=receipt["external_oracle_calls"],observation_wall_seconds=receipt["wall_seconds"]))
    target+=sum(r["target_calls"] for r in qualification.values())
    oracle+=sum(r["oracle_calls"] for r in qualification.values())
    wall+=sum(r["observation_wall_seconds"] for r in qualification.values())
    if target+1152>10000 or oracle+1152>10000 or wall+1200>3600:
        raise PermissionError("fixed workspace research call/time budget cannot reserve another M0")
    return dict(prior_and_qualification_target_attempts=target,prior_and_qualification_oracle_attempts=oracle,
        prior_and_qualification_wall_seconds=wall,reserved_m0_target=1152,reserved_m0_oracle=1152,
        reserved_m0_wall_seconds=1200,authority="THIS_APPEND_ONLY_HARVEST_WORKSPACE")


class _DeadlineCallable:
    """Shared controller deadline; each entered OCI call also has a hard timeout."""
    def __init__(self,delegate,deadline):
        self.delegate,self.deadline=delegate,deadline
        self.ledger=delegate.ledger

    def reset(self):
        return time.perf_counter()+5 < self.deadline and self.delegate.reset() is True

    def __call__(self,point):
        remaining=int(self.deadline-time.perf_counter())-5
        if remaining<1:
            # Charge the actual host adapter entry, but no container/inner call.
            self.ledger["wrapper_entries"]+=1
            raise OSError("M0 shared deadline prevents another external entry")
        self.delegate.timeout=min(30,remaining)
        return self.delegate(point)


def run_harvest_m0(workspace,contract,*,allow_external_execution=False):
    from .harvester_execution import OCIReviewedCallable, validate_source_bundle
    from .online_engine import run_online
    from .online_mold import validate_mold
    from .recursive_observe import make_diagnostics
    keys(contract,("schema","split","candidate_ids","input_contract","mold_path","mold_digest",
        "source_bundles","image","replays","seed_repetitions","max_target_calls","max_oracle_calls",
        "max_wall_seconds","experiment_contract_sha256"))
    if contract["schema"]!="tomolab-harvester-m0-contract-v1" or contract["split"]!="development":
        raise PermissionError("one frozen development M0 contract required; final feedback forbidden")
    experiment=digest({k:v for k,v in contract.items() if k!="experiment_contract_sha256"})
    if contract["experiment_contract_sha256"]!=experiment:
        raise ValueError("M0 contract digest mismatch")
    if any(type(contract[name]) is not int for name in ("seed_repetitions","max_target_calls","max_oracle_calls","max_wall_seconds")) or contract["seed_repetitions"]!=2 or contract["max_target_calls"]!=1152 or contract["max_oracle_calls"]!=1152 or contract["max_wall_seconds"]!=1200:
        raise ValueError("preserve the frozen first M0 resource contract")
    registry=HarvestRegistry(workspace)
    try:
        rows=_qualified_rows(registry,contract["candidate_ids"])
    except (ValueError,PermissionError) as error:
        return dict(schema="tomolab-harvest-m0-result-v1",status="HOLD",m0="HOLD_INSUFFICIENT_LINEAGES",
            reason=str(error),real_target_calls=0,real_oracle_calls=0,experiment_contract_sha256=experiment)
    if allow_external_execution is not True:
        raise PermissionError("external M0 requires inspected OCI execution and explicit opt-in")
    if type(contract["image"]) is not str or re.fullmatch("sha256:[a-f0-9]{64}",contract["image"]) is None:
        raise ValueError("immutable reviewed OCI image digest required")
    if contract["mold_digest"]!=FROZEN_MOLD_DIGEST:
        raise ValueError("real M0 requires the original frozen ALL Mold")
    mold=validate_mold(_local_json(workspace,contract["mold_path"]),expected_digest=contract["mold_digest"])
    bundles={}
    if set(contract["source_bundles"])!=set(contract["candidate_ids"]):
        raise ValueError("source bundles must match the four qualified cases")
    for row in rows:
        cid=row["candidate"]["candidate_id"]
        spec=contract["source_bundles"][cid]
        keys(spec,("path","bundle_digest"))
        bundle=validate_source_bundle(_local_json(workspace,spec["path"]),review=row["review"])
        if bundle["bundle_digest"]!=spec["bundle_digest"] or row["review"]["contract"]!=contract["input_contract"]:
            raise ValueError("one reviewed common input contract and exact source bundle required")
        bundles[cid]=bundle
    budget_reservation=_reserve_research_budget(registry,rows)
    try:
        daemon=subprocess.run(["docker","info","--format","{{.ServerVersion}}"],capture_output=True,text=True,timeout=10)
        available=daemon.returncode==0 and bool(daemon.stdout.strip())
    except (OSError,subprocess.TimeoutExpired):
        available=False
    if not available:
        return dict(schema="tomolab-harvest-m0-result-v1",status="HOLD",m0="HOLD_EXECUTION",
            reason="ACTUAL_OCI_DAEMON_UNAVAILABLE_NO_HOST_FALLBACK",real_target_calls=0,real_oracle_calls=0,
            experiment_contract_sha256=experiment)
    # A prior START is consumed even after interruption; never silently replay.
    if any(r["kind"]=="M0" and r["payload"].get("experiment_contract_sha256")==experiment
           and r["payload"].get("phase")=="START" for r in registry.records()):
        raise PermissionError("M0 execution already started; preserve partial costs for explicit recovery")
    folder=registry.workspace/"m0"/experiment
    save_new(folder/"frozen-contract.json",contract)
    registry.append("M0",dict(phase="START",experiment_contract_sha256=experiment,
        candidate_ids=contract["candidate_ids"],evidence_class="REVIEWED_REAL_DEVELOPMENT"),batch_id="m0-"+experiment[:24])
    started=time.perf_counter()
    deadline=started+1200
    receipts,runs,ledgers=[],[],[]
    for row in rows:
        cid=row["candidate"]["candidate_id"]
        for repeat in range(2):
            if time.perf_counter()+5>=deadline:
                break
            seed=int(digest(dict(contract=experiment,lineage=row["lineage"]["source_lineage_id"],repeat=repeat))[:8],16)
            run_id="m0-"+cid[:16]+"-"+str(repeat)
            common=dict(candidate=row["candidate"],review=row["review"],source_bundle=bundles[cid],
                image=contract["image"],workspace=folder/run_id,allow_external_execution=True,trusted_review=True)
            target=_DeadlineCallable(OCIReviewedCallable(variant="buggy",**common),deadline)
            oracle=_DeadlineCallable(OCIReviewedCallable(variant="oracle",**common),deadline)
            identity=dict(implementation_sha256=row["review"]["implementation_sha256"],oracle_sha256=row["review"]["oracle_sha256"],
                environment_sha256=digest(dict(image=contract["image"])),reset_adapter_sha256=row["review"]["reset_adapter_sha256"],
                purity_review_id=row["review"]["review_ids"]["reset_review_id"])
            cfg=make_diagnostics(mold,experiment_contract_sha256=experiment,source_lineage_id=row["lineage"]["source_lineage_id"],
                project_id=row["lineage"]["project_id"],mechanism_id=row["lineage"]["mechanism_id"],run_id=run_id,identity=identity)
            cfg["public"]["max_pair_seconds"]=max(0.001,min(90,deadline-time.perf_counter()-5))
            result=run_online(target,oracle,contract["input_contract"],method="C",mold=None,replays=contract["replays"],
                seed=seed,budget=72,shrink_budget=9,max_seconds=max(0.001,min(30,deadline-time.perf_counter()-5)),mode="black_box",diagnostics=cfg,
                diagnostic_reset=lambda:target.reset() is True and oracle.reset() is True)
            save_new(folder/(run_id+".json"),dict(run=result,target_oci_ledger=target.ledger,oracle_oci_ledger=oracle.ledger))
            runs.append(result)
            receipts.extend(result.get("paired_diagnostics",{}).get("receipts",[]))
            ledgers.extend([target.ledger,oracle.ledger])
    target_calls=sum(l["external_target_calls"] for l in ledgers)
    oracle_calls=sum(l["external_oracle_calls"] for l in ledgers)
    target_attempts=sum(l["wrapper_entries"] for l in ledgers[::2])
    oracle_attempts=sum(l["wrapper_entries"] for l in ledgers[1::2])
    unknown_external=sum(l["unresolved_call_receipts"] for l in ledgers)
    elapsed=time.perf_counter()-started
    within_budget=target_attempts<=1152 and oracle_attempts<=1152 and elapsed<=1200
    measured=len(runs)==8 and all(r.get("diagnostic_trace",{}).get("status")=="COMPLETE" for r in runs)
    verdict=m0_verdict(receipts,[r["lineage"]["source_lineage_id"] for r in rows],
        measurement_complete=measured,within_budget=within_budget,unknown_external_calls=unknown_external)
    reset_callbacks=sum(r.get("paired_diagnostics",{}).get("cost",{}).get("reset_calls",0) for r in runs)
    external_resets=sum(l["external_reset_calls"] for l in ledgers)
    cost=dict(target_calls=target_attempts,oracle_calls=oracle_attempts,reset_calls=reset_callbacks+external_resets,
        observation_wall_seconds=elapsed,learning_seconds=0.0,validation_seconds=0.0,io_seconds=0.0)
    qualification={r["lineage"]["source_lineage_id"]:dict(target_calls=r["execution_receipt"]["external_target_calls"],
        oracle_calls=r["execution_receipt"]["external_oracle_calls"],reset_calls=r["execution_receipt"]["external_reset_calls"],
        observation_wall_seconds=r["execution_receipt"]["wall_seconds"],learning_seconds=0.0,validation_seconds=0.0,io_seconds=0.0) for r in rows}
    manifest=make_development_manifest([row["lineage"] for row in rows],experiment,evidence_class="REVIEWED_REAL_DEVELOPMENT")
    payload=dict(phase="COMPLETE",experiment_contract_sha256=experiment,candidate_ids=contract["candidate_ids"],
        evidence_class="REVIEWED_REAL_DEVELOPMENT",paired_receipt_digests=[r["pair_receipt_sha256"] for r in receipts],
        real_target_calls=target_calls if unknown_external==0 else None,real_oracle_calls=oracle_calls if unknown_external==0 else None,
        known_external_target_calls=target_calls,known_external_oracle_calls=oracle_calls,
        budget_reservation=budget_reservation,
        unknown_external_call_records=unknown_external,
        adapter_target_attempts=target_attempts,adapter_oracle_attempts=oracle_attempts,
        host_reset_callbacks=reset_callbacks,external_reset_calls=external_resets,
        development_cost_ledger=cost,qualification_cost_by_lineage=qualification,measurement_verdict=verdict,
        cost_scope="Adapter attempts charged; verified inner external calls separate; unresolved inner counts retained",
        wall_seconds=elapsed)
    save_new(folder/"development-manifest.json",manifest)
    save_new(folder/"paired-receipts.json",receipts)
    registry.append("M0",payload,batch_id="m0-"+experiment[:24])
    return dict(schema="tomolab-harvest-m0-result-v1",status="COMPLETE" if verdict["status"]=="LOCAL_SIGNAL_OBSERVED" else "HOLD",
        m0=verdict["status"],**payload,
        transfer_utility="NOT_ESTABLISHED",oos="NOT_ESTABLISHED",policy_updated=False)
