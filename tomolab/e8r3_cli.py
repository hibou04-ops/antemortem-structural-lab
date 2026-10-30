"""Explicit R3 runtime/audit and separately approved guide preparation."""
import json
from pathlib import Path
import time

COMMANDS = ("numerical-prepare-guide", "numerical-runtime", "numerical-audit")


def register(commands):
    for name in COMMANDS:
        parser = commands.add_parser(name, help="R3 단일 생성 runtime / 전체 동등성 audit; 연구용 미발행 기능")
        parser.add_argument("--output", type=Path, required=True,
                            help="새 실행 영수증; 별도 .io.json에 기록·flush 비용 저장")
        if name == "numerical-prepare-guide":
            parser.add_argument("--archive", type=Path, required=True)
            parser.add_argument("--prepared-dir", type=Path, required=True)
            parser.add_argument("--approval-state", type=Path, required=True,
                                help="가이드 디렉터리 밖에 새로 저장할 신뢰된 host 승인 상태")
        else:
            parser.add_argument("--method", choices=("A", "B", "C", "D"),
                                default="B" if name == "numerical-runtime" else "D")
            parser.add_argument("--prepared-dir", type=Path)
            parser.add_argument("--approval-state", type=Path,
                                help="신뢰된 host가 별도로 관리하는 현재 승인 상태")
            parser.add_argument("--expected-digest")
            parser.add_argument("--known-inputs", type=Path)
            parser.add_argument("--replays", type=Path)
            parser.add_argument("--seed", type=int, default=7)
            parser.add_argument("--size", type=int, default=32)
            parser.add_argument("--max-examples", type=int, default=512)
            parser.add_argument("--budget", type=int, default=96)
            parser.add_argument("--shrink-budget", type=int, default=16)
            parser.add_argument("--backend", choices=("subprocess", "docker"), default="subprocess")
            parser.add_argument("--image", default="tomolab-e7-generator:local")
            parser.add_argument("--allow-local-execution", action="store_true")


def dispatch(args, parser):
    started = time.perf_counter()
    from .discovery.numerical_prepared import (prepare_approved_guide,
        load_prepared_guide, read_approval_state)
    from .discovery.schema import digest
    if args.output.exists() or Path(str(args.output)+".io.json").exists():
        raise FileExistsError("R3 receipts must use new paths")
    if args.command == "numerical-prepare-guide":
        result = prepare_approved_guide(args.archive, args.prepared_dir, args.approval_state)
    else:
        if not args.allow_local_execution:
            parser.error("R3 수치 실행에는 --allow-local-execution이 필요합니다")
        from .discovery.numerical_service import run_numerical_method
        from .discovery.numerical_guidance import numerical_input_digest, public_input_contract
        compiled, expected, prepared_metrics = None, None, None
        if args.method == "D":
            if not all((args.prepared_dir, args.approval_state, args.expected_digest)):
                parser.error("D에는 --prepared-dir, --approval-state, --expected-digest가 필요합니다")
            loaded = load_prepared_guide(args.prepared_dir, expected_digest=args.expected_digest,
                expected_current_context=read_approval_state(args.approval_state))
            compiled, expected, prepared_metrics = loaded["compiled"], args.expected_digest, loaded["metrics"]
        elif any((args.prepared_dir, args.approval_state, args.expected_digest)):
            parser.error("A/B/C는 D 가이드·승인 상태를 읽지 않습니다; 해당 옵션을 제거하세요")
        known = json.loads(args.known_inputs.read_text(encoding="utf-8")) if args.known_inputs else []
        replay = json.loads(args.replays.read_text(encoding="utf-8")) if args.replays else []
        if not isinstance(known, list) or not isinstance(replay, list):
            raise ValueError("known inputs and replays must be JSON lists")
        excluded = [item if isinstance(item, str) else numerical_input_digest(item) for item in known]
        profile = "runtime" if args.command == "numerical-runtime" else "audit"
        result = run_numerical_method(compiled, expected_digest=expected, method=args.method,
            seed=args.seed, size=args.size, max_examples=args.max_examples,
            pair_budget=args.budget, shrink_budget=args.shrink_budget,
            excluded_digests=excluded, replay_inputs=replay,
            contract=public_input_contract(lengths=[4,5,6]),
            backend=args.backend, image=args.image, verification_profile=profile)
        if prepared_metrics:
            result = dict(schema="tomolab-r3-prepared-execution-v1", status=result["status"],
                prepared_load=prepared_metrics, run=result, allow_release=False)
    return dict(schema="tomolab-r3-cli-receipt-v1", command=args.command,
        status=result.get("status", "COMPLETE"), result=result, allow_release=False,
        cli_dispatch_seconds_before_serialization=time.perf_counter()-started,
        cli_dispatch_includes_lazy_imports=True, process_startup_included=False,
        output_contract="SEPARATE_IO_RECEIPT_BINDS_WRITTEN_BYTES", result_digest=digest(result))


def save_receipt(result, output, *, main_started):
    """No circular self-timing: the companion binds the completed primary write."""
    from .discovery.numerical_prepared import _write_new
    import hashlib
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialization_started = time.perf_counter()
    payload = (json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)+"\n").encode("utf-8")
    serialized = time.perf_counter()-serialization_started
    write_started = time.perf_counter()
    with output.open("xb") as stream:
        import os
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    written = time.perf_counter()-write_started
    io = dict(schema="tomolab-r3-cli-io-v1", receipt_sha256=hashlib.sha256(payload).hexdigest(),
        receipt_bytes=len(payload), serialization_seconds=serialized,
        write_flush_seconds=written, main_through_receipt_flush_seconds=time.perf_counter()-main_started,
        excludes_python_startup_and_cli_module_imports=True,
        companion_self_write_cost="EXCLUDED_USE_EXTERNAL_PROCESS_TIMER")
    _write_new(str(output)+".io.json", io)
    return io
