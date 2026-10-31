"""Verify small authored product cases in fresh wheel/sdist installations.

This does not collect Source data, learn Mold rules, or run research cohorts.
The CP1252 check uses a real stdout pipe without UTF-8 mode or isolation flags
that would ignore PYTHONIOENCODING. Linux results are explicitly simulations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import venv


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(python, workspace, kind, artifact):
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(key, None)
    checks = []

    def invoke(label, argv, cwd=workspace, expected=0, *, cp1252=False):
        env = dict(environment)
        if cp1252:
            env.update(PYTHONIOENCODING="cp1252:strict", PYTHONUTF8="0")
        prefix = [str(python)] if cp1252 else [str(python), "-I", "-X", "utf8"]
        started = time.perf_counter()
        completed = subprocess.run(prefix + list(map(str, argv)), cwd=cwd, env=env,
                                   capture_output=True, timeout=240)
        record = dict(check=label, returncode=completed.returncode,
                      expected_returncode=expected, wall_seconds=time.perf_counter()-started)
        checks.append(record)
        if completed.returncode != expected:
            record["stderr"] = completed.stderr.decode("utf-8", "backslashreplace")[-4000:]
            raise AssertionError(json.dumps(record))
        return completed.stdout.decode("cp1252" if cp1252 else "utf-8")

    invoke("fresh-install", ["-m", "pip", "install", str(artifact)+"[qa]"])
    invoke("pip-check", ["-m", "pip", "check"])
    identity = json.loads(invoke("installed-origin", ["-c",
        "import json,sys,tomolab,importlib.metadata as m;"
        "print(json.dumps({'python':sys.version,'version':m.version('antemortem-structural-lab'),"
        "'origin':tomolab.__file__}))"]))
    origin = Path(identity.pop("origin")).resolve()
    if not origin.is_relative_to((workspace/"env").resolve()):
        raise AssertionError("import did not come from the fresh installed artifact")
    identity["origin_within_fresh_environment"] = True
    help_text = invoke("cp1252-stdout-pipe-help", ["-m", "tomolab", "--help"], cp1252=True)
    if "MRI" not in help_text or "online-run" not in help_text:
        raise AssertionError("help lost its product description or commands")
    invoke("cp1252-subcommand-help", ["-m", "tomolab", "online-run", "--help"], cp1252=True)
    help_mode = "ACTUAL_WINDOWS_CP1252_PIPE" if os.name == "nt" else "LINUX_CP1252_SIMULATION"

    def prepare(name, target, oracle="def reference(point):\n    return point\n", comparison=None):
        case = workspace/name
        case.mkdir()
        (case/"target.py").write_text(target, encoding="utf-8")
        (case/"oracle.py").write_text(oracle, encoding="utf-8")
        contract = dict(kind="int", low=0, high=0)
        if comparison:
            contract["comparison"] = comparison
        (case/"contract.json").write_text(json.dumps(contract), encoding="utf-8")
        return case

    def run(case, name="run", function=None, expected=0):
        argv = ["-m", "tomolab", "online-run", "target.py", "--oracle-file", "oracle.py",
                "--contract", "contract.json", "--usage-ledger", name+"-usage.jsonl",
                "--allow-local-execution", "--budget", "12", "--shrink-budget", "3",
                "--output", name+".json"]
        if function:
            argv += ["--function", function]
        invoke(case.name+":"+name, argv, case, expected)
        payload = json.loads((case/(name+".json")).read_text(encoding="utf-8"))
        if payload["run"]["method"] != "E9_A":
            raise AssertionError("product fixture unexpectedly changed the default method")
        return payload

    def replay(case, name="replay", source="run", function=None, expected=0):
        argv = ["-m", "tomolab", "online-replay", source+".json", "--source", "target.py",
                "--oracle-file", "oracle.py", "--contract", "contract.json",
                "--allow-local-execution", "--output", name+".json"]
        if function:
            argv += ["--function", function]
        invoke(case.name+":"+name, argv, case, expected)
        if expected:
            if (case/(name+".json")).exists():
                raise AssertionError("rejected replay wrote a success receipt")
            return None
        payload = json.loads((case/(name+".json")).read_text(encoding="utf-8"))
        if payload["replay_status"] != "REPRODUCED":
            raise AssertionError("unchanged fixture did not reproduce")
        return payload

    case = prepare("dataclass-module", "from __future__ import annotations\n"
        "from dataclasses import dataclass\n@dataclass\nclass Item:\n    value: int\n"
        "def implementation(point):\n    return Item(point).value\n")
    if run(case)["run"]["outcome"] != "NO_CONFIRMED_FAILURE_WITHIN_BUDGET":
        raise AssertionError("valid dataclass module did not complete normally")
    case = prepare("alias", "def actual_function(point):\n    return point+1\n"
        "implementation=actual_function\n")
    alias = run(case)
    if alias["run"]["outcome"] != "CONFIRMED_FAILURE":
        raise AssertionError("authored faulty alias was not discovered")
    replay(case)
    run(case, "explicit-run", "actual_function")
    replay(case, "explicit-replay", "explicit-run", "actual_function")
    replay(case, "function-drift-rejected", function="actual_function", expected=2)
    (case/"target.py").write_text((case/"target.py").read_text(encoding="utf-8")+"\n# changed\n",
                                 encoding="utf-8")
    replay(case, "file-drift-rejected", expected=2)
    case = prepare("ordinary", "def implementation(point):\n    return point+1\n")
    ordinary = run(case)
    if ordinary["run"]["outcome"] != "CONFIRMED_FAILURE":
        raise AssertionError("ordinary A fixture was not discovered")
    replay(case)
    allowed = prepare("allowed-exception", "def implementation(point):\n    raise ValueError('expected')\n",
        "def reference(point):\n    raise ValueError('expected')\n",
        dict(expected_exceptions=["builtins.ValueError"], exception_policy="match_type"))
    if run(allowed)["run"]["outcome"] != "NO_CONFIRMED_FAILURE_WITHIN_BUDGET":
        raise AssertionError("allowed exception classified as failure")
    error = prepare("oracle-error", "def implementation(point):\n    return point\n",
                    "def reference(point):\n    raise ValueError('unregistered')\n")
    result = run(error, expected=3)["run"]
    if result["outcome"] != "INCONCLUSIVE" or result["oracle_errors"] < 1 or result["confirmed_failures"]:
        raise AssertionError("Oracle error classified as a confirmed Target failure")
    tolerance = dict(absolute=1e-6, relative=0.0)
    zero = prepare("zero-exact", "def implementation(point):\n    return 0.0\n",
                   "def reference(point):\n    return 1e-9\n", tolerance)
    nonzero = prepare("nonzero-tolerance", "def implementation(point):\n    return 1.0\n",
                      "def reference(point):\n    return 1.000000001\n", tolerance)
    if (run(zero)["run"]["outcome"] != "CONFIRMED_FAILURE" or
            run(nonzero)["run"]["outcome"] != "NO_CONFIRMED_FAILURE_WITHIN_BUDGET"):
        raise AssertionError("existing exact-zero/tolerance contract changed")
    return dict(artifact=kind, artifact_sha256=sha(artifact), status="PASS", identity=identity,
                cp1252_mode=help_mode, checks=checks, authored_cases=7,
                source_collection_calls=0, mold_training_runs=0, historical_research_runs=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1]/"dist")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("validation receipt must be new")
    artifacts = [("wheel", list(args.directory.glob("*.whl"))),
                 ("sdist", list(args.directory.glob("*.tar.gz")))]
    if any(len(paths) != 1 for _, paths in artifacts):
        raise ValueError("exactly one candidate wheel and one sdist required")
    results = []
    with tempfile.TemporaryDirectory(prefix="tomolab-product-runtime-") as temporary:
        external = Path(temporary).resolve()
        checkout = Path(__file__).resolve().parents[1]
        if external.is_relative_to(checkout):
            raise ValueError("installed checks must run outside checkout")
        for kind, paths in artifacts:
            workspace = external/kind
            workspace.mkdir()
            venv.EnvBuilder(with_pip=True).create(workspace/"env")
            python = workspace/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")
            results.append(verify(python, workspace, kind, paths[0].resolve()))
    receipt = dict(schema="tomolab-product-runtime-regression-v1", status="PASS",
                   os=platform.system(), python=sys.version, installations=results,
                   outside_checkout=True, research_execution=False, publication=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"status": receipt["status"], "installations": len(results),
                      "checks": sum(len(row["checks"]) for row in results)}))


if __name__ == "__main__":
    main()
