import hashlib
import importlib.util
from pathlib import Path

import pytest


def test_added_runtime_module_is_rejected_after_freeze(tmp_path):
    path = Path(__file__).resolve().parents[1]/"scripts/check-e7-freeze.py"
    spec = importlib.util.spec_from_file_location("e7_freeze",path)
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    runtime = tmp_path/"tomolab/a.py"
    runtime.parent.mkdir()
    runtime.write_bytes(b"# frozen\n")
    files = [runtime]
    for name in ("pyproject.toml","scripts/evaluate-e7.py","docs/E7_EVALUATION_CONTRACT.json"):
        path = tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"# committed\n");files.append(path)
    manifest = {"schema":"tomolab-e7-code-freeze-v1","version":"0.7.0a1","product_files":len(files),
                "product":{path.relative_to(tmp_path).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
    assert check.verify(tmp_path,manifest)["status"] == "PASS"
    omitted = {**manifest,"product":{k:v for k,v in manifest["product"].items() if k!="scripts/evaluate-e7.py"},"product_files":3}
    with pytest.raises(ValueError,match="file set"):
        check.verify(tmp_path,omitted)
    runtime.with_name("added.py").write_bytes(b"# changed runtime set\n")
    with pytest.raises(ValueError,match="file set"):
        check.verify(tmp_path,manifest)
