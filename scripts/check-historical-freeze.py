"""Verify an existing commitment at its original Git revision, without rebasing hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def verify(root, revision, manifest_path):
    def original(path):
        return subprocess.check_output(["git", "show", revision+":"+path], cwd=root)
    raw = original(manifest_path)
    if (root/manifest_path).read_bytes() != raw:
        raise ValueError("historical commitment was rewritten")
    manifest = json.loads(raw)
    if manifest["product_files"] != len(manifest["product"]):
        raise ValueError("historical inventory length differs")
    for name, expected in manifest["product"].items():
        if hashlib.sha256(original(name)).hexdigest() != expected:
            raise ValueError("historical blob differs: "+name)
    tests = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision, "tests"], cwd=root).decode().splitlines()
    for name in tests:
        if (root/name).read_bytes() != original(name):
            raise ValueError("historical regression contract changed: "+name)
    return dict(status="PASS", revision=revision, manifest=manifest_path,
                historical_files=manifest["product_files"], regression_files_preserved=len(tests),
                current_code_compared_as_historical=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(Path(__file__).resolve().parents[1], args.revision, args.manifest), indent=2))
