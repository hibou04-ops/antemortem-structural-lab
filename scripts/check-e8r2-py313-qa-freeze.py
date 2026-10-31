"""Preserve both earlier commitments and verify only reviewed QA adaptations.

Python 3.13 omits empty AST fields by default. Explicit show_empty restores
the earlier serialization without changing either expected AST hash. Neither
this QA correction nor UTF-8 output handling changes Source execution.
"""
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE_TREE = "9f5fb9b15fa6854c1b8c090bfb62915fcae5fc26"
PACKAGE_TREE = "044335dc7882ed7414250bfe9a0327da641eaf05"
SOURCE_MANIFEST_SHA256 = "d8c3f5a0cff4b8461ffbb19fccd22479cef1e07e5445cebd9141ba8a721e44b1"
PACKAGE_MANIFEST_SHA256 = "8424cad3df6cb417cd5455f914444a33c346602ed46d8962e96bfa4683ca1f69"
QA_FIXES = {"scripts/check-numerical-wheel.py", ".github/workflows/tests.yml", "tests/test_numerical_source.py"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def historical(root, tree, name):
    return subprocess.check_output(["git","show",tree+":"+name],cwd=root)


def _history(root,tree,name,expected,count):
    raw = (root/name).read_bytes()
    if sha(raw) != expected or raw != historical(root,tree,name):
        raise ValueError("historical commitment rewritten: "+name)
    manifest = json.loads(raw)
    if manifest["product_files"] != count:
        raise ValueError("historical commitment inventory changed")
    for path,digest in manifest["product"].items():
        if sha(historical(root,tree,path)) != digest:
            raise ValueError("historical committed file differs: "+path)
    return manifest


def verify_history(root):
    root=Path(root)
    source=_history(root,SOURCE_TREE,"docs/E8_R2_CODE_FREEZE.json",SOURCE_MANIFEST_SHA256,157)
    package=_history(root,PACKAGE_TREE,"docs/E8_R2_PACKAGING_CODE_FREEZE.json",PACKAGE_MANIFEST_SHA256,165)
    for name,digest in source["product"].items():
        if name not in QA_FIXES and sha((root/name).read_bytes()) != digest:
            raise ValueError("validated runtime/recipe/domain/Oracle/budget changed: "+name)
    allowed_additions={"scripts/check-e8r2-package-freeze.py", "scripts/check-e8r2-py313-qa-freeze.py"}
    python_files={p.relative_to(root).as_posix() for folder in ("tomolab","scripts","tests") for p in (root/folder).rglob("*.py")}
    if python_files != {p for p in source["product"] if p.endswith(".py")} | allowed_additions:
        raise ValueError("unreviewed post-validation Python addition")
    old_checker="scripts/check-e8r2-package-freeze.py"
    if sha((root/old_checker).read_bytes()) != package["product"][old_checker]:
        raise ValueError("prior packaging checker changed")
    wheel=historical(root,SOURCE_TREE,"scripts/check-numerical-wheel.py").decode()
    wheel=wheel.replace('[str(python), "-I", *map(str, arguments)]','[str(python), "-I", "-X", "utf8", *map(str, arguments)]')
    workflow=historical(root,SOURCE_TREE,".github/workflows/tests.yml").decode()
    workflow=workflow.replace("python scripts/check-e8r2-freeze.py","python scripts/check-e8r2-py313-qa-freeze.py")
    test=historical(root,SOURCE_TREE,"tests/test_numerical_source.py").decode()
    before='    actual = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False)\n'
    after=('    dump_options = {"show_empty": True} if "show_empty" in inspect.signature(ast.dump).parameters else {}\n'
           '    actual = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False, **dump_options)\n')
    if test.count(before) != 1:
        raise ValueError("unexpected historical AST test shape")
    test=test.replace(before,after)
    for name,text in (("scripts/check-numerical-wheel.py",wheel), (".github/workflows/tests.yml",workflow),
                      ("tests/test_numerical_source.py",test)):
        if (root/name).read_bytes() != text.encode("utf-8"):
            raise ValueError("QA change exceeds reviewed byte patch: "+name)
    return source,package


def expected_files(root):
    previous=json.loads((Path(root)/"docs/E8_R2_PACKAGING_CODE_FREEZE.json").read_text(encoding="utf-8"))
    return set(previous["product"]) | {"docs/E8_R2_PACKAGING_CODE_FREEZE.json", "scripts/check-e8r2-py313-qa-freeze.py"}


def verify(root,manifest):
    root=Path(root)
    verify_history(root)
    if (manifest.get("schema") != "tomolab-e8r2-python313-qa-freeze-v1" or
            manifest.get("source_validation_tree") != SOURCE_TREE or
            manifest.get("prior_packaging_tree") != PACKAGE_TREE or
            manifest.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256 or
            manifest.get("prior_packaging_manifest_sha256") != PACKAGE_MANIFEST_SHA256 or
            manifest.get("qa_only_modified_source_files") != sorted(QA_FIXES) or
            manifest.get("Source_validation_batch_reexecuted") is not False or
            set(manifest.get("product",{})) != expected_files(root) or
            manifest.get("product_files") != len(manifest.get("product",{}))):
        raise ValueError("Python 3.13 QA commitment differs")
    for name,digest in manifest["product"].items():
        if sha((root/name).read_bytes()) != digest:
            raise ValueError("final QA package bytes changed: "+name)
    return {"status":"PASS", "historical_Source_files":157, "historical_packaging_files":165,
        "current_QA_package_files":manifest["product_files"], "original_manifests_preserved":True,
        "expected_AST_hashes_changed":False, "runtime_recipe_Oracle_budget_unchanged":True,
        "explicit_QA_only_changes":sorted(QA_FIXES), "Source_validation_batch_reexecuted":False}


if __name__ == "__main__":
    root=Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root,json.loads((root/"docs/E8_R2_PY313_QA_CODE_FREEZE.json").read_text(encoding="utf-8"))),indent=2))
