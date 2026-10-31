# Antemortem Structural Lab

An experimental Python testing tool for **your reviewed functions, an explicit input contract, and a reference Oracle**. Generate inputs with Hypothesis, record reproducible disagreements, shrink counterexamples within a budget, and replay the evidence. It does not supply a universal Oracle or prove program correctness.

[한국어 안내](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/README.ko.md) · [0.8 migration](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/MIGRATION_0_8.md) · [Changelog](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/CHANGELOG.md)

## Install and try an example

Python 3.11+ is required. The **0.8.0a1 prerelease** online commands need the `qa` extra.

```bash
python -m pip install "antemortem-structural-lab[qa]==0.8.0a1"
python -m tomolab --help
python -m tomolab online-demo --workspace demo-work --usage-ledger demo-usage.jsonl --allow-local-execution --budget 24 --shrink-budget 6 --output demo-result.json
```

The default is **A: native Hypothesis generation with the shared observation, confirmation, and shrinking path**. This authored demo deliberately returns the wrong answer at zero. A/B demos execute the Target and Oracle with **no Source collection or learning**. Use new workspace, ledger, and output paths; existing receipts are preserved.

The distribution is `antemortem-structural-lab`; the import and CLI are `tomolab`. `python -m tomolab` and `tomolab` expose the same CLI. The optional `solver`, `analysis`, and `corr` extras serve other integrations and are not needed for this example.

The validated CI scope is Windows and Linux on Python 3.11–3.13; macOS and other Python versions are outside that validation. `solver` installs Z3 for supported bounded constraint checks, `analysis` adds the optional CrossHair comparison integration, and `corr` installs the declared SciPy/NumPy versions on Python 3.12+ for the separate correlation adapters. None supplies a universal Oracle.

## Check a function and replay the evidence

Copy the bundled example into a new directory, then replace it with your own reviewed synchronous function and independent reference model. Each callable receives **one JSON-compatible value**. This example's contract is an integer from −8 through 8; its intentional error at zero is a functional fixture, not a discovered project defect.

`target.py`:

```python
"""Authored demonstration: deliberately wrong at zero; not a real project defect."""


def implementation(point: int) -> int:
    if point == 0:
        return point + 1
    return point
```

`oracle.py`:

```python
"""Explicit deterministic identity contract for the authored demonstration."""


def reference(point: int) -> int:
    return point
```

`contract.json`:

```json
{"kind":"int","low":-8,"high":8}
```

```bash
python -c "from pathlib import Path; from shutil import copytree; from tomolab.cli import EXAMPLES; copytree(EXAMPLES / 'product', Path('my-check'))"
python -m tomolab online-run my-check/target.py --oracle-file my-check/oracle.py --contract my-check/contract.json --usage-ledger my-check/usage.jsonl --allow-local-execution --budget 24 --shrink-budget 6 --output my-check/run.json
python -m tomolab online-replay my-check/run.json --source my-check/target.py --oracle-file my-check/oracle.py --contract my-check/contract.json --allow-local-execution --output my-check/replay.json
```

The default function names are `implementation` and `reference`; `online-run --function` and `--oracle` select other names. New receipts bind the reviewed files and contract. Replay checks that binding and re-executes stored evidence; it is not a new search. Local receipts may contain inputs, outputs, and paths: review them before sharing.

Aliases such as `implementation = actual_function` are supported. New receipts record the selected export name, while the usage ledger keeps the callable's own identity. Replay must use the same selected names; unchanged file hashes and the binding digest remain required. The binding format stays `tomolab-online-replay-binding-v1`. Older receipts that stored the callable's own name remain readable: use that recorded name with `online-replay --function` (and `--oracle` for an Oracle alias). Changing names in a receipt or bypassing its checks is not a compatibility path.

An Oracle is **your explicit expected-behavior model**. An incorrect Oracle can create false disagreement reports. Preserve the specification, numeric tolerance, expected exceptions, and state-reset policy; do not change them just to obtain a passing result.

