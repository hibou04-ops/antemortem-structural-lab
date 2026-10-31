"""Check immutable R2 evidence against its original Git trees, never R3 bytes."""
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "0247d364e322e998b453157677af740ed76fa470"
TREES = (("da63d701e4af3d3b8e0cbb17f1be004da211ced2", "docs/E8_R2_CODE_FREEZE.json", 157),
         ("c04f0610a98698098acf0362fd2955db096232c6", "docs/E8_R2_PACKAGING_CODE_FREEZE.json", 165),
         (REVISION, "docs/E8_R2_PY313_QA_CODE_FREEZE.json", 167))


def verify(root):
    def historical(revision, path):
        return subprocess.check_output(["git", "show", revision+":"+path], cwd=root)
    counts = []
    for revision, name, count in TREES:
        raw = historical(revision, name)
        if (Path(root)/name).read_bytes() != raw:
            raise ValueError("historical R2 manifest overwritten: "+name)
        manifest = json.loads(raw)
        if manifest["product_files"] != count:
            raise ValueError("historical R2 inventory differs")
        for path, expected in manifest["product"].items():
            if hashlib.sha256(historical(revision, path)).hexdigest() != expected:
                raise ValueError("historical R2 blob differs: "+path)
        counts.append(count)
    # Existing tests remain byte-identical, including main's PyPI tests.
    tests = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION, "tests"], cwd=root).decode().splitlines()
    for name in tests:
        if (Path(root)/name).read_bytes() != historical(REVISION, name):
            raise ValueError("existing R2 test contract changed: "+name)
    return dict(status="PASS", revision=REVISION, historical_inventories=counts,
                preserved_test_files=len(tests), current_R3_compared_as_R2=False)


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), indent=2))
