"""Trusted local online execution using the shared experimental usage authority."""
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
import time

COMMANDS = ("online-run", "online-learn", "online-demo")


def register(commands):
    for name in COMMANDS:
        p = commands.add_parser(name, help="E9 타깃 내부 온라인 탐색 / Source 변형 정책 학습; 미발행 실험 기능")
        p.add_argument("--output", type=Path, required=True)
        if name == "online-learn":
            p.add_argument("--observations", type=Path, required=True)
            p.add_argument("--mold", type=Path, required=True)
        else:
            p.add_argument("--allow-local-execution", action="store_true")
            p.add_argument("--method", choices=("A", "B", "C", "D"), default="C")
            p.add_argument("--seed", type=int, default=7)
            p.add_argument("--budget", type=int, default=48)
            p.add_argument("--shrink-budget", type=int, default=8)
            p.add_argument("--max-seconds", type=float, default=30)
            p.add_argument("--mode", choices=("structural", "black_box"), default="structural")
            p.add_argument("--usage-ledger", type=Path, required=True)
            if name == "online-run":
                p.add_argument("path", type=Path)
                p.add_argument("--function", default="implementation")
                p.add_argument("--oracle", default="reference")
                p.add_argument("--oracle-file", type=Path, required=True)
                p.add_argument("--contract", type=Path, required=True)
                p.add_argument("--replays", type=Path)
                p.add_argument("--mold", type=Path)
                p.add_argument("--expected-digest")
            else:
                p.add_argument("--workspace", type=Path, required=True)


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 8_000_000:
        raise ValueError("online JSON request exceeds the existing transport resource ceiling")
    return json.loads(raw)


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=False)+"\n")
        handle.flush(); os.fsync(handle.fileno())


def callable_identity(fn):
    """Portable function identity for the existing cooperative usage ledger."""
    from .discovery.schema import digest
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    original = ast.dump(tree, include_attributes=False)
    from .discovery.analysis import analyze_source
    normalized = analyze_source(textwrap.dedent(inspect.getsource(fn)), fn.__name__)["graph_signature"]
    # A clone token is conservative: name-only copies cannot become unseen.
    module = Path(inspect.getfile(fn)).name
    return dict(canonical_function_identity=digest(dict(module=module, function=fn.__name__, ast=original)),
                cross_revision_function_key=digest(dict(module=module, function=fn.__name__)),
                normalized_ast_clone_sha256=normalized, implementation_sha256=digest(original))


def _execute(target, oracle, contract, args, *, mold, replays, configuration, target_identity=None, inspection_target=None):
    from .discovery.evaluation_usage import UsageLedger
    from .discovery.online_engine import run_online
    from .discovery.schema import digest
    authority = digest({"fixed_online_authority": str(args.usage_ledger.resolve())})
    ledger = UsageLedger(args.usage_ledger, authority_id=authority)
    # This explicit trusted-host command binds the current algorithm and data.
    package = Path(__file__).resolve().parent
    algorithm = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(package.rglob("*.py"))}
    profile = dict(schema="tomolab-online-execution-profile-v1", scope="EXPERIMENTAL_PROBE",
                   authority_id=authority, algorithm_digest=digest(algorithm),
                   initial_knowledge_digest=digest(mold), configuration_digest=digest(configuration),
                   target_local_feedback=True, cross_target_feedback=False,
                   final_evaluation_authorized=False, publication_authorized=False)
    start = ledger.claim_experimental([target_identity or callable_identity(target)], profile,
                                      expected_profile=deepcopy(profile), output=args.output)
    result = run_online(target, oracle, contract, method=args.method, seed=args.seed,
                        budget=args.budget, shrink_budget=args.shrink_budget,
                        mold=mold, replays=replays, max_seconds=args.max_seconds, mode=args.mode,
                        inspection_target=inspection_target)
    ledger.complete(start["claim_id"], dict(status=result.get("status"), receipt_sha256=digest(result)))
    return dict(schema="tomolab-online-cli-v1", status="COMPLETE" if result.get("status") == "COMPLETE" and result.get("outcome") != "INCONCLUSIVE" else "INCONCLUSIVE", execution_profile=profile,
                run=result, final_target_eligible=False, allow_release=False,
                isolation="TRUSTED_LOCAL_LOGICAL_BOUNDARY_NOT_OS_SANDBOX")


