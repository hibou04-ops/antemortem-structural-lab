"""Small authored product regressions; no historical targets or learning."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.cast import _load_module
from tomolab.cli import main
from tomolab.discovery.online_observe import observe
from tomolab.discovery.schema import digest


def _files(folder, *, dataclass=False):
    header = ("from __future__ import annotations\nfrom dataclasses import dataclass\n"
              "@dataclass\nclass Metadata:\n    value: int\n\n") if dataclass else ""
    (folder / "target.py").write_text(header +
        "def actual_function(point):\n    return point + 1 if point == 0 else point\n"
        "implementation = actual_function\n", encoding="utf-8")
    (folder / "oracle.py").write_text(
        "def actual_reference(point):\n    return point\nreference = actual_reference\n", encoding="utf-8")
    (folder / "contract.json").write_text('{"kind":"int","low":-2,"high":2}', encoding="utf-8")


def _run(folder, output, *extra):
    return main(["online-run", str(folder / "target.py"), "--oracle-file", str(folder / "oracle.py"),
                 "--contract", str(folder / "contract.json"), "--allow-local-execution",
                 "--usage-ledger", str(output.with_suffix(".usage.jsonl")), "--output", str(output),
                 "--budget", "12", "--shrink-budget", "0", *extra])


def _replay(folder, evidence, output, *extra):
    return main(["online-replay", str(evidence), "--source", str(folder / "target.py"),
                 "--oracle-file", str(folder / "oracle.py"), "--contract", str(folder / "contract.json"),
                 "--allow-local-execution", "--output", str(output), *extra])


def test_postponed_dataclass_module_uses_registered_metadata_and_runs(tmp_path):
    _files(tmp_path, dataclass=True)
    module = _load_module(tmp_path / "target.py", "_tomolab_runtime_metadata")
    try:
        assert sys.modules[module.__name__] is module
        assert module.__spec__.name == module.__name__
        assert module.__loader__ is not None and Path(module.__file__) == tmp_path / "target.py"
        assert module.Metadata(3).value == 3
        assert _run(tmp_path, tmp_path / "run.json") == 0
    finally:
        sys.modules.pop("_tomolab_runtime_metadata", None)


@pytest.mark.parametrize("has_prior", [False, True])
def test_failed_module_execution_restores_previous_cache_entry(tmp_path, has_prior):
    name = "_tomolab_runtime_failure"
    prior = object()
    if has_prior:
        sys.modules[name] = prior
    (tmp_path / "bad.py").write_text("raise RuntimeError('authored import failure')\n", encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="authored import failure"):
            _load_module(tmp_path / "bad.py", name)
        assert (sys.modules[name] is prior) if has_prior else (name not in sys.modules)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("explicit", [False, True])
def test_aliases_bind_selected_exports_and_replay_by_default(tmp_path, explicit):
    _files(tmp_path)
    evidence = tmp_path / "run.json"
    options = ["--function", "actual_function", "--oracle", "actual_reference"] if explicit else []
    assert _run(tmp_path, evidence, *options) == 0
    receipt = json.loads(evidence.read_text(encoding="utf-8"))
    assert receipt["replay_binding"]["source_function"] == ("actual_function" if explicit else "implementation")
    assert receipt["replay_binding"]["oracle_function"] == ("actual_reference" if explicit else "reference")
    assert _replay(tmp_path, evidence, tmp_path / "replay.json", *options) == 0
    assert json.loads((tmp_path / "replay.json").read_text(encoding="utf-8"))["replay_status"] == "REPRODUCED"


@pytest.mark.parametrize("change", ["file", "function", "oracle", "binding_digest"])
def test_alias_receipt_still_rejects_identity_drift(tmp_path, change):
    _files(tmp_path)
    evidence = tmp_path / "run.json"
    assert _run(tmp_path, evidence) == 0
    extra = []
    if change == "file":
        with (tmp_path / "target.py").open("a", encoding="utf-8") as stream:
            stream.write("\nraise AssertionError('changed file must not import')\n")
    elif change == "function":
        extra = ["--function", "actual_function"]
    elif change == "oracle":
        extra = ["--oracle", "actual_reference"]
    else:
        receipt = json.loads(evidence.read_text(encoding="utf-8"))
        receipt["replay_binding"]["source_function"] = "actual_function"
        evidence.write_text(json.dumps(receipt), encoding="utf-8")
    output = tmp_path / "denied.json"
    with pytest.raises(SystemExit) as error:
        _replay(tmp_path, evidence, output, *extra)
    assert error.value.code == 2 and not output.exists()


def test_existing_v1_callable_name_bindings_keep_explicit_replay_path(tmp_path):
    _files(tmp_path)
    evidence = tmp_path / "run.json"
    assert _run(tmp_path, evidence) == 0
    receipt = deepcopy(json.loads(evidence.read_text(encoding="utf-8")))
    binding = receipt["replay_binding"]
    binding.update(source_function="actual_function", oracle_function="actual_reference")
    binding["binding_digest"] = digest({k: v for k, v in binding.items() if k != "binding_digest"})
    evidence.write_text(json.dumps(receipt), encoding="utf-8")
    assert _replay(tmp_path, evidence, tmp_path / "old-replay.json", "--function", "actual_function",
                   "--oracle", "actual_reference") == 0


@pytest.mark.parametrize("arguments", [["--help"], ["online-run", "--help"]])
def test_help_in_actual_cp1252_stdout_pipe(arguments):
    env = dict(os.environ, PYTHONIOENCODING="cp1252:strict", PYTHONUTF8="0")
    process = subprocess.run([sys.executable, "-m", "tomolab", *arguments], env=env, capture_output=True)
    assert process.returncode == 0, process.stderr.decode("cp1252", errors="replace")
    rendered = process.stdout.decode("cp1252", errors="strict")
    assert "usage: tomolab" in rendered and "--help" in rendered


def test_numeric_zero_exact_policy_is_unchanged():
    contract = {"kind": "float", "comparison": {"absolute": 1e-6, "relative": 1e-6}}
    assert observe(lambda x: 0.0, lambda x: 1e-9, 0.0, contract, tracing=False)["feedback"]["status"] == "FAILURE"
    assert observe(lambda x: 1.0, lambda x: 1.000000001, 0.0, contract, tracing=False)["feedback"]["status"] == "PASS"
    assert observe(lambda x: -0.0, lambda x: 0.0, 0.0, contract, tracing=False)["feedback"]["status"] == "PASS"
