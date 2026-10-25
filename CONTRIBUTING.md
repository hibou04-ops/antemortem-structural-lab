# Contributing

Contributions must preserve the distinction between **observed executions**, **formal claims**, and **independent proof**. New features need reproducible fixtures, testable failure modes, and clear in-scope/out-of-scope declarations.

Set up:

```bash
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```

Do not commit `results/`, generated build outputs, keys, `.env`, personally identifiable information, or private research notes. Avoid implying benchmark superiority without matched independent baselines.
