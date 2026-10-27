"""One fail-closed policy for CI and the publisher, before any release mutation.

Public receipts are reviewed host attestations, not cryptographic proof of
Oracle truth. Private source/answers/known-positive tests never belong here.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(root=ROOT):
    root = Path(root)
    reasons = []
    try:
        auth = _read(root/"docs/E8_RELEASE_AUTHORIZATION.json")
        if auth.get("schema") != "tomolab-e8-release-authorization-v1":
            reasons.append("unsupported-release-authorization")
        if auth.get("status") != "AUTHORIZED":
            reasons.append("release-not-authorized")
        if auth.get("source_corroboration_linkage") != "VERIFIED":
            reasons.append("real-source-corroboration-not-verified")
        if auth.get("comparison_status") != "COMPLETE":
            reasons.append("eligible-comparison-not-complete")
        if type(auth.get("qualified_guidance")) is not int or auth["qualified_guidance"] < 1:
            reasons.append("no-qualified-guidance")
        # A blocked development branch is a valid CI outcome, not publication.
        if reasons:
            return {"allow_release": False, "status": "NOT_AUTHORIZED_READINESS_BLOCKED", "reasons": reasons}
        readiness_path = root/"docs/E8_READINESS_PUBLIC.json"
        comparison_path = root/"docs/E8_FINAL_RESULTS.json"
        freeze_path = root/"docs/E8_CODE_FREEZE.json"
        for field,path in (("readiness_receipt_sha256",readiness_path),
                           ("comparison_receipt_sha256",comparison_path),
                           ("product_manifest_sha256",freeze_path)):
            if auth.get(field) != _sha(path):
                reasons.append(field+"-differs")
        ready, result = _read(readiness_path), _read(comparison_path)
        if (ready.get("status") != "PASS" or ready.get("evidence_scope") != "REVIEWED_REAL_PROJECT"
                or ready.get("source_corroboration_linkage") != "VERIFIED"
                or type(ready.get("qualified_guidance")) is not int or ready["qualified_guidance"] < 1):
            reasons.append("readiness-is-not-real-qualified-transfer")
        if (result.get("comparison_status") != "COMPLETE" or result.get("final_attempts") != 1
                or result.get("full_grid") is not True or result.get("methods") != ["A","B","C","D"]
                or result.get("generator_feedback") != 0 or result.get("required_errors") != 0
                or result.get("control_false_alerts") != 0
                or result.get("readiness_receipt_sha256") != auth["readiness_receipt_sha256"]
                or result.get("product_manifest_sha256") != auth["product_manifest_sha256"]
                or result.get("verdict") not in ("IMPROVED","NO_IMPROVEMENT","INCONCLUSIVE")):
            reasons.append("comparison-does-not-meet-publication-contract")
        freeze = _read(freeze_path)
        checker_path = root/"scripts/check-e8-freeze.py"
        spec = importlib.util.spec_from_file_location("e8_current_byte_commitment",checker_path)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        checker.verify(root,freeze)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        reasons.append("invalid-or-missing-publication-evidence:"+type(error).__name__)
    return {"allow_release": not reasons,
            "status": "AUTHORIZED" if not reasons else "NOT_AUTHORIZED_READINESS_BLOCKED",
            "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    result = evaluate()
    if args.github_output:
        path = os.environ.get("GITHUB_OUTPUT")
        if not path:
            raise ValueError("GITHUB_OUTPUT required for CI outputs")
        with open(path,"a",encoding="utf-8",newline="\n") as stream:
            stream.write("allow_release="+str(result["allow_release"]).lower()+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
