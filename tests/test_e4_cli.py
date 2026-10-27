import json

import pytest

from tomolab.cli import main
from tomolab.mold.schema import default_spec


def test_ast_cli_checks_without_execution(tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(default_spec(low=-3, high=3)), encoding="utf-8")
    assert main(["constraints-check", "--spec", str(spec), "--expression", "x > 0",
                 "--expression", "x <= 0"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "UNSAT"


@pytest.mark.parametrize("option,value", [("--seed", "-1"), ("--shrink-budget", "4226"), ("--budget", "0")])
def test_invalid_pbt_controls_rejected_before_import(tmp_path, option, value):
    marker = tmp_path / "imported"
    target = tmp_path / "target.py"
    oracle = tmp_path / "oracle.py"
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef implementation(x,y): return x+y\n", encoding="utf-8")
    oracle.write_text("def reference(x,y): return x+y\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(default_spec()), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["pbt-run", str(target), "--oracle-file", str(oracle), "--spec", str(spec),
              "--allow-local-execution", option, value])
    assert exc.value.code == 2
    assert not marker.exists()


def test_pbt_cli_requires_explicit_trust(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["pbt-run", str(tmp_path / "absent.py"), "--oracle-file", str(tmp_path / "oracle.py"),
              "--spec", str(tmp_path / "spec.json")])
    assert exc.value.code == 2
