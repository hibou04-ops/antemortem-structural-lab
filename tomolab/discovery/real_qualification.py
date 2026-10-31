"""One exposed public regression, never a blind discovery or transfer result.

The original single candidate's public metadata projection omits upstream file,
license, and test-patch bodies. Official pinned downloads restore those bytes
and must reproduce its original metadata digest before any OCI call. Host code
only downloads, hashes, and parses upstream text. Opting in explicitly accepts
the bundled bounded contract, independent exhaustive Oracle, reset and MIT
notice review. Metadata alone grants no execution authority.
"""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import harvester_execution as execution
from .harvester_github import validate_candidate
from .harvester_review import assess_candidate, make_review, source_function_identity, validate_review_bundle
from .harvester_service import save_new
from .schema import digest

PUBLIC_PROJECTION = json.loads(r'''{"buggy_revision":"7f71a911232b2ef4f5396f16f5ea704d4315ce0c","candidate_id":"28c85a77103c1f1fddd26b09ca2aa8145582fe0a0974a1b87066a4c7f62bf528","changed_files":[{"additions":6,"deletions":6,"patch_present":true,"patch_sha256":"70007a6398a201695ca66149d1b774f6c36359ab6a8911f93b7a8ecf980b25e0","path":"algorithms/string/longest_palindromic_substring.py","previous_path":null,"sha":"d6272d08ecb1957ad716febfba5a69721f219baf","status":"modified"},{"additions":2,"deletions":0,"patch_present":true,"patch_sha256":"c9fbde8cbb84d7862dd0de9cf5d079d610f8167c817df629648c01a9de89cdf1","path":"tests/test_string.py","previous_path":null,"sha":"ca0ad0a4536a6b0fa4d21428f1508bade63a1b3d","status":"modified"}],"discovered_at":"2026-10-31T21:42:46+00:00","fixed_revision":"25772ca62d04a8bbd31faac27455c9fa94227b50","identity_support":{"consumption_status":"NOT_REVIEWED","independence_status":"NOT_ESTABLISHED","python_source_available":true,"raw_sources_verified":true,"source_files_inspected":1},"issues":["https://github.com/keon/algorithms/issues/2771"],"license":{"git_blob_sha":"76e14882e47d16548334bcdc1e116c239ec6ffb7","path":"LICENSE","revision":"25772ca62d04a8bbd31faac27455c9fa94227b50","sha256":"f676cbf8e504df7f12c9628ab17dddf686671d785f2a9f403098f29fadde4a96","spdx_id":"MIT","status":"ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW"},"metadata_digest":"4644cd09e527d2f69a14f073aefe95907023410860c976020d3b9b14fef7d72e","number":2772,"provenance":{"api_objects":[{"endpoint":"/search/issues?q=repo%3Akeon%2Falgorithms+is%3Apr+is%3Amerged+fix+in%3Atitle&sort=created&order=desc&per_page=8&page=1","raw_sha256":"306d724de602f131c223f0a56e110412f9fc3c3e96c6ae25c6e969f80fd2b743","status":200},{"endpoint":"/repos/keon/algorithms/pulls/2772","raw_sha256":"da7098d877dbbd5479117a6bb0dc99cd516f8d2e85f34ab2a419b297306886f7","status":200},{"endpoint":"/repos/keon/algorithms/commits/25772ca62d04a8bbd31faac27455c9fa94227b50","raw_sha256":"495cc28610d9eaa54d3e35df28e2e1c75a5988d82d5f446a67f5fbe291cdd95c","status":200},{"endpoint":"/repos/keon/algorithms/pulls/2772/files?per_page=50&page=1","raw_sha256":"08aadd890e588007c0cfac6b8ebc810b06e4db32311239dd11e97caedbd43cc5","status":200},{"endpoint":"/repos/keon/algorithms/license?ref=25772ca62d04a8bbd31faac27455c9fa94227b50","raw_sha256":"42cb07b251479794418afaa5acf2813a3741637a8360685a0396dcfe0538baaf","status":200},{"endpoint":"/repos/keon/algorithms/contents/algorithms/string/longest_palindromic_substring.py?ref=7f71a911232b2ef4f5396f16f5ea704d4315ce0c","raw_sha256":"d3a880ab9f9152195cebd41ab33d489587a4978bc515d6ea12db71ce4e900b08","status":200},{"endpoint":"/repos/keon/algorithms/contents/algorithms/string/longest_palindromic_substring.py?ref=25772ca62d04a8bbd31faac27455c9fa94227b50","raw_sha256":"789e0662d97e2623f54e4045ca6403ff5041a5cc56ee33d757ba0910421d4127","status":200}],"detail_reserved":true,"merge_commit_sha":"25772ca62d04a8bbd31faac27455c9fa94227b50","merged":true,"proposed_buggy_first_parent":true,"proposed_buggy_parent_sha":"7f71a911232b2ef4f5396f16f5ea704d4315ce0c","public_repository":true,"qualification_reserved":true,"reported_base_sha":"7f71a911232b2ef4f5396f16f5ea704d4315ce0c","reported_head_sha":"55a62f5f118ebdabde73d3276e38c620179d3dfd","repository_id":74073233},"repository":"keon/algorithms","source_blobs":[{"git_blob_sha":"1cb74d7ee82a7602cd1e982dbbc06551115791a8","path":"algorithms/string/longest_palindromic_substring.py","revision":"7f71a911232b2ef4f5396f16f5ea704d4315ce0c","sha256":"4d98567316e7bce6cbfc0c65a9a2629a366277e38c1215cf39427aefc403c84f"},{"git_blob_sha":"d6272d08ecb1957ad716febfba5a69721f219baf","path":"algorithms/string/longest_palindromic_substring.py","revision":"25772ca62d04a8bbd31faac27455c9fa94227b50","sha256":"575c7a2f2729f2b07b07a98bb07820923368810c6c7a464ab37fbab120a1b839"}],"source_url":"https://github.com/keon/algorithms/pull/2772","stage":"PROVENANCE_VERIFIED","test_evidence":{"patches":[{"path":"tests/test_string.py","sha256":"c9fbde8cbb84d7862dd0de9cf5d079d610f8167c817df629648c01a9de89cdf1"}],"paths":["tests/test_string.py"]},"title":"Fix/palindrome separator collision","unknown_reasons":["CONTRACT_ORACLE_RESET_AND_INDEPENDENCE_NOT_REVIEWED"]}''')
ORIGINAL_METADATA_DIGEST = "4644cd09e527d2f69a14f073aefe95907023410860c976020d3b9b14fef7d72e"
SOURCE_PATH = "algorithms/string/longest_palindromic_substring.py"
WITNESS = "a#a"
FUNCTION_IDENTITY = dict(
    canonical_function_identity="6b3b77a561f92763d4b9642f4a8744968db5cc78621eb6b4721385b0baaa749f",
    cross_revision_function_key="90166bfe2ec4379475def7be0491623f72140be4b87cfea2f5819898f5963610",
    normalized_ast_clone_sha256="6d65baca5e639c63034e8b5e89f1a73fec20dc65af9791a451e995c8bf9d61fe",
    implementation_sha256="4d98567316e7bce6cbfc0c65a9a2629a366277e38c1215cf39427aefc403c84f")
