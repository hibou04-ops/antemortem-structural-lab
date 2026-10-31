"""Data-only evidence qualification. Metadata never authorizes external execution.

Review IDs bind accountable host review; hashes cannot prove semantic Oracle
independence. External source text is parsed, never imported on the host.
"""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sysconfig
from urllib.parse import urlsplit

from .evaluation_usage import identity_tokens
from .online_schema import validate_contract
from .schema import canonical, digest, identifier, keys

REVIEW_SCHEMA = "tomolab-harvester-review-v1"
ASSESSMENT_SCHEMA = "tomolab-harvester-assessment-v1"
PROFILE_SCHEMA = "tomolab-harvester-candidate-profile-v1"
CONSUMED_SCHEMA = "tomolab-harvester-consumed-v1"
CONSUMED_SNAPSHOT_DIGEST = "9bc758c5746e3e52cf0ca24361f3ce2efff9db738eedc9b37166e63a03832b12"
STATES = ("DISCOVERED", "PROVENANCE_VERIFIED", "CONTRACT_REVIEWED", "ORACLE_REVIEWED",
          "REPRODUCED", "DEVELOPMENT_ELIGIBLE", "REJECTED", "UNKNOWN", "HOLD_REVIEW", "HOLD_EXECUTION")
REVIEW_IDS = ("contract_review_id", "oracle_review_id", "reset_review_id", "license_review_id", "reviewer_id")
LINEAGE_FIELDS = ("source_lineage_id", "project_id", "mechanism_id", "independence_id")
REVIEW_FIELDS = ("schema", "candidate_id", "metadata_digest", "split", "review_id", "contract",
    "implementation_sha256", "fixed_implementation_sha256", "oracle_sha256", "reset_adapter_sha256",
    "function_identity", "source_path", "exports", "lineage", "review_ids", "oracle_independence_basis", "reset_strategy", "review_digest")


def _sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise ValueError("explicit SHA256 identity required")
    return value


def _candidate(candidate):
    from .harvester_github import validate_candidate
    return validate_candidate(candidate)


def _signed(value, field):
    return dict(value, **{field: digest(value)})


def candidate_profile(candidate):
    """Bound file-backed metadata, leaving unreviewed semantic identities UNKNOWN.

    A Python file suffix is evidence of the upstream file's declared language,
    not a supported input contract, selected function, mechanism, or Oracle.
    """
    candidate = _candidate(candidate)
    references = [dict(path=blob["path"],revision=blob["revision"],git_blob_sha=blob["git_blob_sha"],
                       sha256=blob["sha256"]) for blob in candidate["source_blobs"]]
    python_files = [deepcopy(row) for row in references if row["path"].lower().endswith(".py")]
    value = dict(schema=PROFILE_SCHEMA,candidate_id=candidate["candidate_id"],
        metadata_digest=candidate["metadata_digest"],language="Python" if python_files else "UNKNOWN",
        language_evidence=python_files,library=candidate["repository"],input_type="UNKNOWN",mechanism="UNKNOWN",
        implementation_identity=dict(status="UPSTREAM_FILE_BYTES_VERIFIED_FUNCTION_NOT_REVIEWED" if references else "UNKNOWN",
            references=references,selected_function_identity="UNKNOWN"),
        input_contract_identity="UNKNOWN",oracle_identity="UNKNOWN",
        evidence_scope="FILE_PROVENANCE_ONLY_NOT_SEMANTIC_OR_EXECUTION_QUALIFICATION")
    return _signed(value,"sha256")


def validate_candidate_profile(candidate, profile):
    """Recompute the profile from its exact immutable candidate envelope."""
    expected = candidate_profile(candidate)
    if profile != expected:
        raise ValueError("candidate profile differs from exact source-backed metadata")
    return deepcopy(profile)


def _verify_digest(value, field):
    _sha(value.get(field))
    if value[field] != digest({k:v for k,v in value.items() if k != field}):
        raise ValueError("harvester review content digest mismatch")


