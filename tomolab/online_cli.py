"""Trusted local online execution using the shared experimental usage authority."""
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap
import time

COMMANDS = ("online-run", "online-learn", "online-demo", "online-replay")


def register(commands):
    for name in COMMANDS:
        p = commands.add_parser(name, help="단일 JSON 입력의 로컬 탐색 / 관측 재현 / 실험적 Source 정책 학습")
        p.add_argument("--output", type=Path, required=True)
        if name == "online-learn":
            p.add_argument("--observations", type=Path, required=True)
            p.add_argument("--mold", type=Path, required=True)
        elif name == "online-replay":
            p.add_argument("evidence", type=Path)
            p.add_argument("--source", type=Path, required=True)
            p.add_argument("--function", default="implementation")
            p.add_argument("--oracle", default="reference")
            p.add_argument("--oracle-file", type=Path, required=True)
            p.add_argument("--contract", type=Path, required=True)
            p.add_argument("--allow-local-execution", action="store_true")
            p.add_argument("--allow-unbound-legacy", action="store_true",
                           help="파일 바인딩이 없는 구형 영수증을 명시한 코드로 재현; 원본 코드 일치 미확인")
            p.add_argument("--max-witnesses", type=int, default=32)
        else:
            p.add_argument("--allow-local-execution", action="store_true")
            p.add_argument("--method", choices=("A", "B", "C", "D"), default="A",
                           help="A: 기본 native Hypothesis, B: 명시적 로컬 편집, C: 선택한 반례 재생, D: 실험적 Source 가이드")
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


def validate_json_callable(fn, role):
    """The public file CLI accepts exactly one synchronous positional JSON input."""
    if (not inspect.isfunction(fn) or inspect.iscoroutinefunction(fn)
            or inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn)):
        raise ValueError(f"{role}: one synchronous Python function with a single JSON argument is required")
    parameters = list(inspect.signature(fn).parameters.values())
    if len(parameters) != 1 or parameters[0].kind not in (
            inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise ValueError(f"{role}: exactly one positional JSON argument is supported; use an explicit adapter for other signatures")


def _require_qa():
    import importlib.util
    if importlib.util.find_spec("hypothesis") is None:
        raise ValueError('온라인 생성에는 선택 의존성이 필요합니다: pip install "antemortem-structural-lab[qa]"')


def _binding(target, oracle, contract, *, source_function=None, oracle_function=None):
    from .discovery.schema import digest
    value = dict(schema="tomolab-online-replay-binding-v1",
                 source_file_sha256=hashlib.sha256(Path(inspect.getfile(target)).read_bytes()).hexdigest(),
                 source_function=source_function if source_function is not None else target.__name__,
                 oracle_file_sha256=hashlib.sha256(Path(inspect.getfile(oracle)).read_bytes()).hexdigest(),
                 oracle_function=oracle_function if oracle_function is not None else oracle.__name__, contract_digest=digest(contract))
    return dict(value, binding_digest=digest(value))


def _method_context(args, replays, mold, result):
    from .discovery.schema import digest
    replay_file = getattr(args, "replays", None)
    provenance = dict(source="EXPLICIT_INPUT_FILE" if replay_file is not None else
                      "AUTHORED_DEMO_SOURCE_OBSERVATIONS" if replays else "NONE",
                      explicitly_selected=args.method in ("C", "D") and bool(replay_file or replays),
                      input_count=len(replays), input_digest=digest(replays),
                      input_only=True, labels_transferred=False,
                      domain_rejected=result.get("replay_inputs_rejected_before_transport", 0),
                      actual_replay_calls=result.get("source_replay_calls", 0))
    if replay_file is not None:
        provenance["file_sha256"] = hashlib.sha256(replay_file.read_bytes()).hexdigest()
    return dict(method=args.method, default_method="A", source_replays=provenance,
                experimental=args.method == "D", mold_digest=mold.get("artifact_digest") if mold else None,
                warning=("D는 실험적 Source 가이드입니다. C 대비 추가 가치가 입증되지 않았으며 음의 전이가 관측됐습니다."
                         if args.method == "D" else None))


def _execute(target, oracle, contract, args, *, mold, replays, configuration, target_identity=None, inspection_target=None):
    from .discovery.evaluation_usage import UsageLedger
    from .discovery.online_engine import run_online
    from .discovery.schema import digest
    validate_json_callable(target, "Target")
    validate_json_callable(oracle, "Oracle")
    # Replay binds the selected public export; callable_identity separately
    # records the actual function for the existing usage authority.
    binding = _binding(target, oracle, contract,
                       source_function=getattr(args, "function", None),
                       oracle_function=getattr(args, "oracle", None))
    if args.method == "D":
        print("경고: D는 실험적 Source 가이드이며 추가 가치가 입증되지 않았고 음의 전이가 관측됐습니다.", file=sys.stderr)
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
                run=result, replay_binding=binding,
                method_context=_method_context(args, replays, mold, result),
                final_target_eligible=False, allow_release=False,
                isolation="TRUSTED_LOCAL_LOGICAL_BOUNDARY_NOT_OS_SANDBOX")


