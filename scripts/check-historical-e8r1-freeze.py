"""Verify R1 at its fixed revision; its original manifest/checker stay intact."""
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "e10699f602fb8757098e0ba675b44e54828f960c"


def verify(root):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)
    manifest = json.loads(git("show", REVISION + ":docs/E8_R1_CODE_FREEZE.json"))
    runtime = {p for p in git("ls-tree", "-r", "--name-only", REVISION, "tomolab").decode().splitlines() if p.endswith(".py")}
    extras = {"pyproject.toml", ".github/workflows/tests.yml", "scripts/check-e8r1-freeze.py",
        "scripts/check-historical-e8-freeze.py", "scripts/check-historical-e7-freeze.py",
        "scripts/check-wheel.py", "scripts/check-public-scope.py", "scripts/check-e8-release-eligibility.py",
        "scripts/publish-e8.py", "scripts/evaluate-e8.py", "docs/E8_CONSUMED_IDENTITIES.json",
        "docs/E8_EVALUATION_CONTRACT.json", "docs/E8_R1_SEMANTIC_CONTRACT.json", "docs/E8_R1_DEVELOPMENT_CONTRACT.json"}
    if (manifest["schema"] != "tomolab-e8r1-code-freeze-v1" or manifest["version"] != "0.8.0a1"
            or manifest["product_files"] != 76 or set(manifest["product"]) != runtime | extras):
        raise ValueError("historical R1 product inventory differs")
    for name, sha in manifest["product"].items():
        if hashlib.sha256(git("show", REVISION + ":" + name)).hexdigest() != sha:
            raise ValueError("historical R1 blob differs: " + name)
    return {"status": "PASS", "revision": REVISION, "historical_product_files": 76,
            "current_R2_compared_as_R1": False}


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), indent=2))