def static_source_review(source):
    """Syntax/shape triage only. Absence of a flagged node is not safety proof."""
    if type(source) is not str or len(source.encode("utf-8")) > 256 * 1024:
        raise ValueError("bounded Python source text required")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as error:
        return dict(status="UNKNOWN", reason="PYTHON_SYNTAX_UNSUPPORTED", functions=[],
                    flags=[type(error).__name__], host_imported=False)
    functions = []
    flags = set()
    for index,node in enumerate(ast.walk(tree)):
        if index >= 20000:
            return dict(status="UNKNOWN",reason="STATIC_AST_NODE_CAP",functions=[],flags=["REVIEW_REQUIRED"],host_imported=False)
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            flags.add("ASYNC_OR_GENERATOR_REQUIRES_REVIEW")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "exec", "eval", "compile", "__import__", "open", "input"}:
            flags.add("EXECUTION_OR_IO_PRIMITIVE_REQUIRES_REVIEW")
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        if len(functions) >= 256:
            return dict(status="UNKNOWN",reason="STATIC_FUNCTION_COUNT_CAP",functions=[],flags=["REVIEW_REQUIRED"],host_imported=False)
        try:
            clone = deepcopy(node)
        except (RecursionError,MemoryError):
            return dict(status="UNKNOWN",reason="STATIC_AST_RESOURCE_LIMIT",functions=[],flags=["REVIEW_REQUIRED"],host_imported=False)
        for item in ast.walk(clone):
            if isinstance(item, (ast.FunctionDef, ast.ClassDef)):
                item.name = "DEFINITION"
            elif isinstance(item, ast.arg):
                item.arg = "ROLE"
            elif isinstance(item, ast.Name):
                item.id = "NAME"
            elif isinstance(item, ast.Constant):
                item.value = type(item.value).__name__
        functions.append(dict(name=node.name,
            normalized_ast_clone_sha256=hashlib.sha256(ast.dump(clone, include_attributes=False).encode()).hexdigest()))
    return dict(status="STATIC_ONLY", reason="SEMANTICS_AND_SAFETY_NOT_AUTHORIZED", functions=functions,
                flags=sorted(flags), host_imported=False)


def build_consumed_registry(root=None):
    """Union known public consumed registries without reading private final data."""
    explicit_root = root is not None
    root = Path(root) if explicit_root else Path(__file__).resolve().parents[2]
    tokens, urls, lineages, revisions, files = set(), set(), set(), set(), []
    paths = ("docs/E8_CONSUMED_IDENTITIES.json", "docs/E8_R4_CORR_USAGE.json",
             "docs/HISTORICAL_PROFILE.json", "docs/ONLINE_PROFILE.json")
    if not all((root / relative).is_file() for relative in paths) or not (root / "benchmarks/historical/manifest.json").is_file():
        fallback = Path(sysconfig.get_path("data")) / "share/antemortem-structural-lab/HARVESTER_CONSUMED_FINGERPRINTS_20261101.json"
        if not explicit_root and fallback.is_file():
            value = validate_consumed_registry(json.loads(fallback.read_bytes()))
            if value["registry_digest"] != CONSUMED_SNAPSHOT_DIGEST:
                raise ValueError("bundled consumed fingerprint snapshot differs from the pinned reviewed identity")
            return value
        raise ValueError("required public consumed registries unavailable; qualification must HOLD")
    def walk(value):
        if type(value) is list:
            for row in value:
                walk(row)
        elif type(value) is dict:
            if set(("canonical_function_identity", "cross_revision_function_key",
                    "normalized_ast_clone_sha256", "implementation_sha256")) <= value.keys():
                identity = {k:value[k] for k in ("canonical_function_identity", "cross_revision_function_key",
                    "normalized_ast_clone_sha256", "implementation_sha256")}
                tokens.update(identity_tokens(identity))
            for name in ("issue", "source_url"):
                if type(value.get(name)) is str and value[name].startswith("https://github.com/"):
                    urls.add(_provenance_url(value[name]))
            for name in ("lineage", "implementation_lineage"):
                if type(value.get(name)) is str:
                    lineages.add(value[name])
            for name in ("buggy_revision", "fixed_revision", "implementation_revision"):
                if type(value.get(name)) is str and re.fullmatch("[a-f0-9]{40}", value[name]):
                    revisions.add(value[name])
            for child in value.values():
                walk(child)
    for relative in paths:
        path = root / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("consumed registry exceeds reviewed bound")
        walk(json.loads(raw))
        files.append(dict(path=relative, sha256=hashlib.sha256(raw).hexdigest()))
    historical = root / "benchmarks/historical/manifest.json"
    if historical.is_file():
        raw = historical.read_bytes()
        manifest = json.loads(raw)
        files.append(dict(path="benchmarks/historical/manifest.json", sha256=hashlib.sha256(raw).hexdigest()))
        for case in manifest.get("cases", []):
            original = dict(project=case["project"], path=case["original_path"], function=case["function"])
            tokens.add("cross_revision_function_key:"+digest(original))
            lineages.add(case["implementation_lineage"])
            if case.get("issue"):
                urls.add(_provenance_url(case["issue"]))
            for version in ("buggy", "fixed"):
                record = case[version]
                revisions.add(record["revision"])
                tokens.add("canonical_function_identity:"+digest(dict(original, revision=record["revision"])))
                tokens.add("implementation_sha256:"+record["capsule_sha256"])
                capsule = (historical.parent / record["capsule"]).resolve()
                if not capsule.is_relative_to(historical.parent.resolve()):
                    raise ValueError("consumed capsule path escaped registry")
                source = capsule.read_bytes()
                if hashlib.sha256(source).hexdigest() != record["capsule_sha256"]:
                    raise ValueError("consumed original capsule hash mismatch")
                for function in static_source_review(source.decode("utf-8"))["functions"]:
                    if function["name"] == case["function"]:
                        tokens.add("normalized_ast_clone_sha256:"+function["normalized_ast_clone_sha256"])
    value = _signed(dict(schema=CONSUMED_SCHEMA, tokens=sorted(tokens), source_urls=sorted(urls),
        lineages=sorted(lineages), revisions=sorted(revisions), sources=files,
        coverage="KNOWN_PUBLIC_REGISTRIES_ONLY_NOT_A_GLOBAL_E1_E9_CENSUS",
        private_final_inputs_read=False), "registry_digest")
    snapshot = root / "docs/HARVESTER_CONSUMED_FINGERPRINTS_20261101.json"
    if snapshot.is_file():
        frozen = validate_consumed_registry(json.loads(snapshot.read_bytes()))
        if frozen != value or frozen["registry_digest"] != CONSUMED_SNAPSHOT_DIGEST:
            raise ValueError("public consumed snapshot differs from the source-derived reviewed registries")
    return value