### Adapting a function with several arguments

For a reviewed `legacy(left, right)` in an importable module, write a one-argument wrapper in `target.py`:

```python
from your_package import legacy


def implementation(point):
    return legacy(point[0], point[1])
```

Use a fixed-length input contract:

```json
{"kind":"sequence_int","low":-8,"high":8,"min_size":2,"max_size":2}
```

Write a separate `reference(point)` from the real specification. This wrapper only maps two arguments; it does not derive an Oracle or establish that the legacy function is correct.

## Contracts and result meanings

| Input kind | Bounded input shape |
|---|---|
| `int`, `float` | Finite values within declared numeric limits |
| `sequence_int`, `sequence_float` | JSON lists of the corresponding numbers |
| `text` | Strings from a declared alphabet |
| `mapping` | String keys and integer values |
| `state_trace` | Full lists of `{ "op": ..., "value": ... }` actions |
| `graph` | `{ "n": ..., "edges": [[from, to], ...] }` |

Unsupported shapes and preconditions are rejected. Arbitrary nested objects, asynchronous functions, hidden persistent state, and unrestricted Python semantics are outside this contract. Use pure functions or a reviewed adapter that resets state for every full input trace.

Read `run.status`, `run.outcome`, error counters, and confirmation/shrinking records together.

| Result | Meaning |
|---|---|
| `CONFIRMED_FAILURE` | A recorded Target/Oracle disagreement was confirmed by three matching executions. Its significance depends on the Oracle and contract. |
| `NO_CONFIRMED_FAILURE_WITHIN_BUDGET` | This run found no confirmed disagreement within its budget. **It is not a correctness proof.** |
| `INCONCLUSIVE` | Limits, boundary failures, unknown results, or execution/Oracle errors prevent a clean conclusion. |
| Replay `REPRODUCED` / `NOT_REPRODUCED` / `NO_CONFIRMED_FAILURE` | Existing evidence reproduced, differed, or contained no confirmed failure to replay. |

`COMPLETE` means the run completed, not that the Target is correct. Shrinking produces a budget-bounded reduction, not a global minimality proof. Replay mismatches remain inconclusive. Use `online-run --help` and `online-replay --help` for the current arguments.

### Numeric tolerance preserves exact zero

For two finite nonzero float outputs of the same type, `comparison.absolute` and `comparison.relative` are the `abs_tol` and `rel_tol` arguments of `math.isclose`: `abs(a-b) <= max(relative * max(abs(a), abs(b)), absolute)`. Both default to zero. If either float is zero, exact equality takes priority regardless of those tolerances; `-0.0` and `0.0` compare equal. Different output types still differ, and the same rules apply recursively to supported output containers.

For example, `{"absolute":1e-6,"relative":0.0}` accepts `1.0` versus `1.000000001`, but rejects `0.0` versus `1e-9`. With `{"absolute":0.0,"relative":1e-6}`, `100.0` versus `100.00001` is accepted. This is the existing exact-zero contract, so a positive absolute tolerance does not extend to comparisons involving zero. This patch changes its documentation, not its meaning or past research judgments.

### Exceptions belong to the comparison contract

An ordinary Oracle exception whose fully qualified type is absent from `comparison.expected_exceptions` is `ORACLE_ERROR`, not a confirmed Target defect. For an expected `ValueError`, add this comparison object to the input contract only when the specification permits it:

```json
{"expected_exceptions":["builtins.ValueError"],"exception_policy":"match_type"}
```

With that declared policy, Target and Oracle raising the same registered type is `PASS`; exception messages are not compared. If only the Target raises while the Oracle returns, the observation is `FAILURE` and requires review of the user code and contract. Call-time `MemoryError`, `ImportError`, `OSError`, and `RecursionError` are captured as `EXECUTION_ERROR`. Module-import/setup failures can abort before observations exist; neither is evidence of a successfully classified program defect.