CONTRACT = dict(kind="text", alphabet="ab#", min_size=0, max_size=16,
    description="Return the longest contiguous palindromic substring. Equal lengths choose the earliest start; empty input returns empty text.",
    comparison=dict(exception_policy="unexpected"), preconditions=[])
RESET_SOURCE = "def reset():\n    return True\n"
PER_CALL_SECONDS = 30
CONTROLLER_SECONDS = 300
CLEANUP_RESERVE_SECONDS = 20
MIN_ENTRY_REMAINING_SECONDS = 25
FILES_URL = "https://api.github.com/repos/keon/algorithms/pulls/2772/files?per_page=50&page=1"


def reference(text):
    """Exhaustive original substrings, independent of Manacher and separators."""
    best = ""
    for start in range(len(text)):
        for end in range(start + 1, len(text) + 1):
            part = text[start:end]
            if part == part[::-1] and len(part) > len(best):
                best = part
    return best


ORACLE_SOURCE = inspect.getsource(reference)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise HTTPError(request.full_url, code, "unreviewed redirect", headers, fp)


def _download(url, *, timeout, maximum):
    """No auth, proxy credential, shell, retry, discovery, or redirect path."""
    allowed = {FILES_URL}
    for row in PUBLIC_PROJECTION["source_blobs"] + [PUBLIC_PROJECTION["license"]]:
        allowed.add("https://raw.githubusercontent.com/keon/algorithms/" + row["revision"] + "/" + row["path"])
    if url not in allowed or not 0 < timeout <= 10:
        raise ValueError("one bounded reviewed official download required")
    request = Request(url, headers={"User-Agent": "antemortem-public-qualification/1", "Accept": "application/vnd.github+json" if url == FILES_URL else "text/plain"})
    opener = build_opener(ProxyHandler({}), HTTPSHandler(), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("exact official source response required")
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("official source response exceeds byte bound")
    return raw


def _verified_text(raw, row):
    if type(raw) is not bytes or _sha(raw) != row["sha256"]:
        raise ValueError("pinned upstream SHA256 mismatch")
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != row["git_blob_sha"]:
        raise ValueError("pinned upstream Git blob identity mismatch")
    return raw.decode("utf-8")


def _restore_candidate(projection, payloads):
    """Restore the original envelope exactly; no receipt rebinding is possible."""
    candidate = deepcopy(projection)
    for index, row in enumerate(candidate["source_blobs"]):
        row["text"] = _verified_text(payloads["source" + str(index)], row)
        tree = ast.parse(row["text"])
        if (len(tree.body) != 3 or not isinstance(tree.body[0], ast.Expr)
                or not isinstance(tree.body[1], ast.ImportFrom) or tree.body[1].module != "__future__"
                or not isinstance(tree.body[2], ast.FunctionDef) or tree.body[2].name != "longest_palindrome"):
            raise ValueError("reviewed upstream module shape differs")
    candidate["license"]["text"] = _verified_text(payloads["license"], candidate["license"])
    files = json.loads(payloads["files"].decode("utf-8"))
    if type(files) is not list or len(files) > 50:
        raise ValueError("bounded original PR file metadata required")
    for patch in candidate["test_evidence"]["patches"]:
        matches = [row.get("patch") for row in files if type(row) is dict and row.get("filename") == patch["path"]]
        if len(matches) != 1 or type(matches[0]) is not str or _sha(matches[0].encode()) != patch["sha256"]:
            raise ValueError("original public test patch SHA256 mismatch")
        patch["text"] = matches[0]
    return validate_candidate(candidate)


def _prepare_case(deadline, downloads, source_directory):
    payloads = {}
    rows = [("source" + str(i), row, 256 * 1024) for i, row in enumerate(PUBLIC_PROJECTION["source_blobs"])]
    rows.append(("license", PUBLIC_PROJECTION["license"], 64 * 1024))
    for key, row, maximum in rows + [("files", None, 2 * 1024 * 1024)]:
        remaining = deadline - time.monotonic() - CLEANUP_RESERVE_SECONDS
        if remaining <= 0:
            raise TimeoutError("controller deadline before source download")
        url = FILES_URL if row is None else "https://raw.githubusercontent.com/keon/algorithms/" + row["revision"] + "/" + row["path"]
        raw = _download(url, timeout=min(10, remaining), maximum=maximum)
        payloads[key] = raw
        downloads.append(dict(role=key, url=url, sha256=_sha(raw), bytes=len(raw)))
        source_directory.mkdir(parents=True, exist_ok=True)
        with (source_directory / (key + ".txt")).open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    candidate = _restore_candidate(PUBLIC_PROJECTION, payloads)
    if candidate["metadata_digest"] != ORIGINAL_METADATA_DIGEST or source_function_identity(candidate, path=SOURCE_PATH, function="longest_palindrome") != FUNCTION_IDENTITY:
        raise ValueError("restored source identity does not bind the original development candidate")
    review = make_review(candidate, contract=CONTRACT,
        implementation_sha256=candidate["source_blobs"][0]["sha256"],
        fixed_implementation_sha256=candidate["source_blobs"][1]["sha256"],
        oracle_sha256=_sha(ORACLE_SOURCE.encode()), reset_adapter_sha256=_sha(RESET_SOURCE.encode()),
        function_identity=FUNCTION_IDENTITY,
        lineage=dict(source_lineage_id="keon-algorithms-pr2772-longest-palindrome", project_id="keon.algorithms",
                     mechanism_id="input-sentinel-collision-character-erasure", independence_id="exhaustive-original-substrings-v1"),
        review_ids=dict(contract_review_id="public-keon2772-bounded-text-v1", oracle_review_id="public-keon2772-exhaustive-oracle-v1",
                        reset_review_id="public-keon2772-pure-callable-v1", license_review_id="public-keon2772-pinned-mit-v1",
                        reviewer_id="explicit-public-case-execution-authority"),
        oracle_independence_basis="Authored from the contiguous-palindromic-substring definition: enumerate original slices and compare to their reversal. No Manacher transformed string, sentinel, radius reuse, or upstream implementation copy. Earliest tie is an explicit bounded specification inferred from ascending center traversal and strict best-radius improvement. An explicit execution opt-in accepts this reviewed scope, not global semantic fidelity.")
    bundle = execution.make_source_bundle(candidate["source_blobs"][0]["text"], candidate["source_blobs"][1]["text"], ORACLE_SOURCE, RESET_SOURCE,
        buggy_function="longest_palindrome", fixed_function="longest_palindrome")
    execution.validate_source_bundle(bundle, review=review)
    assessment = assess_candidate(candidate, review=review, trusted_review=True)
    if assessment["status"] != "HOLD_EXECUTION":
        raise PermissionError("existing qualification gate did not authorize the reproduction stage")
    return candidate, review, bundle


class _DeadlineLauncher:
    """Bound each Docker CLI call and confirm disposable-container cleanup.

    This is a controller deadline with cleanup reserve, not an OS hard kill
    guarantee. Timeout/protocol loss or cleanup uncertainty is preserved.
    """
    def __init__(self, deadline):
        self.deadline = deadline
        self.create_attempted = False
        self.cleanup = []
        self.cli_calls = []

    def factory(self):
        launcher = execution._launcher()
        launcher._run = self.run
        return launcher

    def run(self, arguments, *, timeout=60):
        cleanup = arguments[:3] == ["docker", "rm", "--force"]
        if arguments[:2] == ["docker", "create"]:
            self.create_attempted = True
        remaining = self.deadline - time.monotonic()
        budget = min(timeout, remaining if cleanup else remaining - CLEANUP_RESERVE_SECONDS)
        if budget <= 0:
            if cleanup:
                self.cleanup.append(dict(status="UNKNOWN_DEADLINE", removed=False, absence_verified=False))
            raise subprocess.TimeoutExpired(arguments[:2], max(0, budget))
        self.cli_calls.append(dict(operation=arguments[1] if len(arguments) > 1 else "UNKNOWN", timeout_seconds=budget))
        try:
            result = execution._bounded_run(arguments, timeout=budget)
        except Exception:
            if cleanup:
                self.cleanup.append(dict(status="UNKNOWN_CLEANUP_ERROR", removed=False, absence_verified=False))
            raise
        if cleanup:
            record = dict(status="UNKNOWN", removed=result.returncode == 0, absence_verified=False)
            self.cleanup.append(record)
            name = arguments[-1]
            if re.fullmatch(r"tomolab-historical-[a-f0-9]{32}", name) is None:
                raise ValueError("reviewed disposable container name required")
            left = self.deadline - time.monotonic()
            if result.returncode == 0 and left > 0:
                absent = execution._bounded_run(["docker", "container", "ls", "--all", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"], timeout=min(5, left))
                record["absence_verified"] = absent.returncode == 0 and absent.stdout.strip() == ""
            record["status"] = "PASS" if record["removed"] and record["absence_verified"] else "UNKNOWN"
            if record["status"] != "PASS":
                raise RuntimeError("disposable container cleanup is unverified")
        return result

    def evidence(self):
        status = "NOT_CREATED" if not self.create_attempted else "PASS" if len(self.cleanup) == 1 and self.cleanup[0]["status"] == "PASS" else "UNKNOWN"
        return dict(status=status, create_attempted=self.create_attempted, cleanup=deepcopy(self.cleanup), cli_calls=deepcopy(self.cli_calls))


def _image(value):
    if type(value) is not str or re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None:
        raise ValueError("reviewed immutable local OCI image sha256 identity required")
    return value


def _plan(image, enabled):
    runtime = {name:_sha((Path(execution.__file__).resolve().parents[1] / name).read_bytes()) for name in execution.RUNTIME_FILES}
    runtime["runner.py"] = _sha(execution.RUNNER.encode())
    plan = dict(schema="tomolab-public-real-qualification-plan-v1", created_at=datetime.now(timezone.utc).isoformat(), image=_image(image),
        candidate_id=PUBLIC_PROJECTION["candidate_id"], metadata_digest=ORIGINAL_METADATA_DIGEST, function_identity=deepcopy(FUNCTION_IDENTITY),
        public_projection_sha256=digest(PUBLIC_PROJECTION), source_url=PUBLIC_PROJECTION["source_url"], source_path=SOURCE_PATH,
        upstream_file_references=deepcopy(PUBLIC_PROJECTION["source_blobs"] + [PUBLIC_PROJECTION["license"]]),
        upstream_test_patch_references=deepcopy(PUBLIC_PROJECTION["test_evidence"]["patches"]),
        contract=deepcopy(CONTRACT), oracle_sha256=_sha(ORACLE_SOURCE.encode()), reset_sha256=_sha(RESET_SOURCE.encode()),
        first_party_runtime_digest=digest(runtime), controller_source_sha256=_sha(Path(__file__).read_bytes()),
        execution_backend_source_sha256=_sha(Path(execution.__file__).read_bytes()),
        witness=WITNESS, witness_origin="PUBLIC_UPSTREAM_REGRESSION_EXPOSED_DEVELOPMENT_NOT_BLIND", expected_fixed_result=WITNESS,
        schedule=[dict(variant=variant, repeat=repeat, selected=selected) for variant in ("buggy", "fixed") for repeat in range(3) for selected in (variant, "oracle")],
        resource_caps=dict(target_calls=6, oracle_calls=6, resets=12, fresh_containers=12, per_call_seconds=PER_CALL_SECONDS,
                           controller_seconds=CONTROLLER_SECONDS, cleanup_reserve_seconds=CLEANUP_RESERVE_SECONDS,
                           enter_only_if_remaining_at_least=MIN_ENTRY_REMAINING_SECONDS),
        execution_opt_in=enabled, automatic_retries=0, substitutions=0, learning_updates=0, allow_release=False,
        host_external_source_import=False, host_external_source_execution=False,
        claims=dict(new_bug_discovery=False, oos=False, final_evaluation=False, transfer=False, utility=False, sequence_int_m0_eligible=False),
        deadline_scope="CONTROLLER_PER_SUBPROCESS_BOUND_WITH_CLEANUP_RESERVE_NOT_OS_HARD_KILL_GUARANTEE",
        license=dict(spdx_id="MIT", sha256=PUBLIC_PROJECTION["license"]["sha256"], notice="Retain upstream copyright and permission notice with any copied source."))
    plan["sha256"] = digest(plan)
    return plan


def run_public_qualification(workspace, *, image, allow_external_execution=False):
    """One fresh workspace; False does no network/subprocess work, True runs once.

    Explicit True accepts the fixed source/contract/Oracle/reset/license review.
    The separate benign OCI control prerequisite is enforced by the caller's
    workflow. No failed run is replaced or retried by this entry point.
    """
    if type(allow_external_execution) is not bool:
        raise PermissionError("external execution authorization must be an exact boolean")
    plan = _plan(image, allow_external_execution)
    workspace = Path(workspace)
    if workspace.exists() or workspace.is_symlink():
        raise FileExistsError("qualification workspace must be a new path")
    workspace.mkdir(parents=True, exist_ok=False)
    public = workspace / "public"
    save_new(public / "execution-plan.json", plan)
    save_new(public / "execution-reservation.json", dict(plan_sha256=plan["sha256"], invocation_limit=1, automatic_retries=0))
    started = time.monotonic()
    deadline = started + CONTROLLER_SECONDS
    calls, validated_calls, controller, downloads, reasons = [], [], [], [], []
    attempts = 0
    reproduction = None
    review = None
    status = "HOLD_EXECUTION"
    if not allow_external_execution:
        reasons.append("EXTERNAL_EXECUTION_NOT_AUTHORIZED_NO_DOWNLOAD_OR_SUBPROCESS")
    else:
        try:
            candidate, review, bundle = _prepare_case(deadline, downloads, workspace / "downloaded-source-data")
            validate_review_bundle(candidate, review)
            save_new(public / "review.json", review)
            pairs = dict(buggy=[], fixed=[])
            pending = None
            for index, entry in enumerate(plan["schedule"]):
                if deadline - time.monotonic() < MIN_ENTRY_REMAINING_SECONDS:
                    reasons.append("CONTROLLER_ENTRY_DEADLINE_RESERVE")
                    break
                adapter = _DeadlineLauncher(deadline)
                attempts += 1
                try:
                    record = execution.execute_reviewed_case(candidate, review, bundle, variant=entry["selected"], input=WITNESS, image=image,
                        output_directory=public / "calls" / (str(index + 1).zfill(2) + "-" + entry["selected"]),
                        allow_external_execution=True, trusted_review=True, timeout=PER_CALL_SECONDS, launcher_factory=adapter.factory)
                finally:
                    boundary = adapter.evidence()
                    controller.append(dict(index=index, cleanup=boundary))
                calls.append(record)
                execution.validate_execution_receipt(candidate, review, record)
                validated_calls.append(record)
                controller[-1]["execution_receipt_sha256"] = record["sha256"]
                if record["status"] != "COMPLETE" or boundary["status"] != "PASS":
                    reasons.append("FIRST_UNRESOLVED_CALL_STOP_NO_RETRY")
                    break
                if record["boundary"]["inspection"]["image_id"] != image or record["runtime_digest"] != plan["first_party_runtime_digest"] or record["bundle_digest"] != bundle["bundle_digest"]:
                    reasons.append("FROZEN_IMAGE_RUNTIME_BUNDLE_MISMATCH")
                    break
                if entry["selected"] != "oracle":
                    pending = record
                else:
                    pairs[entry["variant"]].append(dict(target=pending, oracle=record))
                    pending = None
            if len(calls) == 12 and not reasons:
                reproduction = execution.make_reproduction_receipt(candidate, review, pairs["buggy"], pairs["fixed"])
                execution.validate_reproduction_receipt(candidate, review, reproduction)
                save_new(public / "reproduction.json", reproduction)
                if reproduction["status"] == "REPRODUCED":
                    status = "REPRODUCED"
                else:
                    reasons.extend(reproduction["reasons"])
        except Exception as error:
            reasons.append("PREPARATION_OR_EXECUTION_" + type(error).__name__)
    elapsed = time.monotonic() - started
    if not math.isfinite(elapsed) or elapsed > CONTROLLER_SECONDS:
        status = "HOLD_EXECUTION"
        reasons.append("CONTROLLER_ELAPSED_BOUND_EXCEEDED")
    counts = {name:sum(row[name] for row in validated_calls if row[name] is not None) for name in ("external_target_calls", "external_oracle_calls", "external_reset_calls")}
    unknown = attempts - len(validated_calls) + sum(any(row[name] is None for name in counts) for row in validated_calls)
    if unknown or any(row["cleanup"]["status"] == "UNKNOWN" for row in controller):
        status = "HOLD_EXECUTION"
        reasons.append("UNKNOWN_CALL_COUNTS_OR_CLEANUP")
    if status == "REPRODUCED" and (counts != dict(external_target_calls=6, external_oracle_calls=6, external_reset_calls=12) or unknown or len(controller) != 12):
        status = "HOLD_EXECUTION"
        reasons.append("ACTUAL_CALL_BUDGET_NOT_EXACT")
    receipt = dict(schema="tomolab-public-real-qualification-receipt-v1", plan_sha256=plan["sha256"], status=status, reasons=sorted(set(reasons)),
        candidate_id=plan["candidate_id"], metadata_digest=ORIGINAL_METADATA_DIGEST, function_identity=deepcopy(FUNCTION_IDENTITY),
        public_projection_sha256=plan["public_projection_sha256"], review_digest=review["review_digest"] if review else None,
        reconstruction="EXACT_ORIGINAL_METADATA_DIGEST_VERIFIED" if review else "NOT_COMPLETED", image=image,
        downloads=downloads, execution_attempts=attempts, calls=calls, controller_ledger=controller, reproduction=reproduction, actual_known_counts=counts,
        unknown_external_call_records=unknown, controller_wall_seconds=elapsed, host_external_source_imported=False,
        automatic_retries=0, learning_updates=0, evidence_scope="ONE_EXPOSED_PUBLIC_REGRESSION_DEVELOPMENT_REPRODUCTION_ONLY")
    receipt["sha256"] = digest(receipt)
    save_new(public / "qualification-receipt.json", receipt)
    summary = dict(schema="tomolab-public-real-qualification-summary-v1", status=status, reasons=receipt["reasons"], receipt_sha256=receipt["sha256"],
        plan_sha256=plan["sha256"], candidate_id=plan["candidate_id"], metadata_digest=ORIGINAL_METADATA_DIGEST,
        source_url=plan["source_url"], witness=WITNESS, witness_is_public=True, blind=False, image=image,
        actual_known_counts=counts, unknown_external_call_records=unknown, fresh_complete_call_records=sum(r["status"] == "COMPLETE" for r in validated_calls),
        controller_wall_seconds=elapsed, default_execution_disabled=not allow_external_execution, development_eligibility="REQUIRES_EXISTING_REGISTRY_REVIEW_GATE",
        m0="HOLD_ONE_TEXT_LINEAGE_IS_NOT_FOUR_SEQUENCE_INT_LINEAGES", oos="NOT_ESTABLISHED", transfer="NOT_ESTABLISHED", utility="NOT_ESTABLISHED",
        new_unique_defects="NOT_ESTABLISHED_PUBLIC_KNOWN_WITNESS", policy_updates=0, allow_release=False)
    summary["sha256"] = digest(summary)
    save_new(public / "summary.json", summary)
    return dict(receipt=receipt, summary=summary)
