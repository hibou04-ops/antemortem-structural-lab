"""Bounded discovery -> provenance registry -> explicit review queue.

Collection never imports external code, executes targets or updates a selector.
"""
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from .harvester_registry import HarvestRegistry
from .schema import canonical, digest

DEFAULT_REPOSITORIES = ("python/cpython", "pallets/werkzeug", "psf/requests", "python-attrs/attrs",
    "sympy/sympy", "networkx/networkx", "grantjenks/python-sortedcontainers", "more-itertools/more-itertools")


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value)+"\n")
        stream.flush()
        os.fsync(stream.fileno())


def discovery_contract(repositories, max_candidates=50, max_details=10, max_qualifications=4):
    for value, cap in ((max_candidates,50),(max_details,10),(max_qualifications,4)):
        if type(value) is not int or not 1 <= value <= cap:
            raise ValueError("bounded discovery caps required")
    if not isinstance(repositories,(list,tuple)) or not 1 <= len(repositories) <= 8 or len(set(repositories))!=len(repositories):
        raise ValueError("one to eight distinct reviewed public repositories required")
    value = dict(schema="tomolab-harvest-discovery-contract-v1", split="development",
        repositories=list(repositories), max_candidates=max_candidates, max_details=max_details,
        max_qualifications=max_qualifications, max_repositories=8,
        selection="FIXED_REPOSITORY_ORDER_EQUAL_QUOTA_THEN_ROUND_ROBIN",
        default="COLLECT_INSPECT_QUEUE_ONLY", background_collection=False,
        external_code_execution=False, policy_update=False,
        candidate_is_validated_defect=False, oracle_independence="REQUIRES_EXPLICIT_REVIEW",
        registry_scope="KNOWN_PUBLIC_E1_E9_RECORDS_NOT_GLOBAL_COMPLETENESS",
        source_roles="DEVELOPMENT_ONLY_FINAL_FEEDBACK_FORBIDDEN")
    value["sha256"] = digest(value)
    return value


def run_harvest(workspace, *, repositories=None, max_candidates=50, max_details=10,
                max_qualifications=4, client=None):
    from .harvester_github import GitHubRestClient, discover_batch
    from .harvester_review import assess_candidate, build_consumed_registry, candidate_profile
    started = time.perf_counter()
    repositories = list(DEFAULT_REPOSITORIES if repositories is None else repositories)
    contract = discovery_contract(repositories,max_candidates,max_details,max_qualifications)
    registry = HarvestRegistry(workspace)
    known = registry.known_candidate_ids()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    batch_id = "harvest-"+now.strftime("%Y%m%dT%H%M%S")+"-"+secrets.token_hex(3)
    folder = registry.workspace / "batches" / batch_id
    code_files = sorted(Path(__file__).parent.glob("harvester*.py"))
    code_digest = digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files})
    consumed = build_consumed_registry()
    registration = dict(contract=contract,registered_at=now.isoformat(),code_digest=code_digest,
        known_candidates=len(known),consumed_registry=consumed)
    save_new(folder/"discovery-contract.json",registration)
    registry.append("BATCH",dict(phase="START",registration=registration),batch_id=batch_id)
    client = GitHubRestClient(registry.workspace/"github-cache") if client is None else client
    batch = discover_batch(client,repositories,max_candidates=max_candidates,max_details=max_details,
        max_qualifications=max_qualifications,known_candidate_ids=known)
    selected = set(batch["qualification_candidate_ids"])
    assessments, new, duplicate = [], 0, 0
    for candidate in batch["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in known:
            duplicate += 1
            continue
        if candidate_id in selected:
            assessment = assess_candidate(candidate,consumed_registry=consumed)
        else:
            assessment = dict(schema="tomolab-harvest-unreviewed-v1",candidate_id=candidate_id,
                status="HOLD_REVIEW",completed_stage=candidate.get("stage","DISCOVERED"),
                reasons=["NOT_SELECTED_WITHIN_FROZEN_QUALIFICATION_CAP"],split="development",
                oracle_independence="UNKNOWN",execution="NOT_EXECUTED")
        registry.register(candidate,assessment,batch_id=batch_id)
        registry.record_profile(candidate_id,candidate_profile(candidate),batch_id=batch_id)
        assessments.append(dict(candidate_id=candidate_id,assessment=assessment))
        new += 1
    current = registry.assessments()
    distribution = dict(sorted(Counter(row["status"] for row in current.values()).items()))
    profiles = registry.profiles()
    queue = [dict(candidate_id=cid,assessment=row,source_profile=profiles.get(cid)) for cid,row in sorted(current.items())
             if row["status"] != "DEVELOPMENT_ELIGIBLE"]
    save_new(folder/"review-queue.json",dict(schema="tomolab-harvest-review-queue-v1",items=queue))
    save_new(folder/"discovery-result-private.json",batch)
    eligible = distribution.get("DEVELOPMENT_ELIGIBLE",0)
    result = dict(schema="tomolab-harvest-result-v1",status="COMPLETE",batch_id=batch_id,
        contract_digest=contract["sha256"],code_digest=code_digest,
        registered_new=new,duplicates_skipped=duplicate,registry_candidates=len(current),
        discovered_this_batch=len(batch["candidates"]),distribution=distribution,
        review_queue_count=len(queue),source_profile_count=len(profiles),caps=batch["caps"],holds=batch["holds"],
        qualification_candidate_ids=batch["qualification_candidate_ids"],
        api_ledger=batch["api_ledger"],wall_seconds=time.perf_counter()-started,
        harvester_status="HARVESTER_FUNCTIONAL" if current else "HOLD_NO_CANDIDATES",
        recursive_update="NOT_EXECUTED_NO_ELIGIBLE_EXPERIENCE",
        m0="HOLD_INSUFFICIENT_LINEAGES" if eligible<4 else "REQUIRES_FROZEN_EXECUTION_CONTRACT",
        real_target_calls=0,real_oracle_calls=0,external_code_execution="NOT_EXECUTED_DEFAULT_DRY_RUN",
        transfer_utility="NOT_ESTABLISHED",oos="NOT_ESTABLISHED",performance_improvement="NOT_ESTABLISHED",
        new_unique_defects_discovered="NOT_ESTABLISHED_CANDIDATE_METADATA_ONLY",allow_release=False)
    registry.append("BATCH",dict(phase="COMPLETE",result=result),batch_id=batch_id)
    save_new(folder/"result.json",result)
    return result
