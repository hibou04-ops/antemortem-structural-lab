"""E8 host evidence commands; no final target execution is dispatched here."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def register(commands):
    importer = commands.add_parser("evidence-import", help="검토한 DEVELOPMENT 공통 기록을 도구 중립 archive로 연결")
    importer.add_argument("--records", type=Path, required=True)
    importer.add_argument("--generation-id", required=True)
    importer.add_argument("--parent-generation", action="append", default=[])
    importer.add_argument("--approve-execution-receipts", action="store_true")
    importer.add_argument("--output")
    inspector = commands.add_parser("evidence-inspect", help="개발 증거의 수용·격리·호출 비용 확인; 대상 실행 없음")
    inspector.add_argument("--bundle", type=Path, required=True)
    inspector.add_argument("--output")
    for command, help_text in (("evidence-learn", "승인된 Source context 전체로 기존 Version Space 생성"),
                               ("evidence-corroborate", "검토한 개발 관측 연결 후 동결; 독립성은 readiness에서 별도 검사")):
        parser = commands.add_parser(command, help=help_text)
        parser.add_argument("--bundle", type=Path, required=True)
        parser.add_argument("--implementation-hash", required=True)
        parser.add_argument("--spec-hash", required=True)
        parser.add_argument("--output")
        if command == "evidence-corroborate":
            parser.add_argument("--archive", type=Path, required=True)
            parser.add_argument("--approve-development-evidence", action="store_true")
    readiness = commands.add_parser("readiness-check", help="readiness 검사; 부족한 근거는 NOT_EXECUTED로 차단")
    readiness.add_argument("--bundle", type=Path, help="constructor의 JSON 자료 묶음; host 권한·실행 함수 제외")
    for option in ("evidence", "knowledge", "lineage", "targets", "protocol", "usage-ledger"):
        readiness.add_argument("--"+option, type=Path)
    readiness.add_argument("--authority-id")
    readiness.add_argument("--output")
    demo = commands.add_parser("readiness-demo", help="빈 Source/C/T를 차단하는 공개 기능 예제; 연구 성과 아님")
    demo.add_argument("--output")
    collect = commands.add_parser("evidence-collect", help="검토한 순수 함수의 Native Hypothesis 개발 수집; host 실행은 격리되지 않음")
    collect.add_argument("path", type=Path)
    collect.add_argument("--oracle-file", type=Path, required=True)
    collect.add_argument("--spec", type=Path, required=True)
    collect.add_argument("--provenance", type=Path, required=True)
    collect.add_argument("--oracle-validation", type=Path, required=True)
    collect.add_argument("--function", default="implementation")
    collect.add_argument("--oracle", default="reference")
    collect.add_argument("--function-identity", required=True)
    collect.add_argument("--generation-id", required=True)
    collect.add_argument("--allow-local-execution", action="store_true")
    collect.add_argument("--budget", type=int, default=64)
    collect.add_argument("--max-calls", type=int, default=256)
    collect.add_argument("--seed", type=int, default=7)
    collect.add_argument("--output")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _optional(path):
    if path is None:
        return None
    try:
        return _read(path)
    except (OSError, ValueError, TypeError) as error:
        return {"read_error":type(error).__name__, "detail":str(error)}


def _selected(evidence, implementation_hash, spec_hash):
    from .discovery.development_evidence import _hash
    _hash(implementation_hash); _hash(spec_hash)
    records = [r for r in evidence.accepted_records() if r["implementation_hash"] == implementation_hash and r["public_spec_hash"] == spec_hash]
    if not records:
        raise ValueError("일치하는 수용 DEVELOPMENT context가 없습니다")
    return records


def _evidence(value):
    from .discovery.development_evidence import DevelopmentEvidenceArchive
    if isinstance(value, dict) and value.get("schema") == "tomolab-native-development-collection-v1":
        value = value.get("evidence_bundle")
    return DevelopmentEvidenceArchive.from_snapshot(value)


def _readiness(args):
    from .discovery.evaluation_readiness import EvaluationReadiness
    from .discovery.evaluation_usage import UsageLedger
    from .discovery.schema import keys
    names = {"evidence":"evidence_bundle", "knowledge":"knowledge_snapshot", "lineage":"lineage_review",
             "targets":"targets", "protocol":"fixed_protocol"}
    values = _optional(args.bundle) if args.bundle else {}
    if not isinstance(values, dict) or "read_error" in values:
        values = {"evidence_bundle":values}
    else:
        keys(values, (), tuple(names.values()))
    values = deepcopy(values)
    for option, key in names.items():
        path = getattr(args, option)
        if path is not None:
            values[key] = _optional(path)
    usage = UsageLedger(args.usage_ledger, authority_id=args.authority_id) if args.usage_ledger else None
    return EvaluationReadiness(**values, usage_ledger=usage, authority=args.authority_id).authorize_final_comparison()


def dispatch(args, parser, examples):
    from .discovery.development_evidence import DevelopmentEvidenceArchive
    from .discovery.knowledge import KnowledgeArchive
    if args.command == "evidence-import":
        if not args.approve_execution_receipts:
            parser.error("evidence-import에는 --approve-execution-receipts 검토 승인이 필요합니다")
        value = _read(args.records)
        if isinstance(value, dict):
            from .discovery.schema import keys
            keys(value, ("records",))
            value = value["records"]
        if not isinstance(value, list):
            raise ValueError("공통 DEVELOPMENT 기록의 JSON 배열이 필요합니다")
        evidence = DevelopmentEvidenceArchive(args.generation_id, parent_generation_ids=args.parent_generation)
        for record in value:
            evidence.ingest(record, trusted_host=True)
        return evidence.snapshot()
    if args.command == "evidence-inspect":
        evidence = _evidence(_read(args.bundle))
        return {"schema":"tomolab-e8-evidence-inspection-v1", **evidence.summary(),
                "target_calls":0, "oracle_calls":0,
                "authority":"REVIEWED_HOST_ATTESTATION_NOT_TRUTH_OR_INDEPENDENCE_PROOF"}
    if args.command in ("evidence-learn", "evidence-corroborate"):
        if args.command == "evidence-corroborate" and not args.approve_development_evidence:
            parser.error("evidence-corroborate에는 --approve-development-evidence 검토 승인이 필요합니다")
        evidence = _evidence(_read(args.bundle))
        records = _selected(evidence, args.implementation_hash, args.spec_hash)
        if args.command == "evidence-learn":
            return evidence.build_knowledge_archive([r["record_id"] for r in records]).snapshot()
        knowledge = KnowledgeArchive.from_snapshot(_read(args.archive))
        for record in records:
            knowledge.observe(evidence.observation(record["record_id"]), trusted_observation=True)
        return knowledge.freeze()
    if args.command == "readiness-check":
        return _readiness(args)
    if args.command == "readiness-demo":
        from .discovery.evaluation_readiness import EvaluationReadiness
        return {"schema":"tomolab-e8-readiness-demo-v1", "scope":"AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH",
                "source_count":0, "corroboration_count":0, "target_count":0,
                "target_calls":0, "oracle_calls":0, "readiness":EvaluationReadiness(targets=[]).authorize_final_comparison()}
    if args.command == "evidence-collect":
        return _collect(args, parser)
    raise ValueError("알 수 없는 E8 명령")


def _collect(args, parser):
    # This guard is deliberately before reading or importing either module.
    if not args.allow_local_execution:
        parser.error("evidence-collect에는 --allow-local-execution이 필요합니다. 검토한 host 실행이며 OS 격리가 없습니다")
    from .discovery.schema import digest, identifier, integer, keys, validate_spec
    from .discovery.knowledge import validate_provenance
    from .discovery.development_evidence import _hash
    spec = validate_spec(_read(args.spec))
    origin = validate_provenance(_read(args.provenance))
    review = _read(args.oracle_validation)
    keys(review, ("status", "receipt_id", "oracle_hash", "public_spec_hash", "receipt_sha256", "comparison_policy"),
         ("authority", "source_receipt_sha256", "limitations"))
    if review["status"] != "VALIDATED" or not isinstance(review["receipt_id"], str) or not review["receipt_id"]:
        raise ValueError("실행 전에 독립 Oracle 검토 영수증이 필요합니다")
    if review["comparison_policy"] != "EXACT_CANONICAL_JSON":
        raise ValueError("개발 수집은 사전 검토한 EXACT_CANONICAL_JSON 비교 계약만 지원합니다")
    for field in ("oracle_hash", "public_spec_hash", "receipt_sha256"):
        _hash(review[field])
    if review["oracle_hash"] != origin.get("oracle_sha256") or review["public_spec_hash"] != digest(spec):
        raise ValueError("Oracle 검토의 코드·공개 명세 결속이 일치하지 않습니다")
    integer(args.budget, 1, 4096); integer(args.seed, 0, 2**32-1); integer(args.max_calls, 0, 10000)
    identifier(args.generation_id)
    if not isinstance(args.function_identity, str) or not 1 <= len(args.function_identity) <= 1024 or "\x00" in args.function_identity:
        raise ValueError("검토한 함수 식별자가 필요합니다")
    if len(spec["contract"]["invariants"]) != 1:
        raise ValueError("수집에는 하나의 독립 검토 invariant가 필요합니다")
    target, oracle = args.path.resolve(strict=True), args.oracle_file.resolve(strict=True)
    if target == oracle:
        raise ValueError("별도로 검토한 Oracle 파일이 필요합니다")
    expected_target = _hash(origin.get("implementation_sha256"))
    expected_oracle = _hash(origin.get("oracle_sha256"))
    before_target = hashlib.sha256(target.read_bytes()).hexdigest()
    before_oracle = hashlib.sha256(oracle.read_bytes()).hexdigest()
    if (before_target, before_oracle) != (expected_target, expected_oracle):
        raise ValueError("실행 전에 target·Oracle 파일 해시가 검토 provenance와 일치해야 합니다")
    # Import after opt-in, JSON/domain/budget/Oracle/provenance checks. _load
    # independently verifies file identity again immediately after each import.
    from .mold.service import _load
    from .discovery.development_collector import collect_native_development
    fn, target_hash = _load(target, args.function)
    ref, oracle_hash = _load(oracle, args.oracle)
    if (target_hash, oracle_hash) != (expected_target, expected_oracle):
        raise ValueError("검증과 import 사이에 코드가 변경되었습니다")
    result = collect_native_development(fn, ref, spec, provenance=origin,
        function_identity=args.function_identity, generation_id=args.generation_id,
        oracle_validation_receipt=review, budget=args.budget, seed=args.seed,
        max_calls=args.max_calls, trusted_execution=True)
    if (hashlib.sha256(target.read_bytes()).hexdigest(), hashlib.sha256(oracle.read_bytes()).hexdigest()) != (expected_target, expected_oracle):
        raise ValueError("개발 실행 중 target·Oracle 파일이 변경되었습니다")
    return result
