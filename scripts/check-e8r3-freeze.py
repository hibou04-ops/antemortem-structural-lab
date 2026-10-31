"""Fail closed if preregistered R3 runtime, tests, policy or budgets change."""
import hashlib
import json
from pathlib import Path
import subprocess

BASE = "262dee89d9ab59dadce44a888649eb48a6abbc6f"
GENERATOR = ("__init__.py", "schema.py", "numerical_guidance.py", "compact_guidance.py", "numerical_worker.py")
EXTRAS = {"pyproject.toml", ".github/workflows/tests.yml", ".github/workflows/publish-pypi.yml",
          "docs/E8_R3_PUBLIC_PROFILE_CONTRACT.json", "docs/E8_R3_SOURCE_CONTRACT.json",
          "examples/numerical/source-guide.json", "examples/numerical/source-approval.json",
          "examples/numerical/source-guide.sha256"}


def inventory(root):
    root = Path(root)
    return sorted({path.relative_to(root).as_posix() for folder in ("tomolab", "scripts", "tests")
        for path in (root/folder).rglob("*.py")} | EXTRAS)


def verify(root, manifest):
    root = Path(root)
    if (manifest.get("schema") != "tomolab-e8r3-code-freeze-v1"
            or manifest.get("baseline_revision") != BASE
            or sorted(manifest.get("product", {})) != inventory(root)
            or manifest.get("product_files") != len(manifest["product"])
            or manifest.get("allow_release") is not False):
        raise ValueError("R3 code freeze schema or product inventory differs")
    for name, expected in manifest["product"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError("R3 frozen file changed: "+name)
    for name in GENERATOR:
        path = "tomolab/discovery/"+name
        original = subprocess.check_output(["git", "show", BASE+":"+path], cwd=root)
        if original != (root/path).read_bytes():
            raise ValueError("R2 clean generator context changed: "+name)
    return dict(status="PASS", product_files=manifest["product_files"],
        generator_files_preserved=len(GENERATOR), r2_policy_and_oracle_changed=False,
        source_validation_batch_reexecuted=False, allow_release=False)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root, json.loads((root/"docs/E8_R3_CODE_FREEZE.json").read_text())), indent=2))
