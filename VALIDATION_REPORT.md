# v0.1.1 validation — 2026-10-24

## Scope

- First-party TypeSafe Jev API direct integration added as an optional route.
- Existing Vercel AI Gateway route retained.
- No changes to `hibou04-ops/antemortem-cli`, existing v0.1.0 ZIP, or archived root handoff.
- No API credentials were collected, committed, logged, or embedded.

## Automated checks

- 29 offline pytest tests passed with Python 3.13.
- Tests mock all Jev HTTP calls and check exact URLs, bearer-header mapping, model identifiers, reply allowlisting, error redaction, no cross-provider failover, and a mixed-success accounting invariant.
- Local deterministic demonstration still runs. Missing-key `--jev` reports `jev_error_deterministic_fallback`, rather than live connectivity.
- **Live API authentication was not executed.** Real service authentication and billing must be tested locally by the owner with the issued credential.

## Failure interpretation

- `jev_live_typesafe`: confirmed parsed response from the direct TypeSafe route. This is **not** proof of a good selection or correctness.
- `jev_error_deterministic_fallback`: all Jev calls failed/missing credentials, with deterministic fallback.
- `jev_partial_fallback`: at least one Jev call succeeded and at least one later call failed.
- `NO_COUNTEREXAMPLE_FOUND`: no contradiction observed; not a correctness proof.