## Optional search policies

| Method | Configuration |
|---|---|
| **A — default** | Native Hypothesis with shared observation, confirmation, and shrinking |
| B | The native base plus the common online edit policy |
| C | B plus explicitly supplied Source input replay and ordinary transformations |
| **D — experimental opt-in** | C plus a frozen Source-learned selection/applicability policy |

Choose B/C/D with `--method`. C accepts an input-only `--replays` JSON list. D also requires `--mold` and its independently expected `--expected-digest`; `online-learn` prepares a Mold from reviewed Source observations. Explicit C/D demos use the older Source preparation path and report its cost. D is not a proven improvement. Without an applicable rule its common fallback matches C; corrupt artifacts are errors.

MRI code inspection, CAST observations, Claim-to-Witness checks, Mold/version-space engines, and earlier numerical/stateful commands remain available through `--help`. Their narrower contracts are documented separately; the online interface is not a general program verifier.

## Recorded research and limits

The frozen E9-R1 historical study used three projects, two Source defects, six Target defects, six fixed-revision controls, and 384 registered runs. In implementation transfer, **A/B/C/D each rediscovered five of six known historical defects**. D had no detection or first-confirmation query gain over C. In eligible empty-input leave-one-mechanism-out runs, D detected 0/6 at both budgets while actually using learned rules. C detected 4/6 at budget 24 and 6/6 at budget 48; A/B detected 6/6 at both. C also performed worse than A/B at the smaller budget.

These bounded historical rediscoveries include negative transfer. They do not establish universal superiority, new defects in current upstream releases, independent corroboration, or external generalization. Publishing the tool does not change those research conclusions or grant final-evaluation readiness.

[Historical report and costs](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_REPORT_KO.md) · [Full measurements](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_RESULTS.json) · [Earlier authored E9 report](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/ONLINE_REPORT_KO.md) · [Earlier numerical results](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/E8_R2_REPORT.md)

## Execution and licensing

`online-run`, `online-demo`, and `online-replay` import and execute trusted local Python. `--allow-local-execution` is consent, **not an OS sandbox**. The separate Generator process limits information flow; it does not make hostile code safe. Hanging calls and uncontrolled side effects are outside the cooperative pure-function contract. Reviewed external historical capsules have a separate fail-closed, inspected OCI/Docker execution gate; a local opt-in flag does not bypass it.

Project code is Apache-2.0. Historical extracts retain their original MIT/BSD licenses; optional dependencies retain their own licenses. Private research archives, raw evaluation data, credentials, and personal storage are excluded from public package assets.

## Troubleshooting

- **Missing Hypothesis / `qa`:** install it into the interpreter running the command: `python -m pip install "antemortem-structural-lab[qa]==0.8.0a1"`.
- **Existing workspace or output rejected:** choose a new run path and preserve the previous receipts. The examples intentionally do not overwrite them.
- **Unsupported signature:** provide one synchronous positional JSON argument; adapt multi-argument functions explicitly as above. Async/generator functions and arbitrary callable objects are not accepted by this file CLI.
- **Unexpected failure or `ORACLE_ERROR`:** review the independent reference, domain, expected exceptions, and numeric comparison before treating a mismatch as a bug. Inspect error and UNKNOWN counters rather than interpreting a budget miss as a pass.

## Contributing

From a source checkout in a development environment:

```bash
python -m pip install -e ".[qa,solver,analysis]" pytest build twine
python -m pytest -q
python -m build
python -m twine check dist/*
python scripts/check-public-scope.py
```

The public-scope check runs after building and checks source and distribution contents. Historical evaluation cohorts and external reviewed capsules are not ordinary local development tests; follow their existing execution and reuse boundaries.

[Security scope](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/SECURITY.md) · [Third-party notices](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/THIRD_PARTY_NOTICES.md) · [Historical execution boundary](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_USAGE_KO.md) · [Contributing](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/CONTRIBUTING.md)