def _provenance_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ValueError("official GitHub provenance URL required")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("repository provenance URL required")
    parts[:2] = [part.lower() for part in parts[:2]]
    if len(parts) > 2 and parts[2].lower() in ("pull", "issues", "commit"):
        parts[2] = parts[2].lower()
    return "https://github.com/"+"/".join(parts)


def source_function_identity(candidate, *, path, function):
    """Fingerprint the selected original function without importing its module."""
    candidate = _candidate(candidate)
    blobs = [row for row in candidate["source_blobs"] if row["revision"] == candidate["buggy_revision"] and row["path"] == path]
    if len(blobs) != 1:
        raise ValueError("one exact buggy source blob is required")
    blob = blobs[0]
    functions = [row for row in static_source_review(blob["text"])["functions"] if row["name"] == function]
    if len(functions) != 1:
        raise ValueError("one statically selected upstream function is required")
    original = dict(project=candidate["repository"], path=path, function=function)
    return dict(canonical_function_identity=digest(dict(original, revision=candidate["buggy_revision"])),
        cross_revision_function_key=digest(original), normalized_ast_clone_sha256=functions[0]["normalized_ast_clone_sha256"],
        implementation_sha256=blob["sha256"])


def validate_consumed_registry(registry):
    keys(registry, ("schema", "tokens", "source_urls", "lineages", "revisions", "sources",
                    "coverage", "private_final_inputs_read", "registry_digest"))
    if registry["schema"] != CONSUMED_SCHEMA or registry["private_final_inputs_read"] is not False:
        raise ValueError("unsupported consumed provenance registry")
    for name in ("tokens", "source_urls", "lineages", "revisions"):
        values = registry[name]
        if type(values) is not list or len(values) > 20000 or any(type(v) is not str or len(v) > 2048 for v in values):
            raise ValueError("bounded consumed identities required")
        if values != sorted(set(values)):
            raise ValueError("consumed identities must be unique canonical lists")
    if not registry["tokens"] or not registry["sources"]:
        raise ValueError("empty consumed registry cannot authorize new development data")
    _verify_digest(registry, "registry_digest")
    return deepcopy(registry)


