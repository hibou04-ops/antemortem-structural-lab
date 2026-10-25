# Antemortem Structural Lab

**Experimental Python verification research: static program-shape probes + dynamic branch feedback + narrow claim-to-witness falsification.**

This is a **public research prototype**, not a production security scanner, an AI safety certification tool, or a general-purpose natural-language verifier. It is independent from [`antemortem-cli`](https://github.com/hibou04-ops/antemortem-cli).

> Status: **v0.2.0 — Phase C0**. Released as an evolving series of auditable experiments; **no performance superiority over CrossHair, Hypothesis, or other established tools has been demonstrated**.

## What it actually does

| Component | Implemented | Not yet demonstrated |
| --- | --- | --- |
| MRI | Reads limited two-integer Python AST comparisons and nested `if` structure, proposes inputs | General symbolic execution, program proof, comprehensive dataflow analysis |
| CAST | Executes explicitly trusted Python functions and observes traces and outputs | Safe sandbox for untrusted code, complete coverage |
| Cross-modal feedback | Generates a follow-up test for an unentered nested true branch | General discrepancy optimization, information-theoretic optimality |
| Phase C0 | Compiles **six exact English/Korean claim templates** into three metamorphic relations, finds and replays counterexamples without a reference function | Open-ended NLP, fidelity between arbitrary prose and formal obligation |
| Jev | Optional TypeSafe or Vercel choice adapter; offline mocked tests | Demonstrated uplift versus deterministic selection; independent truth assessment |

## Install & run

Requires Python **3.11+**. The core runtime uses the Python standard library. For tests install `pytest` (CrossHair is an **optional competitor**, not required by core runtime).

```bash
python -m pip install -e .
python -m pip install pytest
python -m pytest -q

# See exactly which natural-language claim formats are recognized
python -m tomolab claim-compile --claim '두 정수 입력의 순서를 바꿔도 반환값은 같다'

# Execute only code you wrote or trust — this is NOT sandboxed
python -m tomolab claim-run examples/claim_only/symmetry_bug.py \
  --claim '두 정수 입력의 순서를 바꿔도 반환값은 같다' \
  --mode cross --budget 12 --allow-local-execution \
  --output results/symmetry.json
python -m tomolab claim-replay results/symmetry.json --allow-local-execution

# Earlier reference-function comparison path
python -m tomolab demo --mode cross --budget 12
python -m tomolab bench --budget 12 --seeds 30
```

Windows PowerShell users can run the `python -m ...` commands as one line, or use PowerShell's backtick for line continuation.

**Safety:** `claim-run`, `claim-replay`, `run`, `replay`, and similar dynamic experiments **import and execute Python code with your user's privileges**. The `--allow-local-execution` flag is acknowledgement, **not isolation**. Do not point this at arbitrary downloaded code, malicious repositories, or unknown packages. No OS sandbox or reliable execution timeout is built in. Output JSON can contain absolute paths and probe values: **keep it private unless reviewed**. `results/` is ignored from Git.

## Phase C0 — scope, results and comparison

Recognized relations for *exact supported sentences* only:

- **Symmetry:** `f(x, y) == f(y, x)`
- **Unit increment:** `f(x, y) == f(x-1, y) + 1`
- **Monotonicity:** `f(x, y) >= f(x-1, y)`

Assumptions: two positional integer arguments; integer-valued deterministic and side-effect-free functions; declared finite integer domain (default `[-25,25]`). An observed violation refutes the **encoded relation under those conditions**, not necessarily the original free-form natural-language requirement. A clean bounded exploration is `NOT_REFUTED_WITHIN_BUDGET`, **not VERIFIED**.

The shipped toy suite has 3 bug types, 4 clean relation controls, and 30 random seeds: `cross` finds 90/90 toy bug trials while `cast` finds 3/90, `mri` 0/90, and `parallel` 0/90. These **are NOT 90 independent bugs**, and these deliberately nonblind fixtures fit the feedback policy. In the separate pre-C0 toy benchmark, `cross` found 90/90, while `cast` found 13/90, `mri` 11/90 and `parallel` 11/90. CrossHair 0.0.112 also found all three supplied C0 property violations; this project has **no proven real-world or SOTA advantage**.

See [Phase C details](PHASE_C_README_KO.md), [changelog](CHANGELOG.md) and the [release notes](docs/releases/).

## Research question: Claim-to-Obligation Semantic Fidelity (C1)

The next proposed milestone is assessing whether an automatically generated obligation `O` is logically appropriate for original claim `C`, under assumptions `A`. The distinction between `A ∧ C → O` (necessary condition useful for refutation) and `A ∧ O → C` (sufficient condition, if truly proven) is essential. Unverified relations remain **UNKNOWN**. C1 implementation has **not begun** in v0.2.0.

## Jev adapter

With a separately obtained API key, the optional Jev adapter can select bounded candidate probes. **The adapter is not used for any truth verdict.** TypeSafe and Vercel keys use different backends and must not be interchanged. Do not paste credentials into issues, screenshots, files, or commits. The included `scripts/connect-typesafe-jev.ps1` performs an optional billable smoke request; review it before running.

## Version history

Historical experimental snapshots were developed and archived before this Git repository. The public commit sequence imports those verified snapshots in order; **commit timestamps are the date of import, not fabricated historical development timestamps**:

- [`v0.1.0`](docs/releases/v0.1.0.md) — MRI/CAST nested-branch and reference-function demo.
- [`v0.1.1`](docs/releases/v0.1.1.md) — optional direct-TypeSafe Jev choice adapter and failover guards.
- [`v0.2.0`](docs/releases/v0.2.0.md) — restricted oracleless claim-to-metamorphic-witness experiments.

This repository publishes the reusable experimental software only. Private research archives, any personal discussion, third-party tokens, and unrelated projects are not included.

## License

Apache-2.0. See [LICENSE](LICENSE).