def dispatch(args, parser, examples):
    started = time.perf_counter()
    from .discovery.online_learning import learn_mold, load_mold, save_mold
    from .discovery.schema import digest
    if args.output.exists() or Path(str(args.output)+".io.json").exists():
        raise FileExistsError("online execution receipts must use new paths")
    if args.command == "online-learn":
        payload = _read(args.observations)
        observations = (payload.get("run", payload).get("observations")
                        if isinstance(payload, dict) else payload)
        if not isinstance(observations, list):
            raise ValueError("Source observation list or online-run receipt required")
        mold = learn_mold(observations)
        save_mold(args.mold, mold)
        return dict(schema="tomolab-online-learning-receipt-v1", status="COMPLETE",
                    mold_digest=mold["artifact_digest"], mold_bytes=len(json.dumps(mold, separators=(",",":"), sort_keys=True).encode()),
                    source_observations=len(observations), rules=len(mold["rules"]),
                    learning_wall_seconds=time.perf_counter()-started, allow_release=False)
    if not args.allow_local_execution:
        parser.error("온라인 타깃·Oracle 실행에는 --allow-local-execution이 필요합니다; OS sandbox가 아닙니다")
    from .cast import load_trusted_functions
    if args.command == "online-demo":
        args.workspace.mkdir(parents=True, exist_ok=False)
        folder = examples/"online"
        contract = _read(folder/"contract.json")
        source, source_oracle = load_trusted_functions(folder/"source.py", "implementation", "reference", folder/"oracle.py")
        source_args = deepcopy(args)
        source_args.method = "B"
        source_args.output = args.workspace/"source.json"
        collected = _execute(source, source_oracle, contract, source_args, mold=None, replays=[],
                             configuration=dict(contract=contract, role="AUTHORED_SOURCE_FUNCTIONAL"))
        _write(source_args.output, collected)
        mold = learn_mold(collected["run"]["observations"])
        save_mold(args.workspace/"mold.json", mold)
        replays = [r["input"] for r in collected["run"]["observations"] if r["status"] == "FAILURE"]
        target, oracle = load_trusted_functions(folder/"target.py", "implementation", "reference", folder/"oracle.py")
        result = _execute(target, oracle, contract, args, mold=mold if args.method == "D" else None,
                          replays=replays if args.method in ("C","D") else [],
                          configuration=dict(contract=contract, role="AUTHORED_TARGET_FUNCTIONAL", method=args.method))
        result["source_learning"] = dict(target_calls=collected["run"]["target_calls"],
            oracle_calls=collected["run"]["oracle_calls"], rules=len(mold["rules"]), mold_digest=mold["artifact_digest"],
            total_source_plus_target_before_receipt_seconds=time.perf_counter()-started)
        return result
    contract = _read(args.contract)
    replays = _read(args.replays) if args.replays else []
    if not isinstance(replays, list):
        raise ValueError("input-only replay list required")
    mold = None
    if args.method == "D":
        if not args.mold or not args.expected_digest:
            parser.error("D requires --mold and --expected-digest from trusted Source preparation")
        mold = load_mold(args.mold, expected_digest=args.expected_digest)
    elif args.mold or args.expected_digest:
        parser.error("A/B/C do not load the learned D provider")
    if args.method in ("A", "B") and replays:
        parser.error("Source replays belong to C/D")
    target, oracle = load_trusted_functions(args.path, args.function, args.oracle, args.oracle_file)
    config = dict(contract=contract, method=args.method, seed=args.seed, budget=args.budget,
                  shrink_budget=args.shrink_budget, max_seconds=args.max_seconds, mode=args.mode,
                  target_identity=callable_identity(target), oracle_identity=callable_identity(oracle),
                  replay_digest=digest(replays), mold_digest=digest(mold))
    return _execute(target, oracle, contract, args, mold=mold, replays=replays, configuration=config)