def make_review(candidate, *, contract, implementation_sha256, fixed_implementation_sha256,
                oracle_sha256, reset_adapter_sha256, function_identity, lineage, review_ids,
                oracle_independence_basis, reset_strategy="PURE_CALLABLE", split="development", review_id=None, exports=None):
    candidate = _candidate(candidate)
    selected = []
    for blob in candidate["source_blobs"]:
        if blob["revision"] == candidate["buggy_revision"]:
            for function in static_source_review(blob["text"])["functions"]:
                if source_function_identity(candidate,path=blob["path"],function=function["name"]) == function_identity:
                    selected.append((blob["path"],function["name"]))
    if len(selected) != 1:
        raise ValueError("one actual upstream function fingerprint must be selected")
    source_path, function = selected[0]
    exports = deepcopy(exports) if exports is not None else dict(buggy=function,fixed=function,oracle="reference",reset="reset")
    value = dict(schema=REVIEW_SCHEMA, candidate_id=candidate["candidate_id"], metadata_digest=candidate["metadata_digest"],
        split=split, review_id=review_id or review_ids["contract_review_id"], contract=deepcopy(contract),
        implementation_sha256=implementation_sha256, fixed_implementation_sha256=fixed_implementation_sha256,
        oracle_sha256=oracle_sha256, reset_adapter_sha256=reset_adapter_sha256,
        function_identity=deepcopy(function_identity), source_path=source_path, exports=exports,
        lineage=deepcopy(lineage), review_ids=deepcopy(review_ids),
        oracle_independence_basis=oracle_independence_basis, reset_strategy=reset_strategy)
    return validate_review_bundle(candidate, _signed(value, "review_digest"))


def validate_review_bundle(candidate, review):
    candidate = _candidate(candidate)
    keys(review, REVIEW_FIELDS)
    if review["schema"] != REVIEW_SCHEMA or review["candidate_id"] != candidate["candidate_id"] or review["metadata_digest"] != candidate["metadata_digest"]:
        raise ValueError("review does not bind the exact discovered candidate")
    if review["split"] != "development":
        raise PermissionError("final or validation evidence cannot become development learning")
    identifier(review["review_id"])
    validate_contract(review["contract"])
    for name in ("implementation_sha256", "fixed_implementation_sha256", "oracle_sha256", "reset_adapter_sha256"):
        _sha(review[name])
    if review["implementation_sha256"] == review["fixed_implementation_sha256"]:
        raise ValueError("identical code does not establish a buggy/fixed contrast")
    if review["oracle_sha256"] in (review["implementation_sha256"], review["fixed_implementation_sha256"]):
        raise ValueError("Oracle cannot simply be the buggy or fixed implementation bytes")
    identity_tokens(review["function_identity"])
    if review["function_identity"]["implementation_sha256"] != review["implementation_sha256"]:
        raise ValueError("reviewed implementation fingerprint differs")
    keys(review["exports"],("buggy","fixed","oracle","reset"))
    for export in review["exports"].values():
        if type(export) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}",export) is None:
            raise ValueError("one explicitly reviewed export name required")
    if type(review["source_path"]) is not str or len(review["source_path"]) > 1024:
        raise ValueError("explicit reviewed upstream source path required")
    derived = source_function_identity(candidate,path=review["source_path"],function=review["exports"]["buggy"])
    if review["function_identity"] != derived:
        raise ValueError("function fingerprints must derive from the selected actual upstream source")
    keys(review["lineage"], LINEAGE_FIELDS)
    for value in review["lineage"].values():
        identifier(value)
    if review["lineage"]["project_id"] != candidate["repository"].replace("/", "."):
        raise ValueError("review project identity cannot rename the actual upstream repository")
    keys(review["review_ids"], REVIEW_IDS)
    for value in review["review_ids"].values():
        identifier(value)
    if review["reset_strategy"] not in ("PURE_CALLABLE", "REVIEWED_FULL_RESET_ADAPTER"):
        raise ValueError("fresh reset semantics require explicit review")
    basis = review["oracle_independence_basis"]
    if type(basis) is not str or not 20 <= len(basis) <= 8192:
        raise ValueError("a reviewed semantic independence basis is required, not merely different hashes")
    # A review must reference bytes already bound to exact GitHub revisions.
    by_revision = {}
    for blob in candidate["source_blobs"]:
        by_revision.setdefault(blob["revision"], set()).add(blob["sha256"])
    if review["implementation_sha256"] not in by_revision.get(candidate["buggy_revision"], set()) or review["fixed_implementation_sha256"] not in by_revision.get(candidate["fixed_revision"], set()):
        raise ValueError("reviewed implementation bytes lack exact upstream source provenance")
    if not candidate["license"].get("spdx_id") or not candidate["license"].get("sha256"):
        raise ValueError("reviewed license provenance is required")
    _verify_digest(review, "review_digest")
    return deepcopy(review)


def _provenance(candidate):
    p = candidate["provenance"]
    return (p.get("public_repository") is True and p.get("merged") is True
        and p.get("detail_reserved") is True and candidate["fixed_revision"] is not None
        and candidate["fixed_revision"] == p.get("merge_commit_sha")
        and candidate["buggy_revision"] is not None
        and p.get("proposed_buggy_first_parent") is True
        and candidate["buggy_revision"] == p.get("proposed_buggy_parent_sha"))


