"""Current R1 byte commitment, separate from immutable E7 and E8 history."""
import hashlib,json,re,tomllib
from pathlib import Path,PurePosixPath

def expected_files(root):
    root=Path(root)
    return {p.relative_to(root).as_posix() for p in (root/"tomolab").rglob("*.py")} | {
        "pyproject.toml",".github/workflows/tests.yml","scripts/check-e8r1-freeze.py","scripts/check-historical-e8-freeze.py",
        "scripts/check-historical-e7-freeze.py","scripts/check-wheel.py","scripts/check-public-scope.py",
        "scripts/check-e8-release-eligibility.py","scripts/publish-e8.py","scripts/evaluate-e8.py",
        "docs/E8_CONSUMED_IDENTITIES.json","docs/E8_EVALUATION_CONTRACT.json",
        "docs/E8_R1_SEMANTIC_CONTRACT.json","docs/E8_R1_DEVELOPMENT_CONTRACT.json"}

def verify(root,manifest):
    root=Path(root).resolve()
    if (set(manifest)!={"schema","version","scope","product_files","product"}
        or manifest["schema"]!="tomolab-e8r1-code-freeze-v1" or manifest["scope"]!="IMPLEMENTATION_BYTES_NOT_SOURCE_OR_TRANSFER_VERDICT"
        or manifest["version"]!=tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]):
        raise ValueError("unsupported R1 byte commitment")
    product=manifest["product"]
    if not isinstance(product,dict) or set(product)!=expected_files(root) or manifest["product_files"]!=len(product):raise ValueError("R1 product set is incomplete")
    for name,sha in product.items():
        path=(root/name).resolve();relative=PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or not re.fullmatch(r"[a-f0-9]{64}",sha) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError("R1 frozen source changed: "+name)
    return {"status":"PASS","product_files":len(product),"scope":manifest["scope"]}

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_R1_CODE_FREEZE.json").read_text(encoding="utf-8"))),indent=2))
