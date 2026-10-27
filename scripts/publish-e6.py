"""E6 current-main release policy using the reviewed E5 draft/asset verifier."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

VERSION = "0.6.0a1"
TAG = "v"+VERSION


def _load_publisher():
    path = Path(__file__).with_name("publish-e5.py")
    spec = importlib.util.spec_from_file_location("e6_reviewed_publisher",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    module.TAG = TAG
    return module


def main():
    # E5's old-tag recovery is historical; E6 must build and tag its CI main.
    if "E5_RELEASE_SOURCE_SHA" in os.environ:
        raise ValueError("E6 publication requires current main, without E5 recovery overrides")
    publisher = _load_publisher()
    with contextlib.redirect_stdout(io.StringIO()):
        publisher.main()
    path = Path("release-receipt.json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt["source_commit"] != os.environ["GITHUB_SHA"] or receipt["ci_commit"] != os.environ["GITHUB_SHA"]:
        raise ValueError("E6 publication source differs from validated main")
    receipt["publication_entrypoint_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt["publication_policy"] = "E6_CURRENT_MAIN_ONLY"
    path.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":
    main()
