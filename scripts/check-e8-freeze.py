"""Verify current E8 implementation bytes, separately from historical E7."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tomllib


def expected_files(root):
    root = Path(root)
    return {p.relative_to(root).as_posix() for p in (root/"tomolab").rglob("*.py")} | {
        "pyproject.toml", "scripts/evaluate-e8.py", "docs/E8_EVALUATION_CONTRACT.json",
        "docs/E8_CONSUMED_IDENTITIES.json", "scripts/check-e8-release-eligibility.py",
        "scripts/publish-e8.py", "scripts/check-wheel.py", "scripts/check-e8-freeze.py",
        "scripts/check-public-scope.py", "scripts/check-historical-e7-freeze.py", ".github/workflows/tests.yml"}


def verify(root, manifest):
    root = Path(root).resolve()
    if (set(manifest) != {"schema","version","scope","product_files","product"}
            or manifest["schema"] != "tomolab-e8-code-freeze-v1"
            or manifest["scope"] != "IMPLEMENTATION_BYTES_NOT_RESEARCH_VERDICT"
            or manifest["version"] != tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]):
        raise ValueError("unsupported E8 implementation commitment")
    product = manifest["product"]
    if not isinstance(product,dict) or manifest["product_files"] != len(product) or set(product) != expected_files(root):
        raise ValueError("E8 product file set differs or omits evaluation contract")
    for name, expected in product.items():
        relative = PurePosixPath(name)
        path = (root/name).resolve()
        if (relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root)
                or not isinstance(expected,str) or not re.fullmatch(r"[0-9a-f]{64}",expected)
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError("E8 committed file bytes differ: "+name)
    return {"status":"PASS","product_files":len(product),"scope":manifest["scope"]}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_CODE_FREEZE.json").read_text(encoding="utf-8"))),indent=2))
