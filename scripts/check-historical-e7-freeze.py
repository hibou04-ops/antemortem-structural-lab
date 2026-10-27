"""Check the untouched historical E7 Git revision, never current E8 files."""
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "2edfb1230bd8519072845d9b9b0e2d4c42ab3837"


def verify(root):
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=root)
    manifest = json.loads(git("show",REVISION+":docs/E7_CODE_FREEZE.json"))
    if manifest["schema"] != "tomolab-e7-code-freeze-v1" or manifest["version"] != "0.7.0a1":
        raise ValueError("unexpected historical E7 commitment")
    runtime = {p for p in git("ls-tree","-r","--name-only",REVISION,"tomolab").decode().splitlines() if p.endswith(".py")}
    expected = runtime | {"pyproject.toml","scripts/evaluate-e7.py","docs/E7_EVALUATION_CONTRACT.json"}
    if len(runtime) != 54 or set(manifest["product"]) != expected or manifest["product_files"] != 57:
        raise ValueError("historical E7 product set differs")
    for name, expected_sha in manifest["product"].items():
        if hashlib.sha256(git("show",REVISION+":"+name)).hexdigest() != expected_sha:
            raise ValueError("historical E7 Git blob differs: "+name)
    return {"status":"PASS","revision":REVISION,"historical_product_files":57,
            "current_E8_files_compared_as_E7":False}


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]),indent=2))
