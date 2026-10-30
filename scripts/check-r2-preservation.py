"""Read-only lineage checks: fixed public PyPI paths and all prior test blobs."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
R1 = "e10699f602fb8757098e0ba675b44e54828f960c"
MAIN = "3739e7dee2a7064d1c73f2c29dac30dc7c2eefe1"


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT)


def main():
    protected = [".github/workflows/publish-pypi.yml", "scripts/verify-pypi-release.py",
        "scripts/verify-public-pypi.py", "tests/test_pypi_release.py", "docs/PYPI_PUBLISHING.md"]
    for path in protected:
        if (ROOT/path).read_bytes() != git("show",MAIN+":"+path):
            raise ValueError("main PyPI path changed: "+path)
    old_tests = [p for p in git("ls-tree","-r","--name-only",R1,"tests").decode().splitlines() if p.endswith(".py")]
    for path in old_tests:
        if (ROOT/path).read_bytes() != git("show",R1+":"+path):
            raise ValueError("prior R1 test changed: "+path)
    old_manifests = ["docs/E7_CODE_FREEZE.json", "docs/E8_CODE_FREEZE.json", "docs/E8_R1_CODE_FREEZE.json",
        "scripts/check-e7-freeze.py", "scripts/check-e8-freeze.py", "scripts/check-e8r1-freeze.py",
        "docs/E8_RELEASE_AUTHORIZATION.json", "docs/E8_CONSUMED_IDENTITIES.json"]
    for path in old_manifests:
        if (ROOT/path).read_bytes() != git("show",R1+":"+path):
            raise ValueError("frozen historical manifest, checker or gate changed: "+path)
    workflow = (ROOT/".github/workflows/publish-pypi.yml").read_text(encoding="utf-8")
    tests = (ROOT/".github/workflows/tests.yml").read_text(encoding="utf-8")
    if ("workflow_dispatch:" not in workflow or "  push:" in workflow or "  pull_request:" in workflow
            or "refs/heads/main" not in workflow or "pypa/gh-action-pypi-publish@" in tests
            or "workflow_call:" in workflow or "publish-pypi.yml" in tests):
        raise ValueError("ordinary branch/PR CI can reach a PyPI upload")
    print(json.dumps({"status":"PASS", "pypi_paths_preserved":protected,
        "prior_R1_test_files_byte_preserved":len(old_tests),
        "pypi_test_files_byte_preserved":1, "test_name":"test_pypi_release.py",
        "R1_and_main_test_overlap_deduplicated":True,
        "historical_manifests_checkers_gates_preserved":len(old_manifests),
        "ordinary_CI_PyPI_upload_reachable":False},indent=2))


if __name__ == "__main__":
    main()
