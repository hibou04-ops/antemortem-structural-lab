"""Host-validated, bounded execution guides; the full archive stays on the host.

The expected artifact digest is an independently retained host approval. Neither
an artifact's self hash nor a newly manufactured receipt authenticates a host.
This data boundary does not protect against a malicious evaluator host.
"""
from copy import deepcopy
import json
import re
import time

from .schema import canonical, digest, integer, keys

SCHEMA_VERSION = "tomolab-compact-numerical-guide-v1"
SEMANTIC_CONTRACT_VERSION = "e8-r1-claims-v1"
COMPILER_VERSION = "e8-r2-compact-compiler-v1"
RECEIPT_SCHEMA = "tomolab-compact-host-approval-v1"
PROTOCOL = "tomolab-compact-numerical-protocol-v1"
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_MESSAGE = 8_000_000


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("an approved SHA-256 is required")
    return value


def _captured(value, bound, label):
    try:
        encoded = canonical(value).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(label + " requires finite JSON data") from error
    if len(encoded) > bound:
        raise ValueError(label + " exceeds size bound")
    return json.loads(encoded)


def _contract(value):
    from .numerical_guidance import public_input_contract
    keys(value, ("schema", "profile", "lengths", "minimum", "maximum", "nonconstant_centered_ss_min"))
    expected = public_input_contract(profile=value.get("profile"))
    if (not isinstance(value["lengths"], list) or not value["lengths"]
            or len(set(value["lengths"])) != len(value["lengths"])
            or any(type(n) is not int or n not in expected["lengths"] for n in value["lengths"])):
        raise ValueError("lengths are outside the approved input contract")
    if any(value[k] != expected[k] for k in expected if k != "lengths"):
        raise ValueError("public input contract was broadened")
    return deepcopy(value)


def _runtime_recipe(value):
    from .numerical_guidance import FailureGuidanceRecipe
    clean = FailureGuidanceRecipe.from_dict(value).to_dict()
    # Native recipe schemas contain data-only enums and bounded public inputs;
    # these fields never belong to a runtime guide, even after a self rehash.
    forbidden = {"inputs", "actual", "expected", "oracle_output", "target_code", "oracle_code",
                 "journal", "labels", "final_source", "private_path", "code", "python"}
    def inspect(node):
        if isinstance(node, dict):
            if forbidden.intersection(node):
                raise ValueError("runtime recipe contains forbidden execution or answer data")
            for child in node.values():
                inspect(child)
        elif isinstance(node, list):
            for child in node:
                inspect(child)
        elif isinstance(node, str) and ("\\" in node or re.match(r"^[A-Za-z]:", node) or node.startswith("/")):
            raise ValueError("runtime recipe contains a private filesystem path")
    inspect(clean)
    return clean


def _counterevidence_reference(snapshot):
    # A reference commits to the complete state. Repeated evidence arrays stay
    # on the host; the worker never receives a contradictory-input corpus.
    return digest({"source_archive_digest": snapshot["receipt"]["sha256"],
        "claims": [{"id": row["claim_id"],
                    "counterevidence": row.get("counterevidence", row.get("contradicting_evidence", []))}
                   for row in snapshot["claims"]],
        "source_validation_journal": snapshot.get("source_validation_journal", [])})


def _source_observations(archive):
    """Only replay-validated same-Source development events may calibrate."""
    events = list(archive._source_evidence)
    events.extend(row["evidence"] for row in archive._events if row["origin"] == archive.source)
    for batch in archive._source_validation:
        events.extend(row["evidence"] for row in batch["observations"] if row["origin"] == archive.source)
    return [{"inputs": deepcopy(event["inputs"]), "status": event["kind"],
             "evidence_ref": event["evidence_id"]} for event in events]


def _approved_source_contract(archive):
    items = archive.spec["inputs"]
    expected_type = {"kind": "list", "min_size": 3, "max_size": 6,
                     "items": {"kind": "float", "min": -1.0, "max": 1.0}}
    if (archive.spec["contract"]["operation"] != "robust-linear-correlation"
            or [(row["name"], row["role"]) for row in items] != [("a", "left-series"), ("b", "right-series")]
            or any(row["type"] != expected_type for row in items)):
        raise ValueError("archive is outside the approved numerical Source contract")


