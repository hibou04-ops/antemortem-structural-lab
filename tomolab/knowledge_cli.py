"""E7 CLI adapters; targets execute only in the explicitly trusted host."""
import hashlib
import json
from pathlib import Path


def register(commands):
    demo = commands.add_parser("knowledge-demo", help="Run authored E7 evidence-gating fixtures; not a research benchmark")
    demo.add_argument("--case", choices=("qualified", "contradicted", "clean", "no-prior"), default="qualified")
    learn = commands.add_parser("knowledge-learn", help="Learn competing structural claims from a bounded development failure log")
    learn.add_argument("--spec", required=True, type=Path)
    learn.add_argument("--failure-log", required=True, type=Path)
    learn.add_argument("--provenance", required=True, type=Path)
    learn.add_argument("--observations", type=Path)
    learn.add_argument("--approve-development-evidence", action="store_true")
    learn.add_argument("--public-ir", type=Path)
    learn.add_argument("--temporal-contract", type=Path)
    learn.add_argument("--store", type=Path)
    learn.add_argument("--record-id")
    update = commands.add_parser("knowledge-update", help="Create an explicit new development generation while preserving frozen history")
    update.add_argument("--archive", required=True, type=Path)
    update.add_argument("--observations", required=True, type=Path)
    update.add_argument("--generation-id", required=True)
    update.add_argument("--approve-development-evidence", action="store_true")
    update.add_argument("--store", type=Path)
    update.add_argument("--record-id")
    inspect = commands.add_parser("knowledge-inspect", help="Validate public knowledge contracts and applicability without target execution")
    plan = commands.add_parser("knowledge-plan", help="Freeze evidence-qualified probes with zero target or Oracle calls")
    run = commands.add_parser("knowledge-run", help="Compare explicitly trusted local pure functions with an independent Oracle")
    run.add_argument("path", type=Path)
    run.add_argument("--oracle-file", required=True, type=Path)
    run.add_argument("--function", default="implementation")
    run.add_argument("--oracle", default="reference")
    run.add_argument("--allow-local-execution", action="store_true")
    run.add_argument("--failure-signature", default="reference-comparison")
    for parser in (inspect, plan, run):
        parser.add_argument("--spec", required=True, type=Path)
        parser.add_argument("--archive", type=Path, required=parser is plan)
        parser.add_argument("--target-provenance", type=Path)
        parser.add_argument("--public-ir", type=Path)
        if parser is not run:
            parser.add_argument("--temporal-contract", type=Path)
    for parser in (demo, plan, run):
        parser.add_argument("--budget", type=int, default=32)
        parser.add_argument("--shrink-budget", type=int, default=32)
        parser.add_argument("--guidance-budget", type=int, default=8)
        parser.add_argument("--pool-size", type=int, default=32)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--time-budget", type=float, default=15.0)
        parser.add_argument("--backend", choices=("subprocess", "docker"), default="subprocess")
    for parser in (demo, learn, update, inspect, plan, run):
        parser.add_argument("--output")


def _read(path):
    if path is None:
        return None
    if not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError("a bounded local public JSON file is required")
    return json.loads(path.read_text(encoding="utf-8"))


def _archive(path):
    value = _read(path)
    if value is None or value.get("schema") == "tomolab-knowledge-archive-v1":
        return value
    for key in ("knowledge_archive", "archive"):
        if isinstance(value.get(key), dict):
            return value[key]
    raise ValueError("knowledge archive not found in the supplied JSON")


