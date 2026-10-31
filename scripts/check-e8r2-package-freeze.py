"""Preserve Source validation bytes and separately verify packaging QA fixes.

The original R2 manifest is never rewritten. A post-validation Windows UTF-8
checker fix changes no runtime, strategy, Oracle, recipe, budget or result.
Both the pinned historical tree and current runtime must match that record.
"""
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE_TREE = "9f5fb9b15fa6854c1b8c090bfb62915fcae5fc26"
SOURCE_MANIFEST_SHA256 = "d8c3f5a0cff4b8461ffbb19fccd22479cef1e07e5445cebd9141ba8a721e44b1"
QA_FIXES = {"scripts/check-numerical-wheel.py", ".github/workflows/tests.yml"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def historical(root, name):
    return subprocess.check_output(["git","show",SOURCE_TREE+":"+name],cwd=root)


def verify_source_history(root):
    root = Path(root)
    raw = (root/"docs/E8_R2_CODE_FREEZE.json").read_bytes()
    if sha(raw) != SOURCE_MANIFEST_SHA256 or raw != historical(root,"docs/E8_R2_CODE_FREEZE.json"):
        raise ValueError("original Source validation manifest was rewritten")
    source = json.loads(raw)
    runtime = {p.relative_to(root).as_posix() for p in (root/"tomolab").rglob("*.py")}
    if source["product_files"] != 157 or runtime != {p for p in source["product"] if p.startswith("tomolab/")}:
        raise ValueError("validated Source runtime inventory changed")
    python_files = {p.relative_to(root).as_posix() for folder in ("tomolab","scripts","tests")
                    for p in (root/folder).rglob("*.py")}
    if python_files != {p for p in source["product"] if p.endswith(".py")} | {"scripts/check-e8r2-package-freeze.py"}:
        raise ValueError("post-validation Python file inventory exceeds the packaging checker addition")
    for name, expected in source["product"].items():
        original = historical(root,name)
        if sha(original) != expected:
            raise ValueError("historical Source validation bytes differ: "+name)
        if name not in QA_FIXES and sha((root/name).read_bytes()) != expected:
            raise ValueError("validated runtime, recipe, contract or budget changed: "+name)
    checker = historical(root,"scripts/check-numerical-wheel.py").decode()
    fixed = checker.replace('[str(python), "-I", *map(str, arguments)]',
                            '[str(python), "-I", "-X", "utf8", *map(str, arguments)]')
    if fixed == checker or (root/"scripts/check-numerical-wheel.py").read_bytes() != fixed.encode("utf-8"):
        raise ValueError("post-validation checker change exceeds the explicit UTF-8 fix")
    workflow = historical(root,".github/workflows/tests.yml").decode()
    adapted = workflow.replace("python scripts/check-e8r2-freeze.py", "python scripts/check-e8r2-package-freeze.py")
    if adapted == workflow or (root/".github/workflows/tests.yml").read_bytes() != adapted.encode("utf-8"):
        raise ValueError("post-validation workflow change exceeds the separate freeze checker route")
    return source


def expected_files(root):
    root = Path(root)
    source = json.loads((root/"docs/E8_R2_CODE_FREEZE.json").read_text(encoding="utf-8"))
    return set(source["product"]) | {"scripts/check-e8r2-package-freeze.py", "MANIFEST.in",
        "README.md", "README.ko.md", "CHANGELOG.md", "docs/E8_R2_REPORT.md",
        "docs/E8_R2_CODE_FREEZE.json", "docs/E8_R2_RESULTS.json"}


def verify(root, package):
    root = Path(root)
    source = verify_source_history(root)
    if (package.get("schema") != "tomolab-e8r2-post-validation-package-freeze-v1" or
            package.get("source_validation_tree") != SOURCE_TREE or
            package.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256 or
            package.get("source_validation_batch_reexecuted") is not False or
            package.get("post_validation_qa_changes") != sorted(QA_FIXES) or
            set(package.get("product",{})) != expected_files(root) or
            package.get("product_files") != len(package.get("product",{}))):
        raise ValueError("post-validation package commitment differs")
    for name, expected in package["product"].items():
        if sha((root/name).read_bytes()) != expected:
            raise ValueError("committed package bytes changed: "+name)
    return {"status":"PASS", "historical_Source_product_files":source["product_files"],
        "source_validation_tree":SOURCE_TREE, "original_Source_manifest_preserved":True,
        "current_runtime_recipe_contract_budget_identical":True,
        "explicit_post_validation_QA_changes":sorted(QA_FIXES),
        "current_package_files":package["product_files"], "Source_validation_batch_reexecuted":False}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_R2_PACKAGING_CODE_FREEZE.json").read_text(encoding="utf-8"))),indent=2))
