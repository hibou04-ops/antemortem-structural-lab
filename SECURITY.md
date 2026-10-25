# Security model (experimental)

**Only run files you authored or independently trust.** This project can import and execute arbitrary local Python target code and has no hostile-code sandbox. Do not treat `--allow-local-execution` as a safety boundary. Never test live systems, unauthorized targets, or untrusted repositories.

Evidence artifacts may contain local paths, function inputs, and other context. They are excluded from source control under `results/`; review any outputs before sharing.

API keys must be passed through environment variables, not source files, logs, issues, or support requests. Jev providers are optional and may bill for a smoke run. This tool cannot independently verify arbitrary LLM claims, model safety, or real-world truth.

For a vulnerability report, open a minimal reproduction without credentials or sensitive data. Use GitHub private vulnerability reporting if available for the repository. Do not publish working credentials.