def _replay(args):
    """Replay host-owned observed witnesses with the original comparison contract."""
    from .discovery.online_schema import input_identity, validate_contract, validate_input
    from .discovery.online_observe import observe
    from .discovery.schema import digest
    if type(args.max_witnesses) is not int or not 1 <= args.max_witnesses <= 256:
        raise ValueError("--max-witnesses must be between 1 and 256")
    payload = _read(args.evidence)
    if not isinstance(payload, dict):
        raise ValueError("online run receipt required")
    if "historical_case" in payload:
        raise ValueError("historical catalog receipts require their reviewed OCI execution path; generic online-replay does not execute them")
    run = payload.get("run", payload)
    if not isinstance(run, dict) or run.get("schema") != "tomolab-online-result-v1":
        raise ValueError("online-replay requires a tomolab-online-cli-v1 or tomolab-online-result-v1 receipt")
    if run.get("receipt_sha256") != digest({k:v for k,v in run.items() if k != "receipt_sha256"}):
        raise ValueError("online run receipt digest differs")
    contract = validate_contract(_read(args.contract))
    if contract != run.get("contract"):
        raise ValueError("replay contract differs from the original public comparison contract")
    binding = payload.get("replay_binding")
    binding_status = "FILE_AND_CONTRACT_BINDINGS_MATCH"
    if binding is None:
        if not args.allow_unbound_legacy:
            raise ValueError("legacy receipt has no source/Oracle file binding; --allow-unbound-legacy is required and cannot verify original code identity")
        binding_status = "LEGACY_SOURCE_ORACLE_IDENTITY_UNVERIFIED"
        print("경고: 구형 영수증에는 원본 Target·Oracle 파일 바인딩이 없어 명시한 코드와의 관측 일치만 확인합니다.", file=sys.stderr)
    else:
        if not isinstance(binding, dict) or binding.get("schema") != "tomolab-online-replay-binding-v1" or binding.get("binding_digest") != digest({k:v for k,v in binding.items() if k != "binding_digest"}):
            raise ValueError("replay source/Oracle binding digest differs")
        expected = dict(source_file_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                        source_function=args.function,
                        oracle_file_sha256=hashlib.sha256(args.oracle_file.read_bytes()).hexdigest(),
                        oracle_function=args.oracle, contract_digest=digest(contract))
        if any(binding.get(k) != v for k,v in expected.items()):
            raise ValueError("replay Target, Oracle, function or contract identity drift; no target was executed")
    observations = run.get("observations")
    private = run.get("private_outcomes")
    failures = run.get("confirmed_failures")
    if (not isinstance(observations, list) or not isinstance(private, list) or not isinstance(failures, list)
            or any(not isinstance(row, dict) for rows in (observations, private, failures) for row in rows)):
        raise ValueError("host observations, private semantic references and confirmed witnesses required")
    witnesses = [(row.get("input"), row.get("input_digest")) for row in failures]
    shrink = run.get("shrinking", {})
    if not isinstance(shrink, dict):
        raise ValueError("stored shrinking receipt must be an object")
    if shrink.get("status") == "REPRODUCED":
        witnesses.append((shrink.get("witness"), input_identity(shrink.get("witness"))))
    unique = {}
    references = {row.get("event"): row.get("semantic_digest") for row in private if isinstance(row, dict)}
    for point, token in witnesses:
        if not validate_input(point, contract) or token != input_identity(point):
            raise ValueError("stored witness is invalid or its input digest differs")
        reference = next((i for i,row in enumerate(observations) if row.get("input_digest") == token and row.get("status") == "FAILURE"), None)
        if reference is None or not isinstance(references.get(reference), str):
            raise ValueError("stored witness lacks its original host semantic reference")
        unique[token] = (point, references[reference])
    if len(unique) > args.max_witnesses:
        raise ValueError("stored witness count exceeds --max-witnesses; no target was executed")
    if not unique:
        return dict(schema="tomolab-online-replay-receipt-v1", status="COMPLETE", replay_status="NO_CONFIRMED_FAILURE",
                    binding_status=binding_status, replayed=0, target_calls=0, oracle_calls=0,
                    source_receipt_sha256=hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
                    results=[], research_comparison_reexecuted=False, allow_release=False)
    from .cast import load_trusted_functions
    target, oracle = load_trusted_functions(args.source, args.function, args.oracle, args.oracle_file)
    validate_json_callable(target, "Target"); validate_json_callable(oracle, "Oracle")
    rows = []
    for token, (point, expected_semantic) in unique.items():
        repeated = [observe(target, oracle, deepcopy(point), contract, tracing=False) for _ in range(3)]
        reproduced = all(row["feedback"]["status"] == "FAILURE" and row["semantic_digest"] == expected_semantic for row in repeated)
        rows.append(dict(input=deepcopy(point), input_digest=token, reproduced=reproduced,
                         statuses=[row["feedback"]["status"] for row in repeated],
                         semantic_references_match=[row["semantic_digest"] == expected_semantic for row in repeated]))
    reproduced = all(row["reproduced"] for row in rows)
    return dict(schema="tomolab-online-replay-receipt-v1", status="COMPLETE" if reproduced else "INCONCLUSIVE",
                replay_status="REPRODUCED" if reproduced else "NOT_REPRODUCED", binding_status=binding_status,
                replayed=len(rows), target_calls=3*len(rows), oracle_calls=3*len(rows), results=rows,
                source_receipt_sha256=hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
                comparison_contract_digest=digest(contract),
                isolation="TRUSTED_LOCAL_EXECUTION_NOT_OS_SANDBOX", research_comparison_reexecuted=False,
                scope="SAME_OBSERVED_BEHAVIOR_UNDER_EXPLICIT_TARGET_ORACLE_AND_PUBLIC_COMPARISON_CONTRACT",
                allow_release=False)


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
    if args.command == "online-replay":
        return _replay(args)
    _require_qa()
    from .cast import load_trusted_functions
    if args.command == "online-demo":
        args.workspace.mkdir(parents=True, exist_ok=False)
        if args.method in ("A", "B"):
            folder = examples/"product"
            contract = _read(folder/"contract.json")
            target, oracle = load_trusted_functions(folder/"target.py", "implementation", "reference", folder/"oracle.py")
            result = _execute(target, oracle, contract, args, mold=None, replays=[],
                              configuration=dict(contract=contract, role="AUTHORED_PRODUCT_FUNCTIONAL", method=args.method))
            result["source_learning"] = dict(enabled=False, target_calls=0, oracle_calls=0, rules=0,
                reason="SOURCE_LEARNING_NOT_REQUESTED")
            return result
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
        result["source_learning"] = dict(enabled=True, target_calls=collected["run"]["target_calls"],
            oracle_calls=collected["run"]["oracle_calls"], rules=len(mold["rules"]), mold_digest=mold["artifact_digest"],
            origin="AUTHORED_DEMO_SOURCE_OBSERVATIONS", observation_receipt_sha256=hashlib.sha256(source_args.output.read_bytes()).hexdigest(),
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
