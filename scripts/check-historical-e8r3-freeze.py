"""Verify R3 at its immutable Git revision, never reinterpret R4 as R3."""
import hashlib
import json
from pathlib import Path
import subprocess

REVISION="942c940c81ff6d39fd50eea6f12d3bf82f91b5d7"


def verify(root):
    def original(path):
        return subprocess.check_output(["git","show",REVISION+":"+path],cwd=root)
    raw=original("docs/E8_R3_CODE_FREEZE.json")
    if (root/"docs/E8_R3_CODE_FREEZE.json").read_bytes()!=raw:
        raise ValueError("historical R3 commitment was rewritten")
    manifest=json.loads(raw)
    if manifest["product_files"]!=165 or len(manifest["product"])!=165:
        raise ValueError("historical R3 inventory differs")
    for path,expected in manifest["product"].items():
        if hashlib.sha256(original(path)).hexdigest()!=expected:
            raise ValueError("historical R3 blob differs: "+path)
    tests=subprocess.check_output(["git","ls-tree","-r","--name-only",REVISION,"tests"],cwd=root).decode().splitlines()
    for path in tests:
        if (root/path).read_bytes()!=original(path):
            raise ValueError("existing 720-test contract file changed: "+path)
    protected=["tomolab/discovery/"+name for name in ("__init__.py","schema.py","numerical_guidance.py",
        "compact_guidance.py","numerical_worker.py","numerical_service.py","numerical_source.py",
        "numerical_response.py","numerical_prepared.py","numerical_boundary.py")]
    for path in protected:
        if (root/path).read_bytes()!=original(path):
            raise ValueError("R4 changed the frozen Source generation/runtime/Oracle path: "+path)
    return dict(status="PASS",revision=REVISION,historical_product_files=165,
        existing_test_files_preserved=len(tests),source_generation_runtime_oracle_files_preserved=len(protected),
        current_R4_compared_as_R3=False)


if __name__=="__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]),indent=2))
