import hashlib
import importlib.util
from pathlib import Path

import pytest


def verifier():
    path=Path(__file__).resolve().parents[1]/"scripts/check-e6-freeze.py"
    spec=importlib.util.spec_from_file_location("e6_freeze_test",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_commitment_accepts_exact_bytes_and_rejects_drift(tmp_path):
    path=tmp_path/"module.py"
    path.write_bytes(b"public source\n")
    manifest={"schema":"tomolab-e6-code-freeze-v1","version":"0.6.0a1","product_files":1,
              "product":{"module.py":hashlib.sha256(path.read_bytes()).hexdigest()}}
    check=verifier()
    assert check.verify(tmp_path,manifest)["status"]=="PASS"
    path.write_bytes(b"modified source\n")
    with pytest.raises(ValueError,match="drifted"):
        check.verify(tmp_path,manifest)


def test_public_commitment_cannot_read_outside_checkout(tmp_path):
    manifest={"schema":"tomolab-e6-code-freeze-v1","version":"0.6.0a1","product_files":1,
              "product":{"../outside.py":"0"*64}}
    with pytest.raises(ValueError,match="inside"):
        verifier().verify(tmp_path,manifest)
