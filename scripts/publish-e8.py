"""Conditional E8 publication using only the existing verified CI publisher."""
import contextlib
import importlib.util
import io
from pathlib import Path
import json
import os


def load(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    folder = Path(__file__).resolve().parent
    gate = load("e8_publication_gate",folder/"check-e8-release-eligibility.py").evaluate()
    if not gate["allow_release"]:
        # Do not even load a publisher which can create a tag or Draft.
        raise PermissionError("E8 release blocked: "+",".join(gate["reasons"]))
    if "E5_RELEASE_SOURCE_SHA" in os.environ:
        raise ValueError("E8 publication requires validated current main")
    wrapper = load("e8_existing_ci_publisher",folder/"publish-e7.py")
    wrapper.VERSION, wrapper.TAG = "0.8.0a1", "v0.8.0a1"
    publisher = wrapper._load_publisher()
    with contextlib.redirect_stdout(io.StringIO()):
        publisher.main()
    path = Path("release-receipt.json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt["source_commit"] != os.environ["GITHUB_SHA"] or receipt["ci_commit"] != os.environ["GITHUB_SHA"]:
        raise ValueError("E8 publication source differs from validated main")
    receipt["publication_policy"] = "E8_READINESS_GATED_SINGLE_CI_PATH"
    path.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(receipt,indent=2))


if __name__ == "__main__":
    main()