def prepare_recipe_from_archive(archive_snapshot, *, contract=None):
    """Validate the original journal and calibrate from its actual Source rows.

    The returned aggregate recipe contains no original input rows or outputs.
    The result is still development guidance, never a failure classifier.
    """
    from .knowledge import KnowledgeArchive, SEMANTIC_SCHEMA
    from .numerical_guidance import calibrate_recipe, public_input_contract
    wall, cpu = time.perf_counter(), time.process_time()
    archive = KnowledgeArchive.from_snapshot(archive_snapshot)
    if not archive.frozen or archive_snapshot.get("schema") != SEMANTIC_SCHEMA:
        raise ValueError("recipe preparation requires an explicitly semantic frozen R1 archive")
    _approved_source_contract(archive)
    contract = public_input_contract() if contract is None else _contract(contract)
    rows = _source_observations(archive)
    receipt = archive.snapshot()["receipt"]["sha256"]
    recipe = calibrate_recipe(rows, source_evidence_refs=["archive-receipt:"+receipt],
                              archive_digest=receipt, contract=contract).to_dict()
    return {"recipe": recipe, "metrics": {"source_rows": len(rows),
        "wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
        "calibration": "ACTUAL_VALIDATED_SAME_SOURCE_DEVELOPMENT_EVENTS_ONLY",
        "independent_transfer_authorized": False}}


