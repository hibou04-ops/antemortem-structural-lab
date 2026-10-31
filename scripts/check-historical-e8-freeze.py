"""Verify original E8 at its pinned PR commit, never rewrite its manifest."""
import hashlib,json,subprocess
from pathlib import Path
REVISION="6ce54758f00a669c9618d9a8cf7fe491c960950b"

def verify(root):
    def git(*args):return subprocess.check_output(["git",*args],cwd=root)
    manifest=json.loads(git("show",REVISION+":docs/E8_CODE_FREEZE.json"))
    runtime={name for name in git("ls-tree","-r","--name-only",REVISION,"tomolab").decode().splitlines() if name.endswith(".py")}
    extras={"pyproject.toml","scripts/evaluate-e8.py","docs/E8_EVALUATION_CONTRACT.json","docs/E8_CONSUMED_IDENTITIES.json",
        "scripts/check-e8-release-eligibility.py","scripts/publish-e8.py","scripts/check-wheel.py","scripts/check-e8-freeze.py",
        "scripts/check-public-scope.py","scripts/check-historical-e7-freeze.py",".github/workflows/tests.yml"}
    if manifest["schema"]!="tomolab-e8-code-freeze-v1" or len(runtime)!=60 or set(manifest["product"])!=runtime|extras or manifest["product_files"]!=71:
        raise ValueError("historical E8 file set differs")
    for name,sha in manifest["product"].items():
        if hashlib.sha256(git("show",REVISION+":"+name)).hexdigest()!=sha:raise ValueError("historical E8 blob differs: "+name)
    return {"status":"PASS","revision":REVISION,"historical_product_files":71,"current_R1_compared_as_old_E8":False}

if __name__=="__main__":print(json.dumps(verify(Path(__file__).resolve().parents[1]),indent=2))
