"""R2 implementation commitment, separate from the immutable E7/E8/R1 history."""
import hashlib
import json
from pathlib import Path


def expected_files(root):
    root = Path(root)
    paths = {p.relative_to(root).as_posix() for folder in ("tomolab","scripts","tests")
             for p in (root/folder).rglob("*.py")}
    paths |= {p.relative_to(root).as_posix() for p in (root/"examples/numerical").iterdir() if p.is_file()}
    paths |= {"pyproject.toml", ".github/workflows/tests.yml", ".github/workflows/publish-pypi.yml",
        "docs/E8_R2_CONTRACT.json", "docs/E7_CODE_FREEZE.json", "docs/E8_CODE_FREEZE.json",
        "docs/E8_R1_CODE_FREEZE.json", "docs/E8_R1_SEMANTIC_CONTRACT.json",
        "docs/E8_RELEASE_AUTHORIZATION.json", "docs/E8_CONSUMED_IDENTITIES.json"}
    return paths


def verify(root, manifest):
    root = Path(root)
    if (manifest.get("schema") != "tomolab-e8r2-code-freeze-v1" or
            manifest.get("scope") != "SOURCE_DEVELOPMENT_CODE_RECIPE_BUDGET_NOT_EXTERNAL_VALIDATION" or
            manifest.get("product_files") != len(manifest.get("product",{})) or
            set(manifest.get("product",{})) != expected_files(root)):
        raise ValueError("R2 implementation commitment inventory differs")
    for name, expected in manifest["product"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError("R2 frozen implementation changed: "+name)
    return {"status":"PASS", "product_files":manifest["product_files"],
            "scope":manifest["scope"], "historical_manifests_rewritten":False}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_R2_CODE_FREEZE.json").read_text(encoding="utf-8"))),indent=2))