def compile_execution_artifact(archive_snapshot, recipes, public_input_contract, *, approved_recipe_ids=None):
    """Replay the original archive, then approve only reviewed bounded recipes.

    No knowledge status or independent-transfer eligibility is upgraded here.
    A compile receipt attests validation and linkage, not recipe usefulness.
    """
    from .knowledge import KnowledgeArchive, SEMANTIC_SCHEMA
    from .numerical_guidance import calibrate_recipe
    wall, cpu = time.perf_counter(), time.process_time()
    archive = KnowledgeArchive.from_snapshot(archive_snapshot)
    if not archive.frozen or archive_snapshot.get("schema") != SEMANTIC_SCHEMA:
        raise ValueError("compact compilation requires a frozen validated R1 archive")
    _approved_source_contract(archive)
    snapshot = archive.snapshot()
    archive_digest = snapshot["receipt"]["sha256"]
    contract = _contract(public_input_contract)
    if not isinstance(recipes, list) or not 1 <= len(recipes) <= 16:
        raise ValueError("one to sixteen approved numerical recipes required")
    normalized = [_runtime_recipe(recipe) for recipe in recipes]
    ids = [row["recipe_id"] for row in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate approved recipe identity")
    approved = ids if approved_recipe_ids is None else approved_recipe_ids
    if not isinstance(approved, list) or approved != ids:
        raise ValueError("approved recipe list and runtime recipes differ")
    evidence_ids = {event["evidence_id"] for event in archive._source_evidence}
    evidence_ids.update(event["evidence"]["evidence_id"] for event in archive._events)
    for batch in archive._source_validation:
        evidence_ids.update(event["evidence"]["evidence_id"] for event in batch["observations"])
    evidence_ids.add("archive-receipt:" + archive_digest)
    for recipe in normalized:
        if (recipe["provenance"].get("source_archive_digest") != archive_digest
                or not set(recipe["source_evidence_refs"]) <= evidence_ids):
            raise ValueError("recipe does not identify the verified source archive evidence")
        if recipe["public_contract"] != contract:
            raise ValueError("recipe and runtime input contracts differ")
        calibrated = calibrate_recipe(_source_observations(archive),
            source_evidence_refs=recipe["source_evidence_refs"], archive_digest=archive_digest,
            contract=contract).to_dict()
        if recipe != calibrated:
            raise ValueError("recipe policy differs from actual validated same-Source observations")
    semantic = (snapshot.get("semantic_policy") or {}).get("semantic_version", SEMANTIC_CONTRACT_VERSION)
    if semantic != SEMANTIC_CONTRACT_VERSION:
        raise ValueError("unsupported source archive claim semantics")
    artifact = dict(schema_version=SCHEMA_VERSION, source_archive_digest=archive_digest,
        semantic_contract_version=semantic, approved_recipe_ids=ids,
        bounded_recipe_parameters=normalized, public_input_contract=contract,
        applicability_scope="SOURCE_DEVELOPMENT_ONLY",
        counterevidence_state_reference=_counterevidence_reference(snapshot),
        compiler_version=COMPILER_VERSION)
    artifact["artifact_digest"] = digest(artifact)
    artifact = _captured(artifact, MAX_ARTIFACT_BYTES, "compact artifact")
    receipt = dict(schema=RECEIPT_SCHEMA, compiler_version=COMPILER_VERSION,
        source_archive_digest=archive_digest, source_archive_content_digest=digest(snapshot),
        source_archive_schema=snapshot["schema"],
        source_archive_validation="FULL_EXISTING_ARCHIVE_REPLAY_VALIDATION_ON_TRUSTED_HOST",
        artifact_digest=artifact["artifact_digest"],
        counterevidence_state_reference=artifact["counterevidence_state_reference"],
        approved_recipe_ids=ids, semantic_contract_version=semantic,
        public_input_contract_digest=digest(contract),
        transfer_authorized=False, final_feedback_allowed=False,
        authority="TRUSTED_HOST_APPROVAL_NOT_SELF_HASH_AUTHENTICATION")
    receipt["receipt_digest"] = digest(receipt)
    validate_execution_artifact(artifact, artifact["artifact_digest"], receipt)
    return {"artifact": artifact, "approval_receipt": receipt,
        "metrics": {"wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
                    "source_archive_bytes": len(canonical(snapshot).encode("utf-8")),
                    "artifact_bytes": len(canonical(artifact).encode("utf-8")),
                    "original_archive_sent_to_worker": False}}


def validate_execution_artifact(artifact, expected_digest, approval_receipt):
    artifact = _captured(artifact, MAX_ARTIFACT_BYTES, "compact artifact")
    receipt = _captured(approval_receipt, 32768, "host approval receipt")
    keys(artifact, ("schema_version", "source_archive_digest", "semantic_contract_version",
        "approved_recipe_ids", "bounded_recipe_parameters", "public_input_contract", "applicability_scope",
        "counterevidence_state_reference", "compiler_version", "artifact_digest"))
    if (artifact["schema_version"] != SCHEMA_VERSION or artifact["compiler_version"] != COMPILER_VERSION
            or artifact["semantic_contract_version"] != SEMANTIC_CONTRACT_VERSION
            or artifact["applicability_scope"] != "SOURCE_DEVELOPMENT_ONLY"):
        raise ValueError("unsupported compact schema, version or applicability scope")
    _sha(expected_digest)
    for field in ("source_archive_digest", "counterevidence_state_reference", "artifact_digest"):
        _sha(artifact[field])
    if (artifact["artifact_digest"] != digest({k:v for k,v in artifact.items() if k != "artifact_digest"})
            or artifact["artifact_digest"] != expected_digest):
        raise ValueError("artifact differs from the separately approved expected digest")
    contract = _contract(artifact["public_input_contract"])
    recipes = artifact["bounded_recipe_parameters"]
    if not isinstance(recipes, list) or not 1 <= len(recipes) <= 16:
        raise ValueError("bounded recipe list required")
    recipes = [_runtime_recipe(row) for row in recipes]
    ids = [row["recipe_id"] for row in recipes]
    if len(set(ids)) != len(ids) or artifact["approved_recipe_ids"] != ids:
        raise ValueError("unapproved or duplicate recipe identity")
    if any(row["public_contract"] != contract or row["provenance"].get("source_archive_digest") != artifact["source_archive_digest"] for row in recipes):
        raise ValueError("recipe contract or original archive linkage differs")
    keys(receipt, ("schema", "compiler_version", "source_archive_digest", "source_archive_content_digest",
        "source_archive_schema", "source_archive_validation", "artifact_digest", "counterevidence_state_reference",
        "approved_recipe_ids", "semantic_contract_version", "public_input_contract_digest", "transfer_authorized",
        "final_feedback_allowed", "authority", "receipt_digest"))
    if (receipt["schema"] != RECEIPT_SCHEMA or receipt["compiler_version"] != COMPILER_VERSION
            or receipt["source_archive_validation"] != "FULL_EXISTING_ARCHIVE_REPLAY_VALIDATION_ON_TRUSTED_HOST"
            or receipt["authority"] != "TRUSTED_HOST_APPROVAL_NOT_SELF_HASH_AUTHENTICATION"
            or receipt["transfer_authorized"] is not False or receipt["final_feedback_allowed"] is not False
            or receipt["public_input_contract_digest"] != digest(contract)
            or receipt["receipt_digest"] != digest({k:v for k,v in receipt.items() if k != "receipt_digest"})):
        raise ValueError("invalid original archive host approval receipt")
    for field in ("source_archive_digest", "artifact_digest", "counterevidence_state_reference", "approved_recipe_ids", "semantic_contract_version"):
        if receipt[field] != artifact[field]:
            raise ValueError("host approval and original archive artifact linkage differ")
    _sha(receipt["source_archive_content_digest"])
    return artifact


def validate_numerical_request(message, spec=None):
    message = _captured(message, MAX_MESSAGE-1, "numerical worker request")
    if not isinstance(message, dict):
        raise ValueError("request must be a finite JSON object")
    action = message.get("action")
    if action == "plan":
        keys(message, ("action", "artifact", "approval_receipt", "expected_digest", "seed", "size", "max_examples", "excluded_digests"), ("contract",))
        validate_execution_artifact(message["artifact"], message["expected_digest"], message["approval_receipt"])
        if "contract" in message:
            contract = _contract(message["contract"])
            approved = message["artifact"]["public_input_contract"]
            if (not set(contract["lengths"]) <= set(approved["lengths"])
                    or any(contract[k] != approved[k] for k in approved if k != "lengths")):
                raise ValueError("execution input contract broadens approved artifact scope")
    elif action == "baseline":
        keys(message, ("action", "method", "seed", "size", "max_examples", "excluded_digests", "contract"), ("replay_inputs",))
        if message["method"] not in ("A", "B", "C"):
            raise ValueError("only A, B or C may use the baseline generation endpoint")
        contract = _contract(message["contract"])
        if message["method"] == "C":
            from .numerical_guidance import domain_guard, public_input_contract
            replays = message.get("replay_inputs")
            if not isinstance(replays, list) or not 1 <= len(replays) <= 64:
                raise ValueError("C requires one to 64 reviewed input-only counterexamples")
            original_domain = public_input_contract(profile=contract["profile"])
            if any(not domain_guard(point, original_domain) for point in replays):
                raise ValueError("C replay inputs violate the approved original Source domain")
        elif "replay_inputs" in message:
            raise ValueError("A and B do not receive failure inputs, labels or a calibrated recipe")
    elif action in ("snapshot", "close", "freeze"):
        keys(message, ("action",))
    elif action == "diagnose":
        keys(message, ("action", "host_sentinel"))
        sentinel = message["host_sentinel"]
        if not isinstance(sentinel, str) or not 1 <= len(sentinel) <= 4096 or "\x00" in sentinel:
            raise ValueError("invalid harmless diagnostic sentinel")
    else:
        raise ValueError("unsupported numerical action; learning and parameter mutation are forbidden")
    if action in ("plan", "baseline"):
        integer(message["seed"], 0, 2**32-1)
        integer(message["size"], 1, 1024)
        integer(message["max_examples"], message["size"], 8192)
        excluded = message["excluded_digests"]
        if not isinstance(excluded, list) or len(excluded) > 8192 or len(set(excluded)) != len(excluded):
            raise ValueError("bounded unique excluded input digest list required")
        for sha in excluded:
            _sha(sha)
    return message


def in_process_candidate_plan(*, artifact, approval_receipt, expected_digest, seed, size, max_examples, excluded_digests, contract=None):
    """Native execution inside the reviewed worker, never the evaluator host.

    Hypothesis 6.170 scans loaded local modules for constants. Worker module
    whitelisting therefore protects generation as well as filesystem access.
    """
    from .numerical_guidance import generate_numerical_candidates
    fields = dict(action="plan", artifact=artifact, approval_receipt=approval_receipt,
        expected_digest=expected_digest, seed=seed, size=size, max_examples=max_examples, excluded_digests=excluded_digests)
    if contract is not None:
        fields["contract"] = contract
    request = validate_numerical_request(fields)
    # One immutable policy per execution plan; combining policies requires a new
    # separately approved artifact instead of implicit post-freeze retuning.
    if len(request["artifact"]["bounded_recipe_parameters"]) != 1:
        raise ValueError("this execution profile supports exactly one approved recipe")
    result = generate_numerical_candidates(method="D", recipe=request["artifact"]["bounded_recipe_parameters"][0],
        seed=request["seed"], size=request["size"], max_examples=request["max_examples"], excluded_digests=request["excluded_digests"],
        contract=request.get("contract", request["artifact"]["public_input_contract"]))
    return {"schema": "tomolab-compact-candidate-plan-v1", "artifact_digest": expected_digest,
        "source_archive_digest": request["artifact"]["source_archive_digest"],
        "candidate_digest": digest(result["candidates"]), "generation": result,
        "execution_contract_digest": digest(request.get("contract", request["artifact"]["public_input_contract"])),
        "frozen": True, "learning_allowed": False, "final_feedback_allowed": False}


def host_candidate_plan(*, artifact, approval_receipt, expected_digest, seed, size, max_examples, excluded_digests, contract=None):
    """Host reference in a fresh process with the same public code whitelist.

    No evaluator/Oracle modules or their automatically mined constants enter
    this reference. Native Hypothesis internals and strategies are unchanged.
    """
    from .numerical_boundary import NumericalBoundary
    fields = dict(artifact=artifact, approval_receipt=approval_receipt, expected_digest=expected_digest,
                  seed=seed, size=size, max_examples=max_examples, excluded_digests=list(excluded_digests))
    if contract is not None:
        fields["contract"] = contract
    request = validate_numerical_request(dict(action="plan", **fields))
    request.pop("action")
    with NumericalBoundary(backend="subprocess") as reference:
        result = reference.request("plan", **request)
        result["reference_boundary"] = reference.receipt
    result["reference_execution"] = "CLEAN_HOST_SUBPROCESS_REFERENCE"
    return result


def generate_baseline_candidates(method, *, seed=7, size=32, max_examples=1024,
        excluded_digests=(), replay_inputs=None, contract=None):
    """A/B/C receive only their declared inputs in an identical clean context.

    A and B cannot receive a recipe, archive, failure corpus or Oracle output.
    C receives the same reviewed failing input material as host calibration,
    without outputs or labels. Its direct replay accounting stays on the host.
    """
    from .numerical_boundary import NumericalBoundary
    from .numerical_guidance import public_input_contract
    fields = dict(method=method, seed=seed, size=size, max_examples=max_examples,
        excluded_digests=list(excluded_digests),
        contract=public_input_contract() if contract is None else contract)
    if replay_inputs is not None:
        fields["replay_inputs"] = replay_inputs
    request = validate_numerical_request(dict(action="baseline", **fields))
    request.pop("action")
    with NumericalBoundary(backend="subprocess") as reference:
        result = reference.request("baseline", **request)
        result["generation_boundary"] = reference.receipt
    result["generation_execution"] = "CLEAN_HOST_SUBPROCESS_BASELINE"
    return result