def assess_candidate(candidate, *, consumed_registry=None, review=None, execution_receipt=None, trusted_review=False):
    candidate = _candidate(candidate)
    registry = validate_consumed_registry(consumed_registry or build_consumed_registry())
    completed, reasons, status = ["DISCOVERED"], [], "DISCOVERED"
    source_urls = {_provenance_url(candidate["source_url"]), *(_provenance_url(u) for u in candidate["issues"])}
    if source_urls & set(registry["source_urls"]):
        status, reasons = "REJECTED", ["CONSUMED_PROVENANCE_ALREADY_USED"]
    elif not _provenance(candidate):
        status, reasons = "UNKNOWN", ["PROVENANCE_INCOMPLETE_OR_UNVERIFIED"]
    else:
        completed.append("PROVENANCE_VERIFIED")
        status, reasons = "HOLD_REVIEW", ["CONTRACT_ORACLE_RESET_LICENSE_REVIEW_REQUIRED"]
        if review is not None:
            review = validate_review_bundle(candidate, review)
            if identity_tokens(review["function_identity"]) & set(registry["tokens"]):
                status, reasons = "REJECTED", ["CONSUMED_IMPLEMENTATION_OR_FUNCTION_IDENTITY"]
            elif trusted_review is not True:
                status, reasons = "HOLD_REVIEW", ["EXPLICIT_ACCOUNTABLE_HOST_REVIEW_REQUIRED"]
            else:
                completed.extend(["CONTRACT_REVIEWED", "ORACLE_REVIEWED"])
                status, reasons = "HOLD_EXECUTION", ["BUGGY_FAILURE_FIXED_PASS_FRESH_REPRODUCTION_REQUIRED"]
                if execution_receipt is not None:
                    from .harvester_execution import validate_reproduction_receipt
                    validate_reproduction_receipt(candidate, review, execution_receipt)
                    if execution_receipt["status"] == "REPRODUCED":
                        completed.extend(["REPRODUCED", "DEVELOPMENT_ELIGIBLE"])
                        status, reasons = "DEVELOPMENT_ELIGIBLE", []
                    else:
                        status, reasons = "HOLD_EXECUTION", list(execution_receipt["reasons"])
        elif candidate["source_blobs"]:
            found = set()
            for blob in candidate["source_blobs"]:
                source = static_source_review(blob["text"])
                for function in source["functions"]:
                    original = dict(project=candidate["repository"], path=blob["path"], function=function["name"])
                    found.add("cross_revision_function_key:"+digest(original))
                    found.add("normalized_ast_clone_sha256:"+function["normalized_ast_clone_sha256"])
            if found & set(registry["tokens"]):
                reasons.append("POSSIBLE_CONSUMED_FUNCTION_OVERLAP_REQUIRES_SELECTED_FUNCTION_REVIEW")
    value = dict(schema=ASSESSMENT_SCHEMA, candidate_id=candidate["candidate_id"],
        metadata_digest=candidate["metadata_digest"], status=status, split="development",
        completed_stages=completed, reasons=reasons,
        evidence_grade="REVIEWED_REPRODUCED_DEVELOPMENT" if status == "DEVELOPMENT_ELIGIBLE" else "NOT_DEVELOPMENT_ELIGIBLE",
        consumed_registry_digest=registry["registry_digest"],
        review_digest=review["review_digest"] if review is not None else None,
        reproduction_digest=execution_receipt.get("sha256") if execution_receipt is not None else None,
        oracle_independence="HOST_REVIEW_REQUIRED_NOT_PROVED_BY_HASH", host_external_code_imported=False)
    return _signed(value, "sha256")


def development_lineage(candidate, assessment, review):
    candidate = _candidate(candidate)
    review = validate_review_bundle(candidate, review)
    if assessment.get("schema") != ASSESSMENT_SCHEMA or assessment.get("status") != "DEVELOPMENT_ELIGIBLE" or assessment.get("candidate_id") != candidate["candidate_id"] or assessment.get("metadata_digest") != candidate["metadata_digest"] or assessment.get("review_digest") != review["review_digest"]:
        raise PermissionError("only reviewed reproduced development candidates enter M0")
    _verify_digest(assessment, "sha256")
    return dict(review["lineage"], implementation_sha256=review["implementation_sha256"],
        oracle_sha256=review["oracle_sha256"], input_contract_sha256=digest(review["contract"]),
        review_id=review["review_id"])
