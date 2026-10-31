"""Reviewed historical catalog commands; external execution requires the OCI gate."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

COMMANDS = ("historical-inspect", "historical-run")


def register(commands):
    for name in COMMANDS:
        p = commands.add_parser(name, help="검토된 과거 비보안 결함: metadata 조회 / 격리된 실제 실행")
        p.add_argument("--catalog", type=Path, required=True, help="검토된 manifest.json의 디렉터리")
        p.add_argument("--output", type=Path, required=True)
        if name == "historical-run":
            p.add_argument("--factory", type=Path, required=True)
            p.add_argument("--expected-factory-sha256", required=True)
            p.add_argument("--case", required=True)
            p.add_argument("--method", choices=("A","B","C","D"), default="A")
            p.add_argument("--mold", type=Path)
            p.add_argument("--expected-digest")
            p.add_argument("--replays", type=Path)
            p.add_argument("--usage-ledger", type=Path, required=True)
            p.add_argument("--seed", type=int, default=11)
            p.add_argument("--budget", type=int, default=24)
            p.add_argument("--shrink-budget", type=int, default=6)
            p.add_argument("--max-seconds", type=float, default=30)
            p.add_argument("--allow-local-execution", action="store_true")


def dispatch(args, parser):
    from .online_cli import _read, _execute
    from .discovery.schema import digest
    if args.output.exists() or Path(str(args.output)+".io.json").exists():
        raise FileExistsError("historical receipts must be new")
    if args.command == "historical-inspect":
        manifest = _read(args.catalog/"manifest.json")
        # Reading data does not import or execute upstream modules or the factory.
        return dict(schema="tomolab-historical-catalog-inspection-v1",status="COMPLETE",
            catalog=manifest,external_code_executed=False,target_calls=0,oracle_calls=0,
            execution_scope="METADATA_ONLY",allow_release=False)
    if not args.allow_local_execution:
        parser.error("역사적 외부 코드 실행에는 --allow-local-execution 및 검증된 OCI 경계가 필요합니다")
    from .historical import require_reviewed_container
    boundary = require_reviewed_container()
    factory = args.factory.resolve(strict=True)
    if not factory.is_relative_to(Path("/app")) or hashlib.sha256(factory.read_bytes()).hexdigest() != args.expected_factory_sha256:
        raise PermissionError("reviewed read-only factory differs from expected source commitment")
    spec = importlib.util.spec_from_file_location("_tomolab_reviewed_historical_catalog",factory)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    case = module.load_case(args.case,catalog=args.catalog)
    mold = None
    if args.method == "D":
        if args.mold is None or args.expected_digest is None:
            parser.error("D requires --mold and its externally expected --expected-digest")
        from .discovery.online_mold import load_mold
        mold = load_mold(args.mold,expected_digest=args.expected_digest)
    elif args.mold or args.expected_digest:
        parser.error("A/B/C do not load Source rule providers")
    replays = _read(args.replays) if args.replays else []
    if not isinstance(replays,list) or (replays and args.method in ("A","B")):
        raise ValueError("only C/D accept a Source input-only replay list")
    # Inspect the reviewed original function, never the adapter's literals.
    # Class construction/argument mapping is outside the current MRI grammar.
    import inspect
    original = case.target.upstream_function
    inspection_target = original if inspect.isfunction(original) else None
    args.mode = "structural" if inspection_target is not None else "black_box"
    metadata = case.metadata()
    result = _execute(case.target,case.oracle,case.contract,args,mold=mold,replays=replays,
        configuration=dict(case=metadata,factory_sha256=args.expected_factory_sha256,
            boundary_binding=boundary["binding"],oracle_contract=metadata.get("oracle_sha256"),
            source_replay_digest=digest(replays)),target_identity=metadata["identity"],
        inspection_target=inspection_target)
    result.update(historical_case=metadata,execution_boundary=boundary,
                  classification="HISTORICAL_DEFECT_REDISCOVERY_NOT_NEW_UPSTREAM_BUG",
                  observation_scope=("REVIEWED_ORIGINAL_AST_AND_ROOT_COVERAGE_ARGUMENT_MAPPING_UNKNOWN"
                    if inspection_target is not None else "UNSUPPORTED_CLASS_EXPLICIT_BLACK_BOX"),
                  isolation="REVIEWED_CONTAINER_BOUNDARY")
    return result
