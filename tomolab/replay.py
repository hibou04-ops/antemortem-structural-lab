"""Evidence replay checks observed behavior against immutable source bytes."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from .cast import load_trusted_functions, observe
from .model import Proposal
from .mri import inspect_file


def replay_evidence(
    evidence_file: Path, *, trusted_execution: bool = False,
    source_override: Path | None = None, oracle_override: Path | None = None,
) -> dict[str, Any]:
    if not trusted_execution:
        raise PermissionError("replay executes local code; explicitly opt in")
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if evidence.get("schema") != "tomolab-evidence-v1":
        raise ValueError("unsupported evidence schema")
    source_meta = evidence.get("source", {})
    source_path = (source_override or Path(source_meta["source_file"])).resolve(strict=True)
    oracle_path = (oracle_override or Path(source_meta["oracle_source_file"])).resolve(strict=True)
    ins = inspect_file(source_path, source_meta["function"])
    if ins.source_sha256 != source_meta.get("source_sha256"):
        return {"status": "SOURCE_DRIFT", "replayed": 0, "expected_sha256": source_meta.get("source_sha256"),
                "actual_sha256": ins.source_sha256}
    oracle_hash = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
    if oracle_hash != source_meta.get("oracle_source_sha256"):
        return {"status": "ORACLE_DRIFT", "replayed": 0, "expected_sha256": source_meta.get("oracle_source_sha256"),
                "actual_sha256": oracle_hash}
    findings = evidence.get("findings", [])
    if not isinstance(findings, list) or not findings:
        return {"status": "NO_FINDINGS", "replayed": 0}
    fn, oracle = load_trusted_functions(source_path, ins.function, evidence["oracle_function"], oracle_path)
    results = []
    for item in findings:
        values = item["inputs"]
        if not isinstance(values, list) or len(values) != len(ins.parameters) or any(type(x) is not int for x in values):
            raise ValueError("malformed evidence inputs")
        probe = Proposal(tuple(values), "replay stored counterexample", "replay")
        obs = observe(fn, oracle, ins, probe)
        replicated = (
            obs.contradicts_oracle
            and item["contradicts_oracle"]
            and obs.actual_type == item["actual_type"]
            and obs.expected_type == item["expected_type"]
            and obs.actual == item["actual"]
            and obs.expected == item["expected"]
        )
        results.append({"inputs": list(values), "replicated": replicated,
                        "actual": obs.actual, "expected": obs.expected})
    status = "REPRODUCED" if all(r["replicated"] for r in results) else "NOT_REPRODUCED"
    return {"status": status, "replayed": len(results), "results": results,
            "scope": "same source hash and executable reference; oracle correctness remains external"}