def dispatch(args, parser, examples):
    from .discovery.knowledge import KnowledgeArchive, validate_provenance
    from .discovery.schema import identifier, integer, validate_spec
    command = args.command
    if command in ("knowledge-learn", "knowledge-update"):
        if args.observations and not args.approve_development_evidence:
            parser.error("independent development evidence requires --approve-development-evidence")
        if command == "knowledge-update":
            archive = KnowledgeArchive.from_snapshot(_archive(args.archive)).fork(args.generation_id)
        else:
            archive = KnowledgeArchive.from_failure_log(_read(args.spec), _read(args.failure_log),
                _read(args.provenance), temporal_contract=_read(args.temporal_contract), public_ir=_read(args.public_ir))
        if args.observations:
            events = _read(args.observations)
            if not isinstance(events, list) or len(events) > 256:
                raise ValueError("at most 256 approved development observations")
            for event in events:
                archive.observe(event, trusted_observation=True)
        result = archive.freeze()
        if args.store:
            if not args.record_id:
                raise ValueError("append-only persistence requires --record-id")
            from .discovery.knowledge_store import KnowledgeStore
            args.store.parent.mkdir(parents=True, exist_ok=True)
            KnowledgeStore(args.store).append(result, record_id=args.record_id)
        return result
    if command == "knowledge-demo":
        from .discovery.knowledge_examples import (build_example_archive, example_ir,
                                                   example_origin, example_spec)
        folder = examples/"knowledge"
        archive, learning = build_example_archive(folder, contradicted=args.case == "contradicted")
        spec = example_spec(("left", "right"), folder=folder)
        target = folder/("clean.py" if args.case == "clean" else "target.py")
        oracle = folder/"target_oracle.py"
        origin = example_origin(folder, target.name, oracle.name, "isqrt-target" if args.case != "clean" else "clean-target")
        ir = example_ir(folder, ("left", "right"))
        if args.case == "no-prior":
            archive = None
    else:
        spec = validate_spec(_read(args.spec))
        archive = _archive(args.archive)
        origin = _read(args.target_provenance)
        if origin is not None:
            origin = validate_provenance(origin)
        ir = _read(args.public_ir)
        temporal = _read(getattr(args, "temporal_contract", None))
        if command == "knowledge-inspect":
            if archive is None:
                from .discovery.temporal import validate_temporal_contract
                return {"schema": "tomolab-knowledge-inspection-v1", "spec": spec,
                        "temporal_contract": None if temporal is None else validate_temporal_contract(temporal, spec),
                        "execution": "NOT_EXECUTED", "gate": "APPLICABILITY_UNKNOWN"}
            value = KnowledgeArchive.from_snapshot(archive)
            return {"schema": "tomolab-knowledge-inspection-v1", "execution": "NOT_EXECUTED",
                    "gate": value.qualify(spec, target_provenance=origin, temporal_contract=temporal, public_ir=ir)}
    integer(args.budget, 1, 4096)
    integer(args.shrink_budget, 0, 4096)
    integer(args.guidance_budget, 0, 2048)
    integer(args.pool_size, 1, 4096)
    integer(args.seed, 0, 2**32-1)
    import math
    if not math.isfinite(args.time_budget) or not 0 < args.time_budget <= 3600:
        raise ValueError("finite cooperative time budget required")
    options = dict(spec=spec, archive=archive, target_provenance=origin, public_ir=ir,
                   budget=args.budget, seed=args.seed, pool_size=args.pool_size, guidance_budget=args.guidance_budget)
    if command == "knowledge-plan":
        from .discovery.knowledge_boundary import KnowledgeBoundary
        if temporal is not None:
            options["temporal_contract"] = temporal
        with KnowledgeBoundary(backend=args.backend) as generator:
            result = generator.request("plan", **options)
            result["information_boundary"] = generator.receipt
        return result
    if command == "knowledge-run":
        if not args.allow_local_execution:
            parser.error("knowledge-run requires --allow-local-execution (trusted host code; no target sandbox)")
        target, oracle = args.path, args.oracle_file
        # Validate the entire configuration and optional dependencies before any
        # user target or Oracle module can execute import-time statements.
        from .discovery.knowledge_engine import KnowledgeEngine
        KnowledgeEngine(**options)
        if target.resolve() == oracle.resolve():
            raise ValueError("separate target and Oracle files required")
        import hypothesis  # noqa: F401
        identifier(args.failure_signature)
        fn_name, ref_name = args.function, args.oracle
    else:
        fn_name, ref_name = "implementation", "reference"
    from .mold.service import _load
    from .discovery.knowledge_service import run_knowledge
    # Bind pinned provenance to the actual reviewed files, not a user-supplied
    # name that could silently point at another implementation.
    target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    oracle_hash = hashlib.sha256(oracle.read_bytes()).hexdigest()
    if origin is not None and (origin.get("implementation_sha256", target_hash) != target_hash
                               or origin.get("oracle_sha256", oracle_hash) != oracle_hash):
        raise ValueError("reviewed target/Oracle provenance differs from actual file bytes")
    fn, imported_target_hash = _load(target, fn_name)
    ref, imported_oracle_hash = _load(oracle, ref_name)
    if target_hash != imported_target_hash or oracle_hash != imported_oracle_hash:
        raise ValueError("reviewed source changed before import")
    result = run_knowledge(fn, ref, shrink_budget=args.shrink_budget, time_budget=args.time_budget,
                          backend=args.backend, trusted_execution=True, failure_signature="directed-width" if command == "knowledge-demo" else args.failure_signature, **options)
    if (hashlib.sha256(target.read_bytes()).hexdigest() != target_hash
            or hashlib.sha256(oracle.read_bytes()).hexdigest() != oracle_hash):
        raise ValueError("reviewed source changed during knowledge execution")
    result.update(target_sha256=target_hash, oracle_sha256=oracle_hash, knowledge_archive=archive)
    if command == "knowledge-demo":
        result["knowledge_learning"] = learning
        result["scope"] = "AUTHORED_FUNCTIONAL_FIXTURE_NOT_REAL_PROJECT_RESEARCH"
    return result
