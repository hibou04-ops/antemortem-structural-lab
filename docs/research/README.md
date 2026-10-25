# Phase C1 research artifacts

This branch adds a bounded research experiment beside the v0.2.0 runtime.
It does not implement general natural-language understanding, certify the original
requirements, or publish a new release. `tomolab`, package version and existing
README examples remain at v0.2.0. Research code runs from a source checkout;
the installed runtime wheel continues to contain only `tomolab`.

- [Preregistered scope and measurements](C1_PROTOCOL.md)
- [Prior art, direct overlap and novelty limits](C1_PRIOR_ART.md)
- [Contract, quantifier and evidence API](../../research/c1/CONTRACT.md)
- [Evaluation provenance and baseline definitions](../../research/c1/EVALUATION.md)
- [Independent Z3 cross-check](../../research/c1/SMT_CROSSCHECK.md)
- [Review findings and corrective checks](C1_REVIEW.md)
- [Results and remaining unknowns](C1_RESULTS.md)

## Reproduce from this branch

```bash
python -m venv .venv
# Activate .venv using the command for your operating system.
python -m pip install pytest -r research/c1/requirements-research.txt
python -m pytest -q
python scripts/run-c1-isolated.py --output research/c1/results/reproduced_dev.json
python -m research.c1.smt_crosscheck --output research/c1/results/reproduced_smt.json
```

The separate process uses Python isolated mode, an environment allowlist and a
timeout. It is not an OS security sandbox and must not execute hostile Python.
Docker was installed but its daemon was unavailable in the local run. C1 itself
only interprets trusted bounded JSON expressions: no target imports, eval/exec,
provider API calls or Jev. Existing runtime tests execute only their reviewed
fixtures. CI also runs the C1 checks on Ubuntu and Windows.

The private unused archive is deliberately absent. Its public commitment is an
integrity record with a private nonce, not encryption or a claim that unseen
evaluation has passed. Never replace the frozen gold or candidates to improve a
score. Semantic JSON hashes in the results are stable across Git newline changes;
generation receipts also retain original raw-byte hashes where available.

The source-distribution manifest includes public `research` files so the new
research tests do not arrive without their modules and JSON fixtures. This is the
only change to an existing base file; it changes no released artifact or runtime.
