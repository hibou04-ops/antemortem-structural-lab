# Phase C1: bounded logical authority protocol

Status: research protocol, frozen before development evaluation. Date: 2026-10-26 (Asia/Seoul).

## Question and scope

Given an explicitly supplied interpretation of a natural-language claim C, premises A,
and candidate obligation O, when may evidence about O become a conclusion about C?
The experiment checks finite open predicates with named variable roles, not arbitrary
natural language or equivalence between already-closed true theorems.

Verified starting point: main and v0.2.0 target commit
`1c020aceec4c745a743cdbb1ca47634bc2b63bad`; existing 45 tests pass in Python 3.12.
Package version, existing runtime, examples, tags, releases and main are protected.
Assumption: curated formal anchors express the intended synthetic claims. That
assumption is NOT proven by the checker. Unknowns include human agreement, real
requirements, correlated model errors, external benchmark performance and Jev gain.

## Competing paths and hypotheses

1. Build a general NL compiler first. Rejected for this phase: no independent
   evidence yet that its obligations preserve the input claims.
2. Check directional authority for bounded supplied interpretations first. Selected:
   it isolates a concrete, falsifiable error mechanism without adding a fuzzer.

H1: directional gates reduce false or unsupported REFUTED conclusions on the same
candidate obligations and evidence. H0: differences arise only from abstention;
report recall and coverage alongside error rates. H2: candidate generation errors
dominate and the gates cannot establish NL fidelity; retain this as a live rival.

## Authority rules

Within exactly the same nonempty support A, O is necessary when A entails C => O;
O is sufficient when A entails O => C. Both directions give bounded predicate
equivalence. Neither direction gives incomparability. Missing interpretation,
unsupported theory/scope, inconsistent premises, invalid witnesses and resource
limits retain distinct UNKNOWN/AMBIGUOUS/OUT_OF_SCOPE reason codes.

For a universal claim, a valid failure of a necessary O can refute C. Exhaustively
passing a sufficient O can establish C only within the declared finite support.
One failing existential witness cannot refute an existential claim. Mixed
quantifiers and longer temporal horizons must abstain unless separately supported.
No result proves that the formal anchor captures the original natural language.

## Independence and data gates

Separate implementation, gold authoring and candidate generation roles. Gold must
be justified by an independent set/predicate oracle rather than the production
checker. Record that all roles use the same model family and lack human semantic
adjudication. Freeze development gold and holdout commitments before candidate
generation. The private unused holdout stays outside the repository and is not
opened or scored in this run. Public development cases are not an unbiased test.

LLM direct and self-review are distinct frozen artifacts, with prompts, model role,
wall time and missing-cost fields. No invented API experiment or invented price.
C0 uses the actual exact-sentence compiler and reports unsupported coverage.
The causal gate ablation shares candidates, evidence and reference answers.

## Measurements and acceptance

Report numerators and denominators separately for: wrong REFUTED conclusions
(C is true throughout the finite support), unsupported REFUTED evidence/authority,
precision of REFUTED declarations, counterexample recall, relation accuracy,
UNKNOWN precision/recall and coverage. Include paired case outcomes and examples.
Do not conflate a coincidentally false C with an authorized submitted witness.
Report generation and checking times separately; tokens and monetary cost are
UNKNOWN if the execution surface does not expose them.

Initial success requires zero wrong/unsupported gate REFUTED on development data,
a visible reduction versus ungated promotion, and retention of at least one real
valid counterexample. Failure of any condition is reported rather than patched
away by relabeling data. Scores establish only this synthetic bounded mechanism;
external superiority and general semantic correctness remain NOT ESTABLISHED.

## Safety and remaining experiments

Use trusted JSON fixtures and an allowlisted, typed expression interpreter only.
No eval/exec, target imports, arbitrary user code, network or Jev calls in C1.
Run in a separate Python environment/process with temporary files in the workspace.
This is not a claim that a virtual environment is an OS security sandbox.
Keep existing test failures, environment failures, source changes, unrun experiments
and newly passing checks separate. Compare all protected files with the base.

Next: independent human anchor adjudication, genuinely blind model/provider runs,
larger disjoint families, an external NL-to-formal baseline, SMT cross-check, and a
preregistered Jev on/off ablation for judgment quality and exploration priority.
No v0.3.0 release or claim of completed arbitrary NL fidelity in this phase.
