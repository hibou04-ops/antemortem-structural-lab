"""Command line: inspect without execution; run only when explicitly trusted."""
from __future__ import annotations

import argparse
import hashlib
import json
import sysconfig
import time
from pathlib import Path

from .engine import MODES, run_experiment
from .claim import compile_claim, run_claim, replay_claim
from .mri import inspect_file
from .replay import replay_evidence

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = (ROOT / "examples" if (ROOT / "pyproject.toml").is_file() else
            ROOT / "share" / "antemortem-structural-lab" / "examples"
            if (ROOT / "share" / "antemortem-structural-lab" / "examples").is_dir() else
            Path(sysconfig.get_path("data")) / "share" / "antemortem-structural-lab" / "examples")


def _save(payload: dict, output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output:
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def _add_engine_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=MODES, default="cross")
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--low", type=int, default=-25)
    parser.add_argument("--high", type=int, default=25)
    parser.add_argument("--jev", action="store_true", help="Use live Jev; network, key and possible data charges")
    parser.add_argument("--jev-provider", choices=("auto", "typesafe", "vercel"), default="auto",
                        help="Choose TypeSafe direct or Vercel route; auto prefers TypeSafe")
    parser.add_argument("--output", help="Write JSON evidence (otherwise stdout)")


def main(argv: list[str] | None = None) -> int:
    main_started = time.perf_counter()
    p = argparse.ArgumentParser(prog="tomolab", description="Experimental MRI↔CAST behavioral falsification")
    cmd = p.add_subparsers(dest="command", required=True)
    pi = cmd.add_parser("inspect", help="AST inspection only; never execute source")
    pi.add_argument("path", type=Path)
    pi.add_argument("--function", default="implementation")
    pi.add_argument("--output")
    pd = cmd.add_parser("demo", help="Run a bundled, local, trusted demonstration")
    pd.add_argument("--case", default="nested_equal", choices=[x.stem for x in EXAMPLES.glob("*.py")])
    _add_engine_options(pd)
    pr = cmd.add_parser("run", help="Execute your local Python target (explicit opt-in required)")
    pr.add_argument("path", type=Path)
    pr.add_argument("--function", default="implementation")
    pr.add_argument("--oracle", default="reference")
    pr.add_argument("--oracle-file", type=Path, help="Separate, independently authored reference module")
    pr.add_argument("--allow-local-execution", action="store_true", help="Required: source is trusted, NOT sandboxed")
    _add_engine_options(pr)
    pp = cmd.add_parser("replay", help="Re-execute a stored counterexample on matching source bytes")
    pp.add_argument("evidence", type=Path)
    pp.add_argument("--source", type=Path, help="Override source path after moving files; hash is checked")
    pp.add_argument("--oracle-file", type=Path, help="Override oracle source path; hash is checked")
    pp.add_argument("--allow-local-execution", action="store_true", help="Required: executes source with NO sandbox")
    pp.add_argument("--output")
    pb = cmd.add_parser("bench", help="Synthetic ablation benchmark (NOT evidence of SOTA)")
    pb.add_argument("--budget", type=int, default=12)
    pb.add_argument("--seeds", type=int, default=10)
    pb.add_argument("--output")
    # Phase C: no executable oracle. The claim's restricted relational meaning
    # is checked directly against multiple runs of one trusted function.
    pc = cmd.add_parser("claim-compile", help="Compile a strictly recognized claim; no code executes")
    pc.add_argument("--claim", required=True, help="One exact supported sentence; ambiguous claims are rejected")
    pc.add_argument("--output")
    pcr = cmd.add_parser("claim-run", help="Find a relational counterexample WITHOUT a reference function")
    pcr.add_argument("path", type=Path)
    pcr.add_argument("--function", default="implementation")
    pcr.add_argument("--claim", required=True)
    pcr.add_argument("--mode", choices=MODES, default="cross")
    pcr.add_argument("--budget", type=int, default=12, help="Maximum ACTUAL target calls (3 per relation)")
    pcr.add_argument("--seed", type=int, default=7)
    pcr.add_argument("--low", type=int, default=-25)
    pcr.add_argument("--high", type=int, default=25)
    pcr.add_argument("--allow-local-execution", action="store_true", help="Required. Target is trusted; NO sandbox")
    pcr.add_argument("--output")
    pcp = cmd.add_parser("claim-replay", help="Re-execute a stored relational witness (source+contract hashes)")
    pcp.add_argument("evidence", type=Path)
    pcp.add_argument("--source", type=Path)
    pcp.add_argument("--allow-local-execution", action="store_true")
    pcp.add_argument("--output")
    pcb = cmd.add_parser("claim-bench", help="Phase C synthetic fixtures; NOT a blind SOTA comparison")
    pcb.add_argument("--budget", type=int, default=12)
    pcb.add_argument("--seeds", type=int, default=30)
    pcb.add_argument("--output")
    pm = cmd.add_parser("mold-demo", help="Learn competing structural constraints from a trusted bundled example")
    pmr = cmd.add_parser("mold-run", help="Learn with trusted target and separate reference; evaluator is NOT sandboxed")
    pmr.add_argument("path", type=Path)
    pmr.add_argument("--oracle-file", type=Path, required=True)
    pmr.add_argument("--spec", type=Path, required=True)
    pmr.add_argument("--function", default="implementation")
    pmr.add_argument("--oracle", default="reference")
    pmr.add_argument("--allow-local-execution", action="store_true")
    pmp = cmd.add_parser("mold-plan", help="Freeze mapped structural probes for a new public contract; no oracle calls")
    pmp.add_argument("--snapshot", type=Path, required=True)
    pmp.add_argument("--spec", type=Path, required=True)
    for mold_parser in (pm, pmr, pmp):
        mold_parser.add_argument("--budget", type=int, default=32)
        mold_parser.add_argument("--seed", type=int, default=7)
        mold_parser.add_argument("--backend", choices=("subprocess", "docker"), default="subprocess")
        mold_parser.add_argument("--solver", choices=("enumeration", "z3"), default="enumeration")
        mold_parser.add_argument("--output")
    pcs = cmd.add_parser("constraints-check", help="Check bounded AST relations without executing source")
    pcs.add_argument("--spec", type=Path, required=True)
    pcs.add_argument("--expression", action="append", required=True)
    pcs.add_argument("--solver", choices=("enumeration", "z3"), default="enumeration")
    pcs.add_argument("--output")
    pbt_demo = cmd.add_parser("pbt-demo", help="Hypothesis generation and shrinking on a trusted bundled example")
    pbt_run = cmd.add_parser("pbt-run", help="Property testing of a trusted target and separate integer Oracle")
    pbt_run.add_argument("path", type=Path)
    pbt_run.add_argument("--oracle-file", type=Path, required=True)
    pbt_run.add_argument("--spec", type=Path, required=True)
    pbt_run.add_argument("--function", default="implementation")
    pbt_run.add_argument("--oracle", default="reference")
    pbt_run.add_argument("--allow-local-execution", action="store_true")
    for parser in (pbt_demo, pbt_run):
        parser.add_argument("--budget", type=int, default=32)
        parser.add_argument("--max-examples", type=int, default=128)
        parser.add_argument("--shrink-budget", type=int, default=128)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--backend", choices=("subprocess", "docker"), default="subprocess")
        parser.add_argument("--solver", choices=("enumeration", "z3"), default="enumeration")
        parser.add_argument("--output")
    discovery_demo = cmd.add_parser("discovery-demo", help="Run the reviewed E5 integrated sequence or state-trace example")
    discovery_demo.add_argument("--case", choices=("sequence", "state"), default="sequence")
    discovery_run = cmd.add_parser("discovery-run", help="Integrated discovery with reviewed target and independent Oracle")
    discovery_run.add_argument("path", type=Path)
    discovery_run.add_argument("--oracle-file", type=Path, required=True)
    discovery_run.add_argument("--function", default="implementation")
    discovery_run.add_argument("--oracle", default="reference")
    discovery_run.add_argument("--allow-local-execution", action="store_true")
    discovery_plan = cmd.add_parser("discovery-plan", help="Freeze structural probes without executing a target or receiving final feedback")
    discovery_plan.add_argument("--snapshot", type=Path, required=True)
    discovery_inspect = cmd.add_parser("discovery-inspect", help="Parse an explicitly public source into typed structural IR; no execution")
    discovery_inspect.add_argument("path", type=Path)
    discovery_inspect.add_argument("--function", default="implementation")
    discovery_inspect.add_argument("--spec", type=Path, required=True)
    discovery_inspect.add_argument("--output")
    for parser in (discovery_run, discovery_plan):
        parser.add_argument("--spec", type=Path, required=True)
        public = parser.add_mutually_exclusive_group(required=True)
        public.add_argument("--public-source", type=Path, help="Explicitly approved source for Generator IR; never a private final target")
        public.add_argument("--public-ir", type=Path)
        parser.add_argument("--public-function", default="implementation")
    for parser in (discovery_demo, discovery_run, discovery_plan):
        parser.add_argument("--budget", type=int, default=32)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--pool-size", type=int, default=128)
        parser.add_argument("--backend", choices=("subprocess", "docker"), default="subprocess")
        parser.add_argument("--solver", choices=("enumeration", "z3"), default="enumeration")
        parser.add_argument("--output")
    for parser in (discovery_demo, discovery_run):
        parser.add_argument("--shrink-budget", type=int, default=64)
        parser.add_argument("--time-budget", type=float, default=10.0)
        parser.add_argument("--strategy", choices=("integrated", "hypothesis"), default="integrated")
        parser.add_argument("--expected-exception", action="append", default=[],
                            choices=("ValueError","TypeError","KeyError","IndexError","ZeroDivisionError","OverflowError"),
                            help="Explicitly approved Oracle exception category; all others propagate")
    discovery_plan.add_argument("--target-evidence", type=Path, help="Approved development counterevidence only; never final labels")
    stateful_demo = cmd.add_parser("stateful-demo", help="E6 native Hypothesis and learned temporal constraints on reviewed state machines")
    stateful_demo.add_argument("--case", choices=("stack","renamed","clean"), default="stack")
    stateful_run = cmd.add_parser("stateful-run", help="E6 discovery on explicitly trusted subject and independent model factories")
    stateful_run.add_argument("path", type=Path)
    stateful_run.add_argument("--oracle-file", type=Path, required=True)
    stateful_run.add_argument("--factory", default="make_subject")
    stateful_run.add_argument("--oracle-factory", default="make_subject")
    stateful_run.add_argument("--allow-local-execution", action="store_true")
    stateful_plan = cmd.add_parser("stateful-plan", help="Transfer frozen state relations using public contracts only")
    stateful_plan.add_argument("--snapshot", type=Path, required=True)
    stateful_plan.add_argument("--target-evidence", type=Path)
    stateful_plan.add_argument("--mapping", type=Path)
    stateful_inspect = cmd.add_parser("stateful-inspect", help="Validate a public finite-state contract without importing target code")
    for parser in (stateful_run,stateful_plan,stateful_inspect):
        parser.add_argument("--contract", type=Path, required=True, help="Public JSON with spec and temporal_contract")
    for parser in (stateful_demo,stateful_run,stateful_plan):
        parser.add_argument("--budget", type=int, default=128)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--pool-size", type=int, default=32)
        parser.add_argument("--backend", choices=("subprocess","docker"), default="subprocess")
        parser.add_argument("--strategy", choices=("integrated","hypothesis"), default="integrated")
        parser.add_argument("--public-ir", type=Path, help="Explicitly approved static IR; never a hidden final source")
    for parser in (stateful_demo,stateful_run):
        parser.add_argument("--shrink-budget", type=int, default=128)
        parser.add_argument("--time-budget", type=float, default=15.0)
        parser.add_argument("--expected-exception", action="append", default=[],
                            choices=("ValueError","TypeError","KeyError","IndexError","ZeroDivisionError","OverflowError"))
    for parser in (stateful_demo,stateful_run,stateful_plan,stateful_inspect):
        parser.add_argument("--output")

    from .knowledge_cli import register as register_knowledge
    register_knowledge(cmd)
    from .e8_cli import register as register_e8
    register_e8(cmd)
    from .e8r1_cli import register as register_e8r1
    register_e8r1(cmd)
    from .e8r2_cli import register as register_e8r2
    register_e8r2(cmd)
    from .e8r3_cli import register as register_e8r3, COMMANDS as R3_COMMANDS
    register_e8r3(cmd)
    from .e8r4_cli import register as register_e8r4, COMMANDS as R4_COMMANDS
    register_e8r4(cmd)
    args = p.parse_args(argv)
    try:
        if args.command in R4_COMMANDS:
            from .e8r4_cli import dispatch
            from .e8r3_cli import save_receipt
            result = dispatch(args, p, EXAMPLES)
            save_receipt(result, args.output, main_started=main_started)
            return 0 if result.get("status", "COMPLETE") == "COMPLETE" else 3
        elif args.command in R3_COMMANDS:
            from .e8r3_cli import dispatch, save_receipt
            result = dispatch(args, p)
            save_receipt(result, args.output, main_started=main_started)
            return 0 if result["status"] == "COMPLETE" else 3
        elif args.command.startswith("numerical-"):
            from .e8r2_cli import dispatch
            try:
                result = dispatch(args, p, EXAMPLES)
            except ModuleNotFoundError as exc:
                p.error(f"R2 수치 실행에는 선택 의존성 [qa]가 필요합니다: {exc}")
            _save(result, args.output)
            if result.get("status") in ("ABORTED_EXECUTION_ERROR", "INCONCLUSIVE", "INCONCLUSIVE_REPLAY_MISMATCH") or result.get("run",{}).get("status") in ("ABORTED_EXECUTION_ERROR", "INCONCLUSIVE_REPLAY_MISMATCH"):
                return 3
        elif args.command.startswith("semantic-"):
            from .e8r1_cli import dispatch
            try:
                result=dispatch(args,p,EXAMPLES)
            except ModuleNotFoundError as exc:
                p.error(f"R1 학습·계획·실행에는 검토된 선택 의존성 [qa]가 필요합니다: {exc}")
            _save(result,args.output)
            if args.command in ("semantic-run","semantic-demo") and (result.get("status")=="ABORTED_EXECUTION_ERROR" or result.get("run",{}).get("status")=="ABORTED_EXECUTION_ERROR"):
                return 3
        elif args.command.startswith(("evidence-", "readiness-")):
            from .e8_cli import dispatch
            result = dispatch(args, p, EXAMPLES)
            _save(result, args.output)
            if args.command == "readiness-check":
                return 0 if result["status"] == "PASS" else 3
        elif args.command.startswith("knowledge-"):
            from .knowledge_cli import dispatch
            _save(dispatch(args, p, EXAMPLES), args.output)
        elif args.command.startswith("stateful-"):
            from .discovery.schema import integer, keys, validate_spec
            from .discovery.temporal import trace_layout, validate_temporal_contract
            if args.command == "stateful-run" and not args.allow_local_execution:
                p.error("stateful-run requires --allow-local-execution (trusted callbacks; host has NO sandbox)")
            folder = EXAMPLES / "temporal"
            bundle_path = folder / ("renamed-contract.json" if args.case == "renamed" else "stack-contract.json") if args.command == "stateful-demo" else args.contract
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            keys(bundle,("spec","temporal_contract"))
            spec = validate_spec(bundle["spec"])
            contract = validate_temporal_contract(bundle["temporal_contract"],spec)
            if args.command == "stateful-inspect":
                _save({"schema":"tomolab-temporal-inspection-v1","spec":spec,"temporal_contract":contract,
                       "execution":"NOT_EXECUTED","scope":"APPROVED_BOUNDED_NUMERIC_STATE_PROJECTIONS"},args.output)
                return 0
            integer(args.budget,1,4096)
            integer(args.seed,0,2**32-1)
            integer(args.pool_size,1,4096)
            ir = json.loads(args.public_ir.read_text(encoding="utf-8")) if args.public_ir else None
            if ir is not None:
                from .discovery.predicates import validate_public_ir
                validate_public_ir(ir,spec)
            if args.command == "stateful-plan":
                from .discovery.temporal_boundary import TemporalBoundary
                source = json.loads(args.snapshot.read_text(encoding="utf-8"))
                source = source.get("snapshot",source)
                options = dict(snapshot=source,spec=spec,temporal_contract=contract,budget=args.budget,
                               seed=args.seed,pool_size=args.pool_size)
                if ir is not None:
                    options["target_ir"] = ir
                if args.target_evidence:
                    options["target_evidence"] = json.loads(args.target_evidence.read_text(encoding="utf-8"))
                if args.mapping:
                    options["mapping"] = json.loads(args.mapping.read_text(encoding="utf-8"))
                with TemporalBoundary(backend=args.backend) as generator:
                    result = generator.request("transfer",**options)
                    result["information_boundary"] = generator.receipt
            else:
                import math
                integer(args.shrink_budget,0,10000)
                if not math.isfinite(args.time_budget) or not 0<args.time_budget<=3600:
                    raise ValueError("stateful time-budget must be finite and in (0,3600]")
                if len(spec["contract"]["invariants"])!=1:
                    raise ValueError("stateful evaluator requires one declared reference-comparison invariant")
                _,_,argument_type = trace_layout(spec)
                if spec["inputs"][0]["type"]["min_size"] != 0 or spec["inputs"][0]["type"]["max_size"] < 1:
                    raise ValueError("native stateful adapter requires min_size=0 and a positive step bound")
                if argument_type["kind"]!="int" or argument_type["max"]-argument_type["min"]>128:
                    raise ValueError("native stateful adapter supports at most 129 bounded integer arguments")
                try:
                    import hypothesis  # noqa: F401
                except ImportError as error:
                    raise ValueError("stateful discovery requires the 'qa' extra") from error
                if args.command == "stateful-demo":
                    target = folder / ({"stack":"stack_target.py","renamed":"renamed_target.py","clean":"clean_target.py"}[args.case])
                    oracle = folder / ("renamed_oracle.py" if args.case=="renamed" else "stack_oracle.py")
                else:
                    target,oracle = args.path,args.oracle_file
                if target.resolve()==oracle.resolve():
                    raise ValueError("stateful discovery requires an independently authored model file")
                from .mold.service import _load
                target_factory,target_hash = _load(target,getattr(args,"factory","make_subject"))
                model_factory,model_hash = _load(oracle,getattr(args,"oracle_factory","make_subject"))
                def action_callback(action):
                    def execute(subject,argument):
                        return subject.step(action,argument)
                    return execute
                operations = {action["name"]:{"arguments":argument_type,"target":action_callback(action["name"]),
                                               "model":action_callback(action["name"])} for action in contract["actions"]}
                from .discovery.temporal_service import run_temporal
                result = run_temporal(target_factory,model_factory,operations,snapshot=lambda subject:subject.snapshot(),
                    spec=spec,temporal_contract=contract,budget=args.budget,shrink_budget=args.shrink_budget,
                    seed=args.seed,pool_size=args.pool_size,time_budget=args.time_budget,strategy=args.strategy,
                    backend=args.backend,public_ir=ir,trusted_execution=True,
                    expected_oracle_exceptions=tuple(getattr(__import__("builtins"),name) for name in args.expected_exception))
                if (hashlib.sha256(target.read_bytes()).hexdigest()!=target_hash or
                        hashlib.sha256(oracle.read_bytes()).hexdigest()!=model_hash):
                    raise ValueError("trusted stateful source changed during execution")
                result.update(target_sha256=target_hash,oracle_sha256=model_hash)
            _save(result,args.output)
        elif args.command.startswith("discovery-"):

            from .discovery.service import prepare_public_contract, run_discovery, plan_discovery
            from .discovery.schema import integer, validate_spec
            from .discovery.predicates import validate_public_ir
            if args.command == "discovery-run" and not args.allow_local_execution:
                p.error("discovery-run requires --allow-local-execution (reviewed code; evaluator has NO sandbox)")
            if args.command == "discovery-inspect":
                spec = json.loads(args.spec.read_text(encoding="utf-8"))
                spec, ir = prepare_public_contract(spec,args.path,function=args.function)
                _save({"spec":spec,"public_ir":ir},args.output)
                return 0
            integer(args.budget,1,4096)
            integer(args.seed,0,2**32-1)
            integer(args.pool_size,1,4096)
            if args.command != "discovery-plan":
                integer(args.shrink_budget,0,10000)
                if not 0 < args.time_budget <= 3600:
                    raise ValueError("time-budget must be in (0,3600]")
            folder = EXAMPLES / "discovery"
            spec_path = folder / f"{args.case}-spec.json" if args.command == "discovery-demo" else args.spec
            spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8")))
            public_source = folder / f"{args.case}_target.py" if args.command == "discovery-demo" else args.public_source
            if public_source is not None:
                spec, ir = prepare_public_contract(spec,public_source,function=getattr(args,"public_function","implementation"))
            else:
                ir = json.loads(args.public_ir.read_text(encoding="utf-8"))
                if spec["contract"]["graph_signature"] == "UNKNOWN":
                    spec["contract"]["graph_signature"] = ir["graph_signature"]
                validate_public_ir(ir,spec)
            options = dict(budget=args.budget,seed=args.seed,pool_size=args.pool_size,solver=args.solver,backend=args.backend)
            if args.command == "discovery-plan":
                snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
                evidence = json.loads(args.target_evidence.read_text(encoding="utf-8")) if args.target_evidence else None
                result = plan_discovery(snapshot,spec,target_ir=ir,target_evidence=evidence,**options)
            else:
                if len(spec["contract"]["invariants"]) != 1:
                    raise ValueError("this reference evaluator requires exactly one declared invariant")
                try:
                    import hypothesis  # noqa: F401
                    if args.solver == "z3":
                        import z3  # noqa: F401
                except ImportError as error:
                    raise ValueError("E5 search requires the 'qa' extra; Z3 also requires 'solver'") from error
                target = folder / f"{args.case}_target.py" if args.command == "discovery-demo" else args.path
                oracle = folder / f"{args.case}_oracle.py" if args.command == "discovery-demo" else args.oracle_file
                if target.resolve() == oracle.resolve():
                    raise ValueError("discovery requires a separately authored Oracle file")
                from .mold.service import _load
                fn, target_hash = _load(target,getattr(args,"function","implementation"))
                ref, oracle_hash = _load(oracle,getattr(args,"oracle","reference"))
                result = run_discovery(fn,ref,spec,public_ir=ir,trusted_execution=True,
                                       shrink_budget=args.shrink_budget,time_budget=args.time_budget,
                                       strategy=args.strategy,
                                       expected_oracle_exceptions=tuple(getattr(__import__("builtins"),name) for name in args.expected_exception),**options)
                if (hashlib.sha256(target.read_bytes()).hexdigest() != target_hash or
                        hashlib.sha256(oracle.read_bytes()).hexdigest() != oracle_hash):
                    raise ValueError("trusted source changed during discovery")
                result.update(target_sha256=target_hash,oracle_sha256=oracle_hash)
            _save(result,args.output)
        elif args.command == "constraints-check":
            from .mold.structural import compile_relation, check_consistency
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
            relations = [compile_relation(expression, spec) for expression in args.expression]
            _save({"relations": relations, **check_consistency(spec, relations, backend=args.solver)}, args.output)
        elif args.command in ("pbt-demo", "pbt-run"):
            from .mold.property_testing import run_properties
            from .mold.schema import validate_spec
            from .mold.service import _load
            if args.command == "pbt-run" and not args.allow_local_execution:
                p.error("pbt-run requires --allow-local-execution (trusted evaluator has NO sandbox)")
            folder = EXAMPLES / "mold"
            target = folder / "target.py" if args.command == "pbt-demo" else args.path
            oracle = folder / "oracle.py" if args.command == "pbt-demo" else args.oracle_file
            spec_path = folder / "spec.json" if args.command == "pbt-demo" else args.spec
            spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8")))
            # Validate controls and dependency availability before target import.
            from .mold.schema import integer
            domain_size = 1
            for var in spec["variables"]:
                domain_size *= var["high"] - var["low"] + 1
            integer(args.budget, 1, min(256, domain_size), "budget")
            integer(args.max_examples, 1, 10000, "max_examples")
            integer(args.shrink_budget, 0, 4225, "shrink_budget")
            integer(args.seed, 0, 2**32 - 1, "seed")
            try:
                import hypothesis  # noqa: F401
            except ImportError as exc:
                raise ValueError("property testing requires the 'qa' package extra") from exc
            if target.resolve() == oracle.resolve():
                raise ValueError("pbt-run requires a separately authored Oracle file")
            fn, target_hash = _load(target, getattr(args, "function", "implementation"))
            ref, oracle_hash = _load(oracle, getattr(args, "oracle", "reference"))
            result = run_properties(fn, ref, spec, budget=args.budget, max_examples=args.max_examples,
                                    shrink_budget=args.shrink_budget, seed=args.seed, backend=args.backend,
                                    solver=args.solver, trusted_execution=True)
            if (hashlib.sha256(target.read_bytes()).hexdigest() != target_hash or
                    hashlib.sha256(oracle.read_bytes()).hexdigest() != oracle_hash):
                raise ValueError("trusted source changed during property testing")
            result.update(target_sha256=target_hash, oracle_sha256=oracle_hash)
            _save(result, args.output)
        elif args.command in ("mold-demo", "mold-run", "mold-plan"):
            from .mold.service import run_mold, plan_mold
            options = dict(budget=args.budget, seed=args.seed, backend=args.backend, solver=args.solver)
            if args.command == "mold-plan":
                snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
                spec = json.loads(args.spec.read_text(encoding="utf-8"))
                result = plan_mold(snapshot, spec, **options)
            else:
                if args.command == "mold-run" and not args.allow_local_execution:
                    p.error("mold-run requires --allow-local-execution (evaluator has NO sandbox)")
                folder = EXAMPLES / "mold"
                spec_path = folder / "spec.json" if args.command == "mold-demo" else args.spec
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                result = run_mold(folder / "target.py" if args.command == "mold-demo" else args.path,
                                  folder / "oracle.py" if args.command == "mold-demo" else args.oracle_file,
                                  spec, function=getattr(args, "function", "implementation"),
                                  oracle_function=getattr(args, "oracle", "reference"),
                                  trusted_execution=True, **options)
            _save(result, args.output)
        elif args.command == "claim-compile":
            contract = compile_claim(args.claim)
            _save({"schema": "tomolab-claim-contract-v1", "claim": contract.as_dict()}, args.output)
        elif args.command == "claim-run":
            if not args.allow_local_execution:
                p.error("claim-run requires --allow-local-execution (NO sandbox)")
            result = run_claim(args.path, args.claim, function=args.function,
                               mode=args.mode, budget=args.budget, seed=args.seed,
                               low=args.low, high=args.high, trusted_execution=True)
            _save(result, args.output)
        elif args.command == "claim-replay":
            if not args.allow_local_execution:
                p.error("claim-replay requires --allow-local-execution (NO sandbox)")
            result = replay_claim(args.evidence, trusted_execution=True, source_override=args.source)
            _save(result, args.output)
            return 0 if result["status"] == "REPRODUCED" else 3
        elif args.command == "claim-bench":
            if not 1 <= args.seeds <= 200:
                p.error("seeds must be 1–200")
            suite = [
                ("symmetry_bug", "두 정수 입력의 순서를 바꿔도 반환값은 같다", True),
                ("shift_bug", "첫 번째 정수 입력을 1 증가시키면 반환값도 1 증가한다", True),
                ("monotone_bug", "첫 번째 정수 입력을 1 증가시키면 반환값이 감소하지 않는다", True),
                ("sum_clean", "두 정수 입력의 순서를 바꿔도 반환값은 같다", False),
                ("sum_clean", "첫 번째 정수 입력을 1 증가시키면 반환값도 1 증가한다", False),
                ("sum_clean", "첫 번째 정수 입력을 1 증가시키면 반환값이 감소하지 않는다", False),
                ("symmetric_not_sum", "두 정수 입력의 순서를 바꿔도 반환값은 같다", False),
            ]
            modes = ("cast", "mri", "parallel", "cross")
            records = []
            for case, claim, expected_violation in suite:
                for mode in modes:
                    for seed in range(args.seeds):
                        evidence = run_claim(EXAMPLES / "claim_only" / f"{case}.py", claim,
                                             mode=mode, budget=args.budget, seed=seed, trusted_execution=True)
                        records.append({"case": case, "kind": evidence["claim"]["kind"],
                                        "mode": mode, "seed": seed,
                                        "expected_violation": expected_violation,
                                        "refuted": evidence["status"] == "CLAIM_REFUTED",
                                        "target_calls": evidence["target_calls"]})
            summary = []
            for mode in modes:
                rows = [r for r in records if r["mode"] == mode]
                bugs = [r for r in rows if r["expected_violation"]]
                clean = [r for r in rows if not r["expected_violation"]]
                summary.append({"mode": mode, "bug_trials": len(bugs),
                                "refuted": sum(r["refuted"] for r in bugs),
                                "missed": sum(not r["refuted"] for r in bugs),
                                "clean_trials": len(clean),
                                "false_refutations": sum(r["refuted"] for r in clean),
                                "mean_target_calls_bug_trials": round(sum(r["target_calls"] for r in bugs)/len(bugs), 3)})
            _save({"schema": "tomolab-claim-synthetic-benchmark-v1", "budget_target_calls": args.budget,
                   "seeds": args.seeds, "summary": summary, "records": records,
                   "warning": "Nonblind toy fixtures chosen for supported guard grammar; no known SOTA advantage. Only exact template claims; CrossHair baseline takes SAME contracts."}, args.output)
        elif args.command == "inspect":
            _save(inspect_file(args.path, args.function).as_dict(), args.output)
        elif args.command in ("run", "demo"):
            target = (EXAMPLES / f"{args.case}.py") if args.command == "demo" else args.path
            if args.command == "run" and not args.allow_local_execution:
                p.error("run requires --allow-local-execution (executes Python; NO sandbox)")
            result = run_experiment(
                target, function=getattr(args, "function", "implementation"),
                oracle_function=getattr(args, "oracle", "reference"),
                oracle_path=getattr(args, "oracle_file", None),
                mode=args.mode, budget=args.budget, seed=args.seed,
                low=args.low, high=args.high, trusted_execution=True, use_jev=args.jev,
                jev_provider=args.jev_provider,
            )
            _save(result.as_dict(), args.output)
        elif args.command == "replay":
            if not args.allow_local_execution:
                p.error("replay requires --allow-local-execution")
            replay = replay_evidence(args.evidence, trusted_execution=True,
                                     source_override=args.source, oracle_override=args.oracle_file)
            _save(replay, args.output)
            return 0 if replay["status"] == "REPRODUCED" else 3
        elif args.command == "bench":
            if not 1 <= args.seeds <= 200:
                p.error("seeds must be 1–200")
            modes = ["cast", "mri", "parallel", "cross"]
            case_names = ["nested_equal", "nested_ge_le", "nested_lt_eq", "correct"]
            records = []
            for name in case_names:
                for mode in modes:
                    for seed in range(args.seeds):
                        result = run_experiment(EXAMPLES / f"{name}.py", mode=mode,
                                                budget=args.budget, seed=seed, trusted_execution=True)
                        records.append({"case": name, "mode": mode, "seed": seed,
                                        "detected": result.status == "ORACLE_CONTRADICTION_FOUND",
                                        "calls": len(result.observations)})
            summary = []
            for mode in modes:
                bugged = [r for r in records if r["mode"] == mode and r["case"] != "correct"]
                clean = [r for r in records if r["mode"] == mode and r["case"] == "correct"]
                summary.append({"mode": mode, "bug_cases": len(bugged),
                                "detected": sum(x["detected"] for x in bugged),
                                "missed": sum(not x["detected"] for x in bugged),
                                "clean_cases": len(clean),
                                "clean_false_alerts": sum(x["detected"] for x in clean),
                                "avg_calls_to_stop": round(sum(x["calls"] for x in bugged) / len(bugged), 3)})
            _save({"schema": "tomolab-synthetic-benchmark-v1", "budget": args.budget,
                   "seeds": args.seeds, "case_names": case_names,
                   "warning": "Fixtures share the same narrow nested-if grammar as the cross-modal policy. Not a real-world or SOTA comparison.",
                   "summary": summary, "records": records}, args.output)
    except (OSError, ValueError, TypeError, PermissionError) as exc:
        p.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
