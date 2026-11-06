"""One frozen sequence-int qualification batch; no host upstream execution.

Scope is exposed public development reproduction, not M0, blind discovery,
policy comparison or utility. Default invocation performs no downloads or OCI
calls. Source bytes are restored from public pinned refs and checked against
the original candidate metadata before the existing OCI validator is entered.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
from pathlib import Path, PurePosixPath
import re
import time
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import harvester_execution as execution
from .harvester_github import validate_candidate, _json
from .harvester_review import assess_candidate, make_review, source_function_identity, validate_review_bundle
from .harvester_service import save_new
from .online_schema import input_identity, validate_contract, validate_input
from .real_qualification import _DeadlineLauncher
from .schema import digest, keys

SCHEMA = "tomolab-sequence-qualification-manifest-v1"
TRACK = "TRACK_SEQ_INT"
APPROVED_MANIFEST_DIGEST = "7416363e23def8cb91fdc2988cf65845535ce900b402985fa518459be7a4eefb"
CONTROLLER_SECONDS = 600
PER_CALL_SECONDS = 30
CLEANUP_RESERVE_SECONDS = 20
MIN_ENTRY_SECONDS = 25
RESET_SOURCE = "def reset():\n    return True\n"


def whole_value_reference(point):
    """Whole-value multiset specification, independent of radix digits."""
    if type(point) is not list or not 1 <= len(point) <= 8 or any(type(v) is not int or not 0 <= v <= 99 for v in point):
        raise ValueError("bounded nonempty exact integer list required")
    result = []
    for value in range(min(point), max(point) + 1):
        count = 0
        for original in point:
            if original == value:
                count += 1
        for _ in range(count):
            result.append(value)
    return result


def decimal_increment_reference(point):
    """Increment the whole decimal value, then retain original minimum width."""
    if type(point) is not list or not 1 <= len(point) <= 8 or any(type(v) is not int or not 0 <= v <= 9 for v in point):
        raise ValueError("bounded nonempty exact decimal digits required")
    value = 0
    for digit in point:
        value = 10 * value + digit
    value += 1
    result = []
    while value:
        value, digit = divmod(value, 10)
        result.insert(0, digit)
    while len(result) < len(point):
        result.insert(0, 0)
    return result


ORACLE_SOURCES = {
    "WHOLE_VALUE_COUNT_SORT": inspect.getsource(whole_value_reference).replace("def whole_value_reference(", "def reference(", 1),
    "WIDTH_PRESERVING_DECIMAL_INCREMENT": inspect.getsource(decimal_increment_reference).replace("def decimal_increment_reference(", "def reference(", 1),
}


def _sha(raw): return hashlib.sha256(raw).hexdigest()


def public_projection(candidate):
    """Remove every upstream body while retaining its original digest binding."""
    value = validate_candidate(candidate)
    for row in value["source_blobs"]: row.pop("text")
    value["license"].pop("text")
    for row in value["test_evidence"]["patches"]: row.pop("text")
    return value


def _safe_path(value):
    if (type(value) is not str or not 1 <= len(value) <= 1024 or "\\" in value
        or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
        or any(ord(c) < 32 for c in value)):
        raise ValueError("bounded relative original source path required")
    return value


def validate_manifest(manifest):
    keys(manifest, ("schema", "track", "plan_digest", "scope", "cases", "resource_caps", "historical_text", "manifest_digest"))
    actual = digest({k:v for k,v in manifest.items() if k != "manifest_digest"})
    if manifest["manifest_digest"] != actual or actual != APPROVED_MANIFEST_DIGEST:
        raise PermissionError("exact reviewed source-bound sequence manifest required")
    if manifest["schema"] != SCHEMA or manifest["track"] != TRACK:
        raise PermissionError("only the separately approved sequence-int track may execute")
    if type(manifest["cases"]) is not list or not 1 <= len(manifest["cases"]) <= 4:
        raise ValueError("one to four frozen reviewed cases required")
    n = len(manifest["cases"])
    expected_caps = dict(target_calls=6*n, oracle_calls=6*n, fresh_reset_count=12*n,
        fresh_containers=12*n, controller_seconds=600, per_call_seconds=30, cleanup_reserve_seconds=20)
    if manifest["resource_caps"] != expected_caps:
        raise ValueError("fixed per-case6T6O12freshreset and whole batch resource caps required")
    identities = set()
    for case in manifest["cases"]:
        keys(case, ("case_id", "projection", "source_path", "function", "function_identity", "contract", "witness", "witness_origin",
            "oracle_key", "oracle_sha256", "reset_sha256", "lineage", "review_ids", "oracle_independence_basis", "review_digest",
            "static_contract_support_digest", "contract_scope"))
        projection = case["projection"]
        if case["case_id"] != projection["candidate_id"] or case["case_id"] in identities:
            raise ValueError("distinct exact original candidate IDs required")
        identities.add(case["case_id"])
        if type(projection["repository"]) is not str or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", projection["repository"]) is None:
            raise ValueError("original public repository identity required")
        if projection["provenance"]["public_repository"] is not True:
            raise PermissionError("only public upstream provenance is permitted")
        for source in projection["source_blobs"]:
            if "text" in source: raise ValueError("public projection cannot contain upstream source bodies")
            _safe_path(source["path"])
            if re.fullmatch(r"[a-f0-9]{40}", source["revision"]) is None: raise ValueError("immutable revision required")
        if "text" in projection["license"] or any("text" in p for p in projection["test_evidence"]["patches"]):
            raise ValueError("public projection cannot contain license or patch bodies")
        _safe_path(projection["license"]["path"]); _safe_path(case["source_path"])
        if type(case["function"]) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", case["function"]) is None:
            raise ValueError("one original callable export required")
        contract = validate_contract(case["contract"])
        if contract["kind"] != "sequence_int" or not validate_input(case["witness"], contract):
            raise ValueError("exact typed sequence witness must satisfy the frozen contract")
        if case["oracle_key"] not in ORACLE_SOURCES or _sha(ORACLE_SOURCES[case["oracle_key"]].encode()) != case["oracle_sha256"]:
            raise ValueError("first-party independent Oracle identity differs")
        if case["reset_sha256"] != _sha(RESET_SOURCE.encode()): raise ValueError("fresh-process reset identity differs")
    return deepcopy(manifest)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise HTTPError(request.full_url, code, "unreviewed redirect", headers, fp)


def _urls(case):
    projection = case["projection"]
    root = "https://raw.githubusercontent.com/" + projection["repository"] + "/"
    urls = [("source" + str(i), root + source["revision"] + "/" + source["path"], source, 262144)
        for i,source in enumerate(projection["source_blobs"])]
    license = projection["license"]
    urls.append(("license", root + license["revision"] + "/" + license["path"], license, 65536))
    if projection["test_evidence"]["patches"]:
        urls.append(("files", "https://api.github.com/repos/" + projection["repository"] + "/pulls/" + str(projection["number"]) + "/files?per_page=50&page=1", None, 2097152))
    return urls


def _download(url, *, allowed, timeout, maximum):
    if url not in allowed or not 0 < timeout <= 10:
        raise ValueError("one frozen official download required")
    request = Request(url, headers={"User-Agent": "antemortem-sequence-qualification/1", "Accept": "application/vnd.github+json" if "api.github.com" in url else "text/plain"})
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("official pinned response status or origin differs")
        raw = response.read(maximum + 1)
    if len(raw) > maximum: raise ValueError("pinned source preparation response exceeds bound")
    return raw


def _cached_payload(cache, url, *, maximum):
    """Read frozen bytes only; a cache miss never falls back to the network."""
    cache=Path(cache).resolve(strict=True)
    index=cache/"index.json"
    if index.is_symlink() or index.stat().st_size>131072:
        raise ValueError("bounded regular source cache index required")
    data=_json(index.read_bytes())
    keys(data,("schema","entries"))
    if data["schema"]!="tomolab-offline-sequence-source-v1":
        raise ValueError("reviewed offline cache schema required")
    row=data["entries"][url]
    keys(row,("path","sha256","bytes","role","origin"))
    if re.fullmatch(r"[a-f0-9]{64}\.txt",row["path"]) is None or row["path"]!=row["sha256"]+".txt":
        raise ValueError("content-addressed flat source data required")
    path=cache/row["path"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size>maximum:
        raise ValueError("bounded regular source data required")
    raw=path.read_bytes()
    if len(raw)!=row["bytes"] or len(raw)>maximum or _sha(raw)!=row["sha256"]:
        raise ValueError("offline source cache digest/size differs")
    return raw


def _restore_candidate(case, payloads):
    candidate = deepcopy(case["projection"])
    for i,row in enumerate(candidate["source_blobs"]):
        raw=payloads["source"+str(i)]
        if _sha(raw)!=row["sha256"] or hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=row["git_blob_sha"]:
            raise ValueError("pinned source bytes/Git blob mismatch")
        row["text"]=raw.decode("utf8")
    raw=payloads["license"]
    if _sha(raw)!=candidate["license"]["sha256"] or hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=candidate["license"]["git_blob_sha"]:
        raise ValueError("original license bytes/Git blob mismatch")
    candidate["license"]["text"]=raw.decode("utf8")
    if candidate["test_evidence"]["patches"]:
        files=_json(payloads["files"])
        if type(files) is not list or len(files)>50: raise ValueError("bounded original public PR files required")
        for patch in candidate["test_evidence"]["patches"]:
            matches=[row.get("patch") for row in files if type(row) is dict and row.get("filename")==patch["path"]]
            if len(matches)!=1 or type(matches[0]) is not str or _sha(matches[0].encode())!=patch["sha256"]:
                raise ValueError("original test patch digest differs")
            patch["text"]=matches[0]
    return validate_candidate(candidate)


def _review_and_bundle(case, candidate):
    if source_function_identity(candidate,path=case["source_path"],function=case["function"]) != case["function_identity"]:
        raise ValueError("restored original function identity differs")
    before=next(row for row in candidate["source_blobs"] if row["path"]==case["source_path"] and row["revision"]==candidate["buggy_revision"])
    after=next(row for row in candidate["source_blobs"] if row["path"]==case["source_path"] and row["revision"]==candidate["fixed_revision"])
    review=make_review(candidate,contract=case["contract"],implementation_sha256=before["sha256"],fixed_implementation_sha256=after["sha256"],
        oracle_sha256=case["oracle_sha256"],reset_adapter_sha256=case["reset_sha256"],function_identity=case["function_identity"],
        lineage=case["lineage"],review_ids=case["review_ids"],oracle_independence_basis=case["oracle_independence_basis"])
    if review["review_digest"]!=case["review_digest"]: raise ValueError("review does not reproduce the frozen preexecution digest")
    validate_review_bundle(candidate,review)
    bundle=execution.make_source_bundle(before["text"],after["text"],ORACLE_SOURCES[case["oracle_key"]],RESET_SOURCE,
        buggy_function=case["function"],fixed_function=case["function"])
    execution.validate_source_bundle(bundle,review=review)
    if assess_candidate(candidate,review=review,trusted_review=True)["status"]!="HOLD_EXECUTION":
        raise PermissionError("existing review gate did not authorize reproduction")
    return review,bundle


def run_sequence_qualification(workspace, *, manifest, image, allow_external_execution=False, trusted_review=False, source_cache=None):
    """Strict dual opt-in, immutable pinned data, one schedule and no host fallback."""
    if type(allow_external_execution) is not bool or type(trusted_review) is not bool:
        raise PermissionError("execution and review authority must be exact booleans")
    manifest=validate_manifest(manifest)
    if type(image) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}",image) is None:
        raise ValueError("immutable same-run reviewed image SHA required")
    workspace=Path(workspace)
    if workspace.exists() or workspace.is_symlink(): raise FileExistsError("fresh one-use sequence qualification workspace required")
    workspace.mkdir(parents=True,exist_ok=False)
    public=workspace/"public"
    runtime={name:_sha((Path(execution.__file__).resolve().parents[1]/name).read_bytes()) for name in execution.RUNTIME_FILES}
    runtime["runner.py"]=_sha(execution.RUNNER.encode())
    plan=dict(schema="tomolab-sequence-qualification-plan-v1",track=TRACK,manifest_digest=manifest["manifest_digest"],
        image=image,created_at=datetime.now(timezone.utc).isoformat(),resource_caps=manifest["resource_caps"],
        case_bindings=[dict(candidate_id=c["case_id"],metadata_digest=c["projection"]["metadata_digest"],review_digest=c["review_digest"],
            function_identity=c["function_identity"],contract_digest=digest(c["contract"]),input_digest=input_identity(c["witness"]),
            oracle_sha256=c["oracle_sha256"],reset_sha256=c["reset_sha256"],witness=c["witness"],witness_origin=c["witness_origin"]) for c in manifest["cases"]],
        runtime_digest=digest(runtime),controller_source_sha256=_sha(Path(__file__).read_bytes()),backend_source_sha256=_sha(Path(execution.__file__).read_bytes()),
        allow_external_execution=allow_external_execution,trusted_review=trusted_review,source_mode="OFFLINE_CACHE_NO_NETWORK_FALLBACK" if source_cache is not None else "PINNED_OFFICIAL_DOWNLOAD",automatic_retries=0,substitutions=0,
        schedule=[dict(case_id=c["case_id"],variant=v,repeat=i,selected=s) for c in manifest["cases"] for v in ("buggy","fixed") for i in range(3) for s in (v,"oracle")],
        claims=dict(new_blind_bug=False,oos=False,transfer=False,utility=False,m0=False,learning_updates=0),
        historical_text=manifest["historical_text"],deadline_scope="COOPERATIVE_CONTROLLER_WITH_PER_SUBPROCESS_TIMEOUT_AND_CLEANUP_RESERVE_NOT_GLOBAL_OS_HARDKILL")
    plan["sha256"]=digest(plan)
    save_new(public/"execution-plan.json",plan)
    save_new(public/"execution-reservation.json",dict(plan_sha256=plan["sha256"],invocation_limit=1,reserved=manifest["resource_caps"],automatic_retries=0))
    started=time.monotonic();deadline=started+CONTROLLER_SECONDS
    attempts=0;calls=[];validated=[];controllers=[];downloads=[];preparation=[];case_results=[];reasons=[];container_ids=set()
    if allow_external_execution is not True or trusted_review is not True:
        reasons.append("EXTERNAL_EXECUTION_AND_REVIEW_NOT_BOTH_AUTHORIZED_NO_DOWNLOAD_OR_SUBPROCESS")
    else:
        try:
            for case_index,case in enumerate(manifest["cases"]):
                payloads={};urls=_urls(case);allowed={u for _,u,_,_ in urls}
                for download_index,(role,url,reference,maximum) in enumerate(urls):
                    left=deadline-time.monotonic()-CLEANUP_RESERVE_SECONDS
                    if left<=0: raise TimeoutError("source preparation deadline")
                    save_new(public/"download-reservations"/f"{case_index:02d}-{download_index:02d}.json",dict(case_id=case["case_id"],role=role,url=url,plan_sha256=plan["sha256"]))
                    download_attempt=dict(case_id=case["case_id"],role=role,url=url,status="ATTEMPTED",response_bytes=None)
                    preparation.append(download_attempt)
                    try:
                        raw=(_cached_payload(source_cache,url,maximum=maximum) if source_cache is not None else _download(url,allowed=allowed,timeout=min(10,left),maximum=maximum))
                    except Exception as error:
                        download_attempt.update(status="UNKNOWN_FAILED_DOWNLOAD",error=type(error).__name__)
                        raise
                    download_attempt.update(status="COMPLETE",response_bytes=len(raw),sha256=_sha(raw))
                    payloads[role]=raw
                    downloads.append(dict(case_id=case["case_id"],role=role,url=url,sha256=_sha(raw),bytes=len(raw),origin="OFFLINE_CACHE" if source_cache is not None else "OFFICIAL_DOWNLOAD"))
                    data_path=workspace/"downloaded-source-data"/case["case_id"]/f"{role}.txt"
                    data_path.parent.mkdir(parents=True,exist_ok=True)
                    with data_path.open("xb") as stream:stream.write(raw)
                candidate=_restore_candidate(case,payloads)
                review,bundle=_review_and_bundle(case,candidate)
                case_public=public/"cases"/case["case_id"]
                save_new(case_public/"review.json",review)
                pairs=dict(buggy=[],fixed=[])
                for variant in ("buggy","fixed"):
                    for repeat in range(3):
                        pending=None
                        for selected in (variant,"oracle"):
                            if deadline-time.monotonic()<MIN_ENTRY_SECONDS: raise TimeoutError("entry cleanup reserve")
                            if attempts>=manifest["resource_caps"]["fresh_containers"]: raise PermissionError("frozen total entry cap")
                            adapter=_DeadlineLauncher(deadline)
                            call_index=attempts+1
                            save_new(public/"entry-reservations"/f"{call_index:02d}.json",dict(case_id=case["case_id"],variant=selected,
                                repeat=repeat,plan_sha256=plan["sha256"],reserved_target=int(selected!="oracle"),reserved_oracle=int(selected=="oracle"),reserved_reset=1))
                            attempts+=1
                            try:
                                record=execution.execute_reviewed_case(candidate,review,bundle,variant=selected,input=case["witness"],image=image,
                                    output_directory=case_public/"calls"/f"{call_index:02d}-{selected}",allow_external_execution=True,trusted_review=True,
                                    timeout=PER_CALL_SECONDS,launcher_factory=adapter.factory)
                            finally:
                                cleanup=adapter.evidence()
                                controllers.append(dict(case_id=case["case_id"],index=call_index,cleanup=cleanup))
                            calls.append(record)
                            execution.validate_execution_receipt(candidate,review,record)
                            validated.append(record)
                            controllers[-1]["execution_receipt_sha256"]=record["sha256"]
                            if record["status"]!="COMPLETE" or cleanup["status"]!="PASS": raise RuntimeError("first unresolved call or cleanup; no retry")
                            cid=record["boundary"]["inspection"]["container_id"]
                            if cid in container_ids: raise ValueError("container reused across frozen calls")
                            container_ids.add(cid)
                            if record["boundary"]["inspection"]["image_id"]!=image or record["runtime_digest"]!=plan["runtime_digest"] or record["bundle_digest"]!=bundle["bundle_digest"]:
                                raise ValueError("same-run frozen image/runtime/bundle mismatch")
                            if selected!="oracle":pending=record
                            else:pairs[variant].append(dict(target=pending,oracle=record))
                reproduction=execution.make_reproduction_receipt(candidate,review,pairs["buggy"],pairs["fixed"])
                execution.validate_reproduction_receipt(candidate,review,reproduction)
                save_new(case_public/"reproduction.json",reproduction)
                case_results.append(dict(candidate_id=case["case_id"],track=TRACK,status=reproduction["status"],reproduction_digest=reproduction["sha256"],
                    metadata_digest=candidate["metadata_digest"],review_digest=review["review_digest"],actual_target_calls=6,actual_oracle_calls=6,fresh_reset_count=12))
                if reproduction["status"]!="REPRODUCED":raise RuntimeError("fixed frozen witness was not reproduced; no replacement")
        except Exception as error:
            reasons.append("PREPARATION_OR_EXECUTION_"+type(error).__name__)
    elapsed=time.monotonic()-started
    fields=("external_target_calls","external_oracle_calls","external_reset_calls")
    lower={key:sum(r[key] for r in validated if r[key] is not None) for key in fields}
    unknown=attempts-len(validated)+sum(any(r[key] is None for key in fields) for r in validated)
    if unknown:reasons.append("UNKNOWN_EXTERNAL_CALL_COUNTS")
    if any(row["cleanup"]["status"]=="UNKNOWN" for row in controllers):reasons.append("UNKNOWN_CLEANUP")
    expected=dict(zip(fields,(manifest["resource_caps"]["target_calls"],manifest["resource_caps"]["oracle_calls"],manifest["resource_caps"]["fresh_reset_count"])))
    if not math.isfinite(elapsed) or elapsed>CONTROLLER_SECONDS:reasons.append("BATCH_DEADLINE_EXCEEDED")
    complete=not reasons and len(case_results)==len(manifest["cases"]) and lower==expected and len(container_ids)==12*len(case_results)
    counts={key:None if unknown else value for key,value in lower.items()}
    receipt=dict(schema="tomolab-sequence-qualification-receipt-v1",track=TRACK,status="REPRODUCED" if complete else "HOLD_EXECUTION",
        plan_sha256=plan["sha256"],manifest_digest=manifest["manifest_digest"],image=image,reasons=sorted(set(reasons)),
        reserved_calls=manifest["resource_caps"],wrapper_execution_attempts=attempts,validated_execution_receipts=len(validated),
        actual_entry_counts=counts,known_call_lower_bound=lower,unknown_external_call_records=unknown,
        actual_distinct_container_ids=len(container_ids),calls=calls,controller_ledger=controllers,downloads=downloads,cases=case_results,
        source_preparation_attempts=len(preparation),source_preparation_unknown_requests=sum(r["status"]!="COMPLETE" for r in preparation),
        source_preparation_ledger=preparation,source_preparation_known_response_bytes=sum(r["response_bytes"] for r in preparation if r["response_bytes"] is not None),
        controller_wall_seconds=elapsed,actual_source_host_imports=0,actual_source_host_execution=0,
        source_mode=plan["source_mode"],additional_source_gets=0 if source_cache is not None else len(downloads),
        host_callable_meter_scope="NOT_USED; OCI_ACTUAL_COUNTS_FROM_VALIDATED_EXTERNAL_EXECUTION_RECEIPTS",
        automatic_retries=0,substitutions=0,learning_updates=0,m0_status="NOT_EXECUTED",m0_pair_count=0,
        m0="HOLD_PENDING_SEPARATE_FOUR_COMMON_CONTRACT_LINEAGE_GATE",utility="NOT_ESTABLISHED",oos="NOT_ESTABLISHED",
        equal_cost_comparison_status="NOT_EXECUTED",equal_cost_pair_count=0,local_gain=None,local_loss=None,measurement_unknown=None,
        historical_text=manifest["historical_text"],this_run_text_target_calls=0,this_run_text_oracle_calls=0,allow_release=False)
    receipt["sha256"]=digest(receipt)
    save_new(public/"qualification-receipt.json",receipt)
    summary={k:deepcopy(v) for k,v in receipt.items() if k not in {"calls","controller_ledger","downloads","source_preparation_ledger"}}
    summary["schema"]="tomolab-sequence-qualification-summary-v1"
    summary["receipt_sha256"]=receipt["sha256"]
    summary.pop("sha256")
    summary["sha256"]=digest(summary)
    save_new(public/"summary.json",summary)
    return dict(receipt=receipt,summary=summary)
