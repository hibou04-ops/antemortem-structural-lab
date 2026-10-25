"""Command line: inspect without execution; run only when explicitly trusted."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import MODES, run_experiment
from .mri import inspect_file
from .replay import replay_evidence

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


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
    args = p.parse_args(argv)
    try:
        if args.command == "inspect":
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
