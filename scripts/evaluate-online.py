"""One registered Source preparation/comparison path, using the common runner.

Raw records stay in caller-selected local files.  This script does not publish,
change readiness, grant FINAL access, or load arbitrary target code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomolab.discovery.schema import canonical, digest
from benchmarks.online import (cases, prepare_sources,
    run_comparison, validate_config, validate_prepared_inputs)
from tomolab.discovery.evaluation_usage import UsageLedger


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(",",":"))+"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment_identity():
    import hypothesis
    return dict(python=platform.python_version(),implementation=platform.python_implementation(),
                hypothesis=hypothesis.__version__)


def validate_registration(registration, config, prepared=None, *, check_environment=True):
    """Integrity check against the explicit host registration, not permission by hash."""
    required = {"schema", "frozen_config", "source_preparation_digest", "initial_molds",
                "code_files", "targets", "profile", "environment", "registration_digest"}
    if not isinstance(registration, dict) or set(registration) != required:
        raise ValueError("bounded host registration schema required")
    if registration["schema"] != "tomolab-online-registration-v1":
        raise ValueError("unsupported host registration")
    payload = {key:value for key,value in registration.items() if key != "registration_digest"}
    if digest(payload) != registration["registration_digest"]:
        raise ValueError("registered manifest digest mismatch")
    if registration["frozen_config"] != config:
        raise ValueError("configuration changed after registration")
    initial = registration["initial_molds"]
    if prepared is not None:
        validate_prepared_inputs(prepared)
        if registration["source_preparation_digest"] != digest(prepared):
            raise ValueError("prepared Source knowledge changed after registration")
        if initial != {fold:mold["artifact_digest"] for fold,mold in prepared["molds"].items()}:
            raise ValueError("initial frozen providers changed")
    files = registration["code_files"]
    if not isinstance(files, dict) or not files or len(files) > 256:
        raise ValueError("bounded algorithm file manifest required")
    mandatory = {path.relative_to(ROOT).as_posix() for path in (ROOT/"tomolab").rglob("*.py")}
    mandatory.add("scripts/evaluate-online.py")
    mandatory.update(path.relative_to(ROOT).as_posix() for path in (ROOT/"benchmarks").rglob("*.py"))
    if mandatory-set(files):
        raise ValueError("all runtime modules and the shared evaluation driver must be frozen")
    for relative, expected in files.items():
        if not isinstance(relative, str) or "\\" in relative:
            raise ValueError("portable relative algorithm path required")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("algorithm path escapes registered root")
        actual = ROOT.joinpath(*path.parts).resolve(strict=True)
        if not actual.is_relative_to(ROOT) or hashlib.sha256(actual.read_bytes()).hexdigest() != expected:
            raise ValueError("algorithm changed after pre-evaluation freeze")
    targets = [case.metadata() for case in cases() if case.role != "SOURCE"]
    environment = registration["environment"]
    if (not isinstance(environment, dict) or set(environment) != {"python", "implementation", "hypothesis"}
        or any(not isinstance(value,str) or not 1 <= len(value) <= 64 for value in environment.values())):
        raise ValueError("bounded registered environment identity required")
    same_environment = environment == environment_identity()
    registered_targets = registration["targets"]
    if not isinstance(registered_targets,list) or len(registered_targets) != len(targets):
        raise ValueError("registered problem set changed")
    for registered, actual in zip(registered_targets,targets):
        if not isinstance(registered,dict) or set(registered) != set(actual):
            raise ValueError("registered problem metadata fields changed")
        identity = registered.get("identity")
        if not isinstance(identity,dict) or set(identity) != set(actual["identity"]):
            raise ValueError("registered implementation identity fields changed")
        if any(not isinstance(value,str) or not re.fullmatch(r"[a-f0-9]{64}",value)
               for value in (*identity.values(),registered.get("oracle_sha256"))):
            raise ValueError("reviewed SHA256 implementation and Oracle identities required")
        left, right = json.loads(canonical(registered)), json.loads(canonical(actual))
        if not same_environment and not check_environment:
            # Cross-version AST fields differ. Raw source, contracts and all
            # other identity fields remain strict; this does not repeat a run.
            left["identity"].pop("normalized_ast_clone_sha256")
            right["identity"].pop("normalized_ast_clone_sha256")
        if left != right:
            raise ValueError("registered problem set or implementation/contract identity changed")
    profile = registration["profile"]
    if check_environment and not same_environment:
        raise ValueError("registered Python implementation/version or Hypothesis changed")
    if (profile.get("algorithm_digest") != digest(files)
        or profile.get("initial_knowledge_digest") != digest(initial)
        or profile.get("configuration_digest") != digest(config)):
        raise ValueError("execution profile does not bind frozen algorithm/knowledge/configuration")
    return profile, targets


def main(argv=None):
    parser = argparse.ArgumentParser(description="동결 알고리즘의 로컬 온라인 비교; FINAL·발행 승인 아님")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--prepared", type=Path,
                        help="Source 원시 관측을 포함하는 로컬 비공개 준비 파일")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--prepare-sources", action="store_true")
    parser.add_argument("--check-registration", action="store_true",
                        help="대상·Oracle 호출 없이 코드 동결만 확인; 등록 환경과 실행 환경을 구분")
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--usage-ledger", type=Path)
    parser.add_argument("--allow-local-execution", action="store_true")
    args = parser.parse_args(argv)
    if args.check_registration:
        if not args.registration or any((args.prepared, args.events, args.prepare_sources, args.usage_ledger)):
            parser.error("정적 동결 확인에는 --registration과 선택 --config/--output만 사용합니다")
        registration = read(args.registration)
        config = validate_config(read(args.config) if args.config else registration["frozen_config"])
        validate_registration(registration, config, check_environment=False)
        actual = environment_identity()
        receipt = dict(schema="tomolab-online-static-registration-check-v1",status="PASS",
            registration_digest=registration["registration_digest"],
            frozen_files=len(registration["code_files"]),target_calls=0,oracle_calls=0,
            source_preparation_verified=False,initial_mold_contents_verified=False,
            registered_environment=registration["environment"],actual_environment=actual,
            environment_matches_registered=registration["environment"] == actual,
            ast_identity_verified=registration["environment"] == actual,
            scope="CODE_AND_PUBLIC_IDENTITY_ONLY_NOT_REPEATED_EVALUATION",allow_release=False)
        if args.output:
            write_new(args.output,receipt)
        print(canonical(receipt))
        return 0
    if not args.config or not args.prepared or not args.output:
        parser.error("Source 준비와 평가는 --config, --prepared, --output이 필요합니다")
    if not args.allow_local_execution:
        parser.error("검토된 로컬 함수 실행에 --allow-local-execution이 필요합니다")
    for path in (args.output, args.events):
        if path is not None and path.exists():
            raise FileExistsError("existing execution receipts must be preserved")
    config = validate_config(read(args.config))
    started = time.perf_counter()
    if args.prepare_sources:
        if args.prepared.exists() or args.registration or args.usage_ledger or args.events:
            parser.error("Source 준비는 새 --prepared 파일만 생성하며 평가 등록·원장·events를 사용하지 않습니다")
        prepared = prepare_sources(config)
        prepared_sha = write_new(args.prepared, prepared)
        receipt = dict(schema="tomolab-online-source-preparation-receipt-v1", status="COMPLETE",
            prepared_file_sha256=prepared_sha, prepared_digest=digest(prepared),
            initial_molds={fold:mold["artifact_digest"] for fold,mold in prepared["molds"].items()},
            source_target_calls=prepared["target_calls"],source_oracle_calls=prepared["oracle_calls"],
            source_cost=prepared["cost"],target_evaluation_calls=0,
            source_and_durable_prepared_wall_seconds=time.perf_counter()-started,allow_release=False)
    else:
        if not args.registration or not args.usage_ledger or not args.events:
            parser.error("평가에는 외부 host --registration, 고정 --usage-ledger, 새 --events가 필요합니다")
        prepared = read(args.prepared)
        registration = read(args.registration)
        profile, targets = validate_registration(registration, config, prepared)
        ledger = UsageLedger(args.usage_ledger, authority_id=profile["authority_id"])
        entries = [dict(identity=row["identity"], evaluation_role="EXPERIMENTAL_PROBE") for row in targets]
        start = ledger.claim_experimental(entries,profile,expected_profile=registration["profile"],output=args.output)
        result = run_comparison(config,prepared,event_path=args.events)
        result["registration_digest"] = registration["registration_digest"]
        result["usage_claim_id"] = start["claim_id"]
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        result["runner_wall_before_durable_result_seconds"] = time.perf_counter()-started
        receipt = result
    output_sha = write_new(args.output, receipt)
    if not args.prepare_sources:
        ledger.complete(start["claim_id"],dict(scope="EXPERIMENTAL_PROBE",status="COMPLETE",
            output_sha256=output_sha,run_count=len(receipt["runs"]),
            registration_digest=registration["registration_digest"],allow_release=False))
    print(canonical(dict(status="COMPLETE",phase="SOURCE_PREPARATION" if args.prepare_sources else "REGISTERED_COMPARISON",
        output_sha256=output_sha,run_count=0 if args.prepare_sources else len(receipt["runs"]),allow_release=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
