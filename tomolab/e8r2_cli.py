"""Source-only numerical recipe preparation, compact compilation and execution."""
from copy import deepcopy
import json
from pathlib import Path

COMMANDS = ("numerical-prepare", "numerical-compile", "numerical-inspect",
            "numerical-run", "numerical-compare", "numerical-demo")


def register(commands):
    for name in COMMANDS:
        parser = commands.add_parser(name, help="R2 수치 Source 개발 경로; 외적 전이·발행 권한을 부여하지 않음")
        parser.add_argument("--output")
        if name in ("numerical-prepare", "numerical-compile"):
            parser.add_argument("--archive", type=Path, required=True)
        if name == "numerical-compile":
            parser.add_argument("--recipe", type=Path, required=True)
        if name in ("numerical-inspect", "numerical-run", "numerical-compare"):
            parser.add_argument("--guide", type=Path, required=True)
            parser.add_argument("--approval", type=Path, required=True)
            pins = parser.add_mutually_exclusive_group(required=True)
            pins.add_argument("--expected-digest")
            pins.add_argument("--expected-digest-file", type=Path)
        if name in ("numerical-run", "numerical-compare", "numerical-demo"):
            parser.add_argument("--seed", type=int, default=7)
            parser.add_argument("--size", type=int, default=8)
            parser.add_argument("--max-examples", type=int, default=128)
            parser.add_argument("--budget", type=int, default=32, help="각 방법의 실제 Source/Oracle 쌍 상한; 재현·축소 포함")
            parser.add_argument("--shrink-budget", type=int, default=0)
            parser.add_argument("--backend", choices=("subprocess","docker"), default="subprocess")
            parser.add_argument("--image", default="tomolab-e7-generator:local")
        if name in ("numerical-run", "numerical-compare"):
            parser.add_argument("--allow-local-execution", action="store_true")
            parser.add_argument("--known-inputs", type=Path, help="개발용 입력 목록; Generator에는 digest만 전송")
            parser.add_argument("--replays", type=Path, help="C용 검토된 실패 입력 목록; host에만 유지")
        if name == "numerical-run":
            parser.add_argument("--method", choices=("A","B","C","D"), default="D")
        if name == "numerical-demo":
            parser.add_argument("--workspace", type=Path, help="새 폴더에 공개 작성 기능 예제 archive/recipe/guide 영수증 저장")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_new(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def functional_archive():
    """Two explicitly provided public diagnostics, not private failure logs.

    This tiny fixture exercises the same preparation/compiler APIs. It cannot
    substitute for the separately verified 72 MB Source archive.
    """
    from .discovery.knowledge import KnowledgeArchive
    from .discovery.numerical_source import evaluate_point
    item = {"kind":"list", "min_size":3, "max_size":6,
            "items":{"kind":"float", "min":-1.0, "max":1.0}}
    spec = {"schema":"tomolab-discovery-spec-v1", "task_id":"r2-public-functional-fixture",
        "inputs":[{"name":"a","role":"left-series","type":deepcopy(item)},
                  {"name":"b","role":"right-series","type":deepcopy(item)}],
        "contract":{"id":"public-numerical-fixture", "operation":"robust-linear-correlation",
            "preconditions":["equal-series-lengths","robust-numeric-variance-domain"],
            "invariants":["independent-equivalence"], "state_model":"stateless", "graph_signature":"UNKNOWN"}}
    origin = {"project":"authored-public-fixture", "lineage":"provided-diagnostic-not-discovered",
        "revision":"functional-v1", "oracle_id":"existing-reviewed-exact-input-helper",
        "semantics":"robust-linear-correlation", "implementation_sha256":"1"*64,
        "oracle_sha256":"2"*64, "independence_id":"not-independent-research-evidence"}
    events = []
    for index, value in enumerate((0.1,0.25)):
        point = {"a":[value]*3, "b":[value]*3}
        row = evaluate_point(point)
        events.append({"evidence_id":"public-diagnostic-"+str(index),
            "kind":"FAILURE" if row["failed"] else "REFUTATION", "inputs":point,
            "invariant":"independent-equivalence", "category":"mismatch", "signature":"provided-centering"})
    return KnowledgeArchive.from_failure_log(spec, events, origin,
        semantic_policy={"max_compound_relations":0}).freeze()


def dispatch(args, parser, examples):
    # Lazy imports keep all pre-existing base-package commands dependency-free.
    from .discovery.compact_guidance import (prepare_recipe_from_archive,
        compile_execution_artifact, validate_execution_artifact)
    from .discovery.numerical_guidance import numerical_input_digest, public_input_contract
    if args.command == "numerical-prepare":
        result = prepare_recipe_from_archive(_read(args.archive))
        result["scope"] = "SOURCE_DEVELOPMENT_NOT_TRANSFER_QUALIFICATION"
        return result
    if args.command == "numerical-compile":
        prepared = _read(args.recipe)
        recipe = prepared.get("recipe", prepared)
        return compile_execution_artifact(_read(args.archive), [recipe], recipe["public_contract"])
    if args.command == "numerical-demo":
        from .discovery.numerical_service import run_numerical_method
        if args.workspace:
            # Exclusive fresh folder prevents replacing a previous frozen run.
            args.workspace.mkdir(parents=True, exist_ok=False)
            snapshot = functional_archive()
            prepared = prepare_recipe_from_archive(snapshot)
            compiled = compile_execution_artifact(snapshot, [prepared["recipe"]], public_input_contract())
            for name,value in (("archive.json",snapshot),("recipe.json",prepared),
                ("guide.json",compiled["artifact"]),("approval.json",compiled["approval_receipt"])):
                _write_new(args.workspace/name, value)
            with (args.workspace/"guide.sha256").open("x", encoding="ascii") as stream:
                stream.write(compiled["artifact"]["artifact_digest"]+"\n")
            public_replays = [{"a":[0.1]*3,"b":[0.1]*3}]
            _write_new(args.workspace/"replays.json", public_replays)
            setup = prepared["metrics"]["wall_seconds"]+compiled["metrics"]["wall_seconds"]
        else:
            folder = examples/"numerical"
            compiled = {"artifact":_read(folder/"source-guide.json"),
                        "approval_receipt":_read(folder/"source-approval.json")}
            setup = 0.0
        pin = (compiled["artifact"]["artifact_digest"] if args.workspace else
               (examples/"numerical"/"source-guide.sha256").read_text(encoding="ascii").strip())
        run = run_numerical_method(compiled, expected_digest=pin, seed=args.seed,
            size=args.size, max_examples=args.max_examples, pair_budget=args.budget,
            shrink_budget=args.shrink_budget, backend=args.backend, image=args.image,
            setup_seconds=setup, excluded_digests=[numerical_input_digest({"a":[v]*3,"b":[v]*3}) for v in (0.1,0.25)])
        return {"schema":"tomolab-numerical-functional-demo-v1",
            "scope":"FUNCTIONAL_INSTALLED_PROFILE_NOT_RESEARCH_COMPARISON", "run":run,
            "preparation_target_calls":2 if args.workspace else 0,
            "preparation_oracle_calls":2 if args.workspace else 0,
            "archive_kind":"AUTHORED_PROVIDED_DIAGNOSTICS" if args.workspace else "PREVIOUSLY_APPROVED_REAL_SOURCE_GUIDE",
            "allow_release":False}
    compiled = {"artifact":_read(args.guide), "approval_receipt":_read(args.approval)}
    pin = args.expected_digest or args.expected_digest_file.read_text(encoding="ascii").strip()
    artifact = validate_execution_artifact(compiled["artifact"], pin, compiled["approval_receipt"])
    if args.command == "numerical-inspect":
        return {"status":"PASS", "artifact_digest":pin, "source_archive_digest":artifact["source_archive_digest"],
            "scope":artifact["applicability_scope"], "artifact_bytes":len(json.dumps(artifact,separators=(",",":"),sort_keys=True).encode()),
            "execution":"NOT_EXECUTED", "target_calls":0, "oracle_calls":0, "allow_release":False}
    if not args.allow_local_execution:
        parser.error("numerical-run/compare는 --allow-local-execution이 필요합니다; 검토된 고정 Source만 host에서 실행합니다")
    from .discovery.numerical_service import run_numerical_method, run_numerical_comparison
    known = _read(args.known_inputs) if args.known_inputs else []
    replays = _read(args.replays) if args.replays else []
    if not isinstance(known,list) or not isinstance(replays,list):
        raise ValueError("bounded host input lists required")
    controls = dict(expected_digest=pin, size=args.size, max_examples=args.max_examples,
        pair_budget=args.budget, shrink_budget=args.shrink_budget,
        excluded_digests=sorted({numerical_input_digest(p) for p in known+replays}),
        replay_inputs=replays, backend=args.backend, image=args.image)
    if args.command == "numerical-run":
        return run_numerical_method(compiled, method=args.method, seed=args.seed, **controls)
    if not replays:
        raise ValueError("공정한 C 비교에는 D 보정과 동일한 검토된 실패 입력 --replays가 필요합니다")
    return run_numerical_comparison(compiled, seeds=(args.seed,), **controls)
