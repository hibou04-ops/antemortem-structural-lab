"""Small, immutable prepared guides with an out-of-band trusted host context.

The approval state is an authority input, not a signature. The trusted host must
keep it current when source evidence, counterevidence or compiler policy changes.
Rehashing the bundle itself cannot replace that external approval input.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from .schema import canonical, digest

SCHEMA = "tomolab-prepared-numerical-guide-v1"
CONTEXT_SCHEMA = "tomolab-numerical-host-context-v1"
MAX_PREPARED_BYTES = 1_048_576
_FILES = ("guide.json", "approval.json", "manifest.json")


def _code_identity(names):
    folder = Path(__file__).parent
    return digest({name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
                   for name in names})


def approval_context(compiled):
    """Describe approved identities; callers must separately authorize this value."""
    from .compact_guidance import validate_execution_artifact
    from .knowledge import VALIDATION_CACHE_VERSION
    artifact, receipt = compiled["artifact"], compiled["approval_receipt"]
    validate_execution_artifact(artifact, artifact["artifact_digest"], receipt)
    return dict(schema=CONTEXT_SCHEMA,
        source_archive_content_digest=receipt["source_archive_content_digest"],
        source_validation_version=VALIDATION_CACHE_VERSION + ":" + _code_identity(
            ("knowledge.py", "claim_semantics.py", "features.py", "predicates.py")),
        semantic_contract_version=artifact["semantic_contract_version"],
        recipe_identity_and_parameters_digest=digest({
            "ids":artifact["approved_recipe_ids"],
            "parameters":artifact["bounded_recipe_parameters"]}),
        public_input_contract=deepcopy(artifact["public_input_contract"]),
        counterevidence_state_reference=artifact["counterevidence_state_reference"],
        compiler_identity=_code_identity(("compact_guidance.py", "numerical_guidance.py", "schema.py")),
        artifact_schema=artifact["schema_version"],
        approved_artifact_digest=artifact["artifact_digest"],
        source_approval_receipt_digest=receipt["receipt_digest"])


def _write_new(path, value):
    payload = (canonical(value)+"\n").encode("utf-8")
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return len(payload)


def _read_small(path):
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_PREPARED_BYTES+1)
    if len(raw) > MAX_PREPARED_BYTES:
        raise ValueError("prepared file exceeds one MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate prepared JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def read_approval_state(path):
    """Read a separately trusted, bounded host approval state."""
    return _read_small(path)


def save_prepared_guide(compiled, destination, *, expected_current_context):
    """Publish an exclusive new directory atomically, never replace a guide."""
    started = time.perf_counter()
    current = approval_context(compiled)
    if not isinstance(expected_current_context, dict) or canonical(current) != canonical(expected_current_context):
        raise ValueError("guide differs from the externally approved current host context")
    directory = Path(destination)
    directory.parent.mkdir(parents=True, exist_ok=True)
    if directory.exists():
        raise FileExistsError(directory)
    manifest = dict(schema=SCHEMA, approval_context=current,
        artifact_digest=compiled["artifact"]["artifact_digest"],
        authority="EXTERNAL_TRUSTED_HOST_CONTEXT_REQUIRED")
    manifest["manifest_digest"] = digest(manifest)
    values = (compiled["artifact"], compiled["approval_receipt"], manifest)
    size = sum(len((canonical(value)+"\n").encode("utf-8")) for value in values)
    if size > MAX_PREPARED_BYTES:
        raise ValueError("entire prepared bundle exceeds one MiB")
    temporary = Path(tempfile.mkdtemp(prefix=".prepared-", dir=directory.parent))
    try:
        for name, value in zip(_FILES, values):
            _write_new(temporary/name, value)
        # rename (not replace) fails on an existing destination on Windows;
        # nonempty directories cannot be overwritten on POSIX either.
        temporary.rename(directory)
    finally:
        if temporary.exists():
            for name in _FILES:
                (temporary/name).unlink(missing_ok=True)
            temporary.rmdir()
    return dict(directory=str(directory), prepared_bytes=size,
                write_flush_seconds=time.perf_counter()-started)


def load_prepared_guide(directory, *, expected_digest, expected_current_context):
    """Reuse only small files; no archive replay, calibration or compilation."""
    started = time.perf_counter()
    directory = Path(directory)
    if not isinstance(expected_current_context, dict):
        raise ValueError("external current host context is required")
    if any((directory/name).is_symlink() for name in _FILES):
        raise ValueError("prepared guide files must not be symlinks")
    if sum((directory/name).stat().st_size for name in _FILES) > MAX_PREPARED_BYTES:
        raise ValueError("entire prepared bundle exceeds one MiB")
    artifact, receipt, manifest = [_read_small(directory/name) for name in _FILES]
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "approval_context", "artifact_digest", "authority", "manifest_digest"}:
        raise ValueError("invalid prepared manifest fields")
    unsigned = {key:value for key,value in manifest.items() if key != "manifest_digest"}
    if (manifest["schema"] != SCHEMA or digest(unsigned) != manifest["manifest_digest"]
            or manifest["authority"] != "EXTERNAL_TRUSTED_HOST_CONTEXT_REQUIRED"
            or manifest["artifact_digest"] != expected_digest):
        raise ValueError("prepared manifest identity mismatch")
    compiled = dict(artifact=artifact, approval_receipt=receipt)
    context = approval_context(compiled)
    if (canonical(context) != canonical(expected_current_context) or canonical(manifest["approval_context"]) != canonical(context)
            or context["approved_artifact_digest"] != expected_digest):
        raise ValueError("stale or unauthorized prepared guide context")
    return dict(compiled=compiled, approval_context=context,
        metrics=dict(prepared_load_validation_seconds=time.perf_counter()-started,
            full_archive_validation_invocations=0, calibration_invocations=0,
            compilation_invocations=0, artifact_validation_status="VALIDATED_CURRENT_HOST_APPROVAL",
            oracle_cache_used=False, candidate_cache_used=False))


def prepare_approved_guide(archive_path, destination, approval_state_path, *, contract=None):
    """Perform original trusted-host validation/calibration/compile once per setup.

    Both existing prepare and compiler validators remain in place. This is two
    validation invocations in preparation, not a claim that R2 replayed an
    archive in every numerical run.
    """
    started = time.perf_counter()
    from .compact_guidance import prepare_recipe_from_archive, compile_execution_artifact
    archive_path, state = Path(archive_path), Path(approval_state_path)
    if Path(destination).exists() or state.exists():
        raise FileExistsError("prepared destination and external approval state must both be new")
    if state.resolve().is_relative_to(Path(destination).resolve()):
        raise ValueError("approval state must be outside the prepared directory")
    with archive_path.open("rb") as stream:
        raw = stream.read(128*1024*1024+1)
    if len(raw) > 128*1024*1024:
        raise ValueError("source archive exceeds existing 128 MiB limit")
    snapshot = json.loads(raw)
    prepared = prepare_recipe_from_archive(snapshot, contract=contract)
    recipe = prepared["recipe"]
    compiled = compile_execution_artifact(snapshot, [recipe], recipe["public_contract"])
    context = approval_context(compiled)
    saved = save_prepared_guide(compiled, destination, expected_current_context=context)
    state.parent.mkdir(parents=True, exist_ok=True)
    _write_new(state, context)
    return dict(schema=SCHEMA, artifact_digest=compiled["artifact"]["artifact_digest"],
        approval_context=context, source_archive_file_sha256=hashlib.sha256(raw).hexdigest(),
        metrics=dict(preparation_seconds=time.perf_counter()-started,
            full_archive_validation_invocations=2, calibration_invocations=2,
            compilation_invocations=1, prepared_bytes=saved["prepared_bytes"],
            historical_first_acquisition_cost="UNKNOWN",
            archive_sent_to_worker=False), allow_release=False)
