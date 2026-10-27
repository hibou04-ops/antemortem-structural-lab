"""E7 current-main release policy using the reviewed E5 draft/asset verifier."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import time
from pathlib import Path

VERSION = "0.7.0a1"
TAG = "v"+VERSION


def created_draft_readback(reader, *, sleep=time.sleep):
    """Retry successful empty reads only; authorization/API errors propagate."""
    for delay in (0, 1, 2, 4):
        if delay:
            sleep(delay)
        release = reader()
        if release is not None:
            return release
    return None


def _load_publisher():
    path = Path(__file__).with_name("publish-e5.py")
    spec = importlib.util.spec_from_file_location("e7_reviewed_publisher",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    module.TAG = TAG
    original_gh, original_find = module.gh, module.find_release
    created = [False]
    def gh(*args, **kwargs):
        result = original_gh(*args, **kwargs)
        if args[:2] == ("release", "create"):
            created[0] = True
        return result
    def find():
        return created_draft_readback(original_find) if created[0] else original_find()
    module.gh, module.find_release = gh, find
    return module


def main():
    # E5's old-tag recovery is historical; E7 must build and tag its CI main.
    if "E5_RELEASE_SOURCE_SHA" in os.environ:
        raise ValueError("E7 publication requires current main, without E5 recovery overrides")
    publisher = _load_publisher()
    with contextlib.redirect_stdout(io.StringIO()):
        publisher.main()
    path = Path("release-receipt.json")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt["source_commit"] != os.environ["GITHUB_SHA"] or receipt["ci_commit"] != os.environ["GITHUB_SHA"]:
        raise ValueError("E7 publication source differs from validated main")
    receipt["publication_entrypoint_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt["publication_policy"] = "E7_CURRENT_MAIN_ONLY"
    receipt["draft_visibility_policy"] = "BOUNDED_SUCCESSFUL_EMPTY_READS_ONLY; API_ERRORS_NOT_RETRIED"
    path.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":
    main()
