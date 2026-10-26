# Release validation

## v0.3.0a1 — E3 integration

This section separates implementation, bounded research performance, packaging and public-release status. Checks below were executed on Windows with Python 3.12.10 on 2026-10-27 KST. A passing unit suite alone is not a generalization result.

| Check | Observed result |
| --- | --- |
| Source tests, including existing functionality | `python -m pytest -q`: 76 passed, no failures or skips in the reviewed environment |
| Distribution build | Wheel and sdist for `0.3.0a1` built successfully |
| Fresh wheel environment | Dependency check, packaged demo, claim compilation/search/replay, Mold imports/demo and frozen mapped plan passed outside the source checkout |
| README runtime examples | All 14 literal CLI commands from the Korean and English READMEs exited successfully in separate public-source copies; expected output states verified |
| Documentation links | Final nine-document audit checked 47 relative-link occurrences with none missing |
| Independent E3 evaluation | 7,040 candidate Oracle calls, all 5,120 final candidates frozen before evaluation, no final feedback |
| Independent ledger review | A second agent recomputed 7,040 rows from literal target formulas and records without importing the target or engine; all matched |
| Freeze preservation | All 10 frozen engine/spec files and all three benchmark source commitments unchanged after evaluation |
| PR CI | [Run 40355976452](https://github.com/hibou04-ops/antemortem-structural-lab/actions/runs/40355976452): all seven jobs passed; Ubuntu and Windows with Python 3.11/3.12/3.13 exercised source tests, builds, metadata/content checks and clean wheel installation |
| Docker access controls | Same run's generator-isolation job passed: host sentinel unreadable, public code not writable, external connection unavailable, UID 65534, private host environment absent; 24 end-to-end development calls completed |
| Final main and published assets | The update script requires successful final-main CI and matching source HEAD before tagging; validates draft asset sizes and SHA-256 before publication. Final commit/tag runs are available in [Actions](https://github.com/hibou04-ops/antemortem-structural-lab/actions), and public assets in [v0.3.0a1](https://github.com/hibou04-ops/antemortem-structural-lab/releases/tag/v0.3.0a1) |

The new checks cover competing hypotheses and refutations, active-query and diversity behavior, justified and rejected transfer, frozen-state protection, JSON process communication, existing CLI compatibility and installed-wheel execution. The optional Docker boundary is evaluated separately from the default `LOGICAL_ISOLATION_ONLY` subprocess path. Targets and Oracles remain trusted host code.

E1 and E2 remain `E1_EXECUTED_NO_IMPROVEMENT` and `E2_EXECUTED_NO_IMPROVEMENT`. E2 used 26,880 candidate Oracle calls and produced A/B/C/D discovery sums of 76/75/72/76, with 16 distinct injected task sites per arm across seeds. D and A had identical final candidate and Oracle records; no new portable constraint was learned. Those consumed data are not fresh E3 evaluation data.

E3's final comparison used 2,560 calls per arm across eight tasks and five seeds. Uniform/Mold discovery sums were 30/30, distinct injected task sites 6/6, and failure events 452/1,104. Mean first-discovery calls across all 40 trials per arm were 21.025/17.5, with non-discoveries censored at 65. This descriptive reduction of about 16.8% did not meet the preregistered joint success criterion, which also required at least two additional task-seed discoveries and at least 10% greater discovery breadth. The bounded verdict is `NO_IMPROVEMENT`; broader generalization remains `GENERALIZATION_UNKNOWN`.

The applicability gate allowed 35 Mold task-seed probes and returned `UNKNOWN` for five contract mismatches. Clean controls produced no false failures. These are synthetic paired-transfer integration checks, not newly discovered real-world defects. The local benchmark used `LOGICAL_ISOLATION_ONLY`. See the [E3 evaluation description](E3_EVALUATION.md).

Publication checks inspect explicit staged paths and the contents of the wheel, sdist and release assets. Private evaluation files, raw records, E1/E2 evidence ZIPs, personal paths and credentials are excluded. This is a bounded inspection of reviewed content, not a universal guarantee against sensitive material.

See the [v0.3.0a1 release notes](releases/v0.3.0a1.md) and [security model](../SECURITY.md).

## Historical first-publication validation

Local checks on 2026-10-25 used Windows and Python 3.12.10. This document describes the checked fixtures and distribution boundaries.

| Source snapshot | pytest | Distribution check |
| --- | --- | --- |
| v0.1.0 | 21 passed | Rebuilt wheel installed separately; explicit-path example and replay succeeded |
| v0.1.1 | 29 passed | Rebuilt wheel installed separately; explicit-path example and replay succeeded |
| v0.2.0 | 45 passed | Rebuilt wheel installed separately; bundled demo, claim compilation, counterexample, replay and small claim benchmark succeeded |

The English and Korean README examples were executed, and all 18 relative links resolved in the source tree. Their claim examples encode the same swap relation. Each finds the supplied `(17, -3)` / `(-3, 17)` witness, with results 15 / 14. The language-specific contract hashes differ by design because the source claim text is part of the hash.

CrossHair 0.0.112 found the three supplied relation violations using the assert-based comparison fixture. Its counterexample exit code was 1. This checks those relations and fixtures; no comparative speed, general defect-finding advantage or independent natural-language semantic fidelity is established. No live Jev call was made for these publication checks.

The pre-publication checks found two portability defects. A test read UTF-8 evidence using the Windows locale encoding; it now states UTF-8 explicitly. The old wheel omitted the examples used by bundled commands; v0.2.0 includes and locates them after installation. A fresh-environment wheel check covers this path. Git attributes fix text line endings so source blobs and distribution files can be compared byte for byte across platforms. Probe and claim algorithms were not changed.

The historical v0.1.0 and v0.1.1 tag objects remain unchanged. Their READMEs retain the archived wording, including references to generated results that were intentionally excluded. The release notes explain how to generate fresh evidence and use the historical wheels with explicit example paths.

The complete reachable Git history was inspected for credentials, private research material, personal filesystem paths and accidental output files. The pattern scan and manual review found none in the reviewed public content. This is a bounded inspection, not a guarantee against every possible sensitive string. First-party runtime code uses the Python standard library; see [third-party materials](THIRD_PARTY.md).

The [GitHub Actions matrix](https://github.com/hibou04-ops/antemortem-structural-lab/actions) runs source tests, source/wheel builds and a fresh wheel installation on Ubuntu and Windows with Python 3.11, 3.12 and 3.13. Its actual run status is reported by Actions.
