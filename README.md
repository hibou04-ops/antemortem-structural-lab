# Antemortem Structural Lab

An experimental Python project for examining the gap between what code appears to do and what it actually does.

[한국어 README](README.ko.md) | [Changelog](CHANGELOG.md) | [Phase C0 details](PHASE_C_README_KO.md)

## The idea

I first pictured an ant nest revealed by a cast: a hidden network becomes visible through the shape left behind. That led me to a question about code. If you cannot see the whole shape from the outside, can you learn something useful by applying carefully chosen inputs and looking at what comes back?

For code, there is another view available: the structure of the program itself. I wanted to put those two views side by side and see whether each one could help the other find what it had missed.

That became Structural Lab. MRI borrows the idea of looking inside: it is the working name for reading a program's structure. CAST is the name for probing its behavior through execution. The current implementation is small, but it is enough to test parts of that idea instead of leaving it as a diagram.

Static analysis, feedback-guided testing, and symbolic execution already have long histories. What interested me was the handoff between the two views: what one misses, what the other observes, and whether that leads to a useful next test.

## What works today

At v0.2.0, the lab can inspect a limited set of Python conditions, execute trusted example functions, use observed branch behavior to propose another input, and save a counterexample for replay.

It also has an early claim-checking path. Instead of requiring a second function as the correct answer, this path checks a relationship that the target function is supposed to satisfy. For example, if swapping two integer inputs should not change the result, it looks for inputs where the outputs differ.

The important distinction is that no reference function is needed, but a defined relation still is. At present, six recognized sentences in English and Korean map to three fixed relations. The project does not understand arbitrary natural-language requirements.

## Try it

Requires Python 3.11 or newer. The core runtime uses the standard library. These examples use only the files included in this repository.

```bash
git clone https://github.com/hibou04-ops/antemortem-structural-lab.git
cd antemortem-structural-lab
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```

First, inspect the contract without running the target function:

```bash
python -m tomolab claim-compile --claim "Swapping the two integer inputs does not change the result"
```

Then try the same claim against a deliberately flawed example:

```bash
python -m tomolab claim-run examples/claim_only/symmetry_bug.py --claim "Swapping the two integer inputs does not change the result" --mode cross --budget 12 --allow-local-execution --output results/symmetry.json
```

Replay the saved counterexample:

```bash
python -m tomolab claim-replay results/symmetry.json --allow-local-execution
```

The example violates the encoded symmetry relation at two inputs: (17, -3) returns 15, while (-3, 17) returns 14. The replay command checks whether the recorded violation still occurs against matching source and contract data.

For the earlier branch-feedback experiment, run:

```bash
python -m tomolab demo --mode cross --budget 12
```

On Windows PowerShell, each command above can be pasted as a single line.

## Current boundaries

The claim checker works with two positional integer inputs, integer results, deterministic and side-effect-free target functions, and a declared integer domain. The default domain is -25 to 25. Unsupported claims are rejected rather than guessed.

A found counterexample challenges the encoded relation under the stated assumptions. It does not automatically disprove every interpretation of the original requirement. An unfound counterexample is reported as `NOT_REFUTED_WITHIN_BUDGET`, not as proof of correctness.

The included synthetic benchmarks are designed around the branch patterns this prototype handles. They are useful for checking that the feedback loop works, not for claiming an advantage on real projects. CrossHair also finds all three supplied claim violations in the current comparison. No superiority over CrossHair, Hypothesis, or other established tools has been shown.

The earlier branch-feedback experiment has an optional Jev adapter for selecting probes. Phase C0 uses a deterministic policy and does not call Jev. The adapter is not a truth oracle, and its contribution to test effectiveness has not yet been established. Jev is not required for the examples above.

## Safety before running code

`claim-run`, `claim-replay`, and the older execution commands import and execute Python with your local user privileges. The execution flag confirms that you chose to run the code. It does not create a sandbox.

Use targets you wrote or have reviewed and trust. Do not run unknown or hostile code through this tool. Saved evidence can include local paths and test inputs, so review it before sharing. Keep API keys in environment variables and out of Git history.

See [Security](SECURITY.md) for the current security model.

## Where the project goes next

The next research question is harder than finding a failing input. If a claim is written in natural language, how do we know the relation selected for testing preserves what that claim actually means?

That is Phase C1: Claim-to-Obligation Semantic Fidelity. It needs an independent evaluation set and explicit treatment of assumptions, missing conditions, and unknown cases before a more general claim compiler would be credible. C1 is not implemented in v0.2.0.

## Development history

The experiments were first kept as separate archived snapshots, then imported into a Git repository in order. The public commit timestamps show when the snapshots were imported, not when each experiment was originally conceived.

The unpublished v0.2.0 tag was finalized after the bilingual documentation and release checks. The original tag and commit hashes are recorded in [the import notice](PUBLIC_IMPORT_NOTICE.md). The v0.1.1 package-version correction remains a separate commit in the history.

| Version | What changed |
| --- | --- |
| [v0.1.0](docs/releases/v0.1.0.md) | Initial MRI and CAST branch-feedback experiment with a reference function |
| [v0.1.1](docs/releases/v0.1.1.md) | Optional TypeSafe Jev connection and provider handling |
| [v0.2.0](docs/releases/v0.2.0.md) | Early claim-to-witness checks without an executable reference function |

This is a separate experimental project from [antemortem-cli](https://github.com/hibou04-ops/antemortem-cli). The source, examples, and tests are public; private research notes and credentials are not part of the repository.

## License

Apache License 2.0. See [LICENSE](LICENSE).
