# Jev Provider Integration — 2026-10-24

**Base:** v0.1.0. **Integration version:** v0.1.1. The v0.1.0 archive and the existing public `antemortem-cli` GitHub repository are not modified.

## Verified contracts

- Direct TypeSafe: `https://api.typesafe.ai/v1/systemone`, model `jev-latest`, key `TYPESAFE_API_KEY` (TypeSafe official documentation)
- Vercel AI Gateway: `https://ai-gateway.vercel.sh/v1/evaluate`, model `typesafe-ai/jev`, key `AI_GATEWAY_API_KEY` (Vercel official documentation)
- TypeSafe provider is auto-preferred only when both keys exist; explicit `--jev-provider` pins one backend. Provider failures do not fail over to another billable provider.
- The only outbound evaluation data consists of a bounded number of small numeric probe values and flags, not source code or file paths.
- Real credentials must never enter source, the ZIP, logs, screenshots, chat or test artifacts.

## Evidence status

- Mock transport and response validation: tested offline. Run `python -m pytest -q`.
- Real billing account, live request, runtime performance or superiority: **NOT TESTED**. Only a user-controlled environment with their real key can check this.
- The smoke script executes one TypeSafe API request on a bundled, deliberately faulty but locally trusted fixture and checks the output's decision-provider label, NOT that the result is objectively best.

## Next checkpoint to append to the existing private archive

Once live tested, record date, executed command, result status, test count, cost visible in TypeSafe usage, provider model version, and a checksum of the v0.1.1 ZIP. Do **not** record the API key or request headers. Keep results separate from the previous v0.1.0 immutable archive.
