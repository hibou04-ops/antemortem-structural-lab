# First-publication validation

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
