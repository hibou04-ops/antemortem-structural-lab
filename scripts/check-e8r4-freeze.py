"""Check the independently preregistered R4 host adapters and CORR policy."""
import hashlib
import json
from pathlib import Path

EXTRAS={"pyproject.toml",".github/workflows/tests.yml",".github/workflows/publish-pypi.yml",
    "docs/E8_R4_EVALUATION_CONTRACT.json","docs/E8_R4_IMPLEMENTATION_REVIEW.json","examples/numerical/source-guide.json",
    "examples/numerical/source-approval.json","examples/numerical/source-guide.sha256"}


def inventory(root):
    return sorted({p.relative_to(root).as_posix() for name in ("tomolab","scripts","tests")
        for p in (root/name).rglob("*.py")} | EXTRAS)


def verify(root,manifest):
    if (manifest.get("schema")!="tomolab-e8r4-code-freeze-v1"
            or manifest.get("baseline_revision")!="942c940c81ff6d39fd50eea6f12d3bf82f91b5d7"
            or manifest.get("product_files")!=len(manifest.get("product",{}))
            or sorted(manifest.get("product",{}))!=inventory(root)
            or manifest.get("allow_release") is not False):
        raise ValueError("invalid R4 product inventory or authority")
    for name,expected in manifest["product"].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:
            raise ValueError("frozen R4 file changed: "+name)
    return dict(status="PASS",product_files=manifest["product_files"],
        guide_recalibrated=False,final_evaluation_authorized=False,allow_release=False)


if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_R4_CODE_FREEZE.json").read_text())),indent=2))
