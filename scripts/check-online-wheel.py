"""Outside-checkout functional Source -> Mold -> online Target verification.

This authored CLI smoke test does not rerun the registered research comparison.
"""
import argparse
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tomllib
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-approved-dependencies", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("installed-wheel receipt must be new")
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root/"pyproject.toml").read_text())["project"]["version"]
    wheels = list((root/"dist").glob(f"antemortem_structural_lab-{version}-*.whl"))
    if len(wheels) != 1:
        raise ValueError("exactly one current candidate wheel required")
    wheel = wheels[0].resolve()
    records, dependencies = [], []
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="online-wheel-") as temporary:
        external = Path(temporary).resolve()
        assert not external.is_relative_to(root)
        venv.EnvBuilder(with_pip=True).create(external/"env")
        python = external/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")
        def run(label, *arguments, success=True):
            tick = time.perf_counter()
            done = subprocess.run([str(python), "-I", "-X", "utf8", *map(str, arguments)],
                cwd=external, env=env, text=True, encoding="utf-8", capture_output=True, timeout=240)
            records.append(dict(check=label, returncode=done.returncode,
                expected_success=success, process_wall_seconds=time.perf_counter()-tick))
            if (done.returncode == 0) != success:
                raise RuntimeError(label+": "+(done.stderr or done.stdout)[-5000:])
            return done.stdout
        def command(label, *arguments):
            output = external/(label+".json")
            run(label, "-m", "tomolab", *arguments, "--output", output)
            value = json.loads(output.read_text())
            io = json.loads(Path(str(output)+".io.json").read_text())
            assert io["receipt_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
            return value, output
        run("base-offline-install", "-m", "pip", "install", "--no-index", "--no-deps", wheel)
        origin = json.loads(run("installed-module-origin", "-c",
            "import inspect,json;from tomolab import online_cli;from tomolab.discovery import online_engine,online_learning;"
            "print(json.dumps([inspect.getfile(m) for m in (online_cli,online_engine,online_learning)]))"))
        assert all(Path(p).resolve().is_relative_to(external/"env") for p in origin)
        for command_name in ("online-run", "online-learn", "online-demo"):
            run("help-"+command_name, "-m", "tomolab", command_name, "--help")
        if args.reuse_approved_dependencies:
            target = Path(run("venv-library", "-c", "import sysconfig;print(sysconfig.get_path('purelib'))").strip())
            assert target.resolve().is_relative_to(external/"env")
            for name in ("hypothesis", "sortedcontainers"):
                installed, inventory = distribution(name), {}
                library = Path(installed.locate_file("")).resolve()
                for item in installed.files or []:
                    source = Path(installed.locate_file(item)).resolve()
                    if not source.is_relative_to(library) or not source.is_file():
                        continue
                    relative = source.relative_to(library)
                    destination = (target/relative).resolve()
                    if not destination.is_relative_to(target.resolve()):
                        raise ValueError("dependency copy escaped fresh environment")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    assert source.read_bytes() == destination.read_bytes()
                    inventory[relative.as_posix()] = hashlib.sha256(destination.read_bytes()).hexdigest()
                dependencies.append(dict(name=name, version=installed.version, files=len(inventory)))
        else:
            run("normal-index-qa-install", "-m", "pip", "install", f"{wheel}[qa]")
        run("pip-check", "-m", "pip", "check")
        examples = Path(run("installed-examples", "-c", "from tomolab.cli import EXAMPLES;print(EXAMPLES)").strip())/"online"
        assert examples.resolve().is_relative_to(external/"env")
        shared = ("--oracle-file", examples/"oracle.py", "--contract", examples/"contract.json",
                  "--budget", "32", "--shrink-budget", "6", "--seed", "7")
        run("local-execution-consent-required", "-m", "tomolab", "online-run", examples/"source.py",
            *shared, "--method", "B", "--usage-ledger", external/"denied-usage.jsonl",
            "--output", external/"denied.json", success=False)
        assert not (external/"denied-usage.jsonl").exists()
        source, source_path = command("collect-source", "online-run", examples/"source.py", *shared,
            "--method", "B", "--usage-ledger", external/"usage.jsonl", "--allow-local-execution")
        assert source["run"]["first_confirmed_failure"] is not None
        learned, _ = command("learn-mold", "online-learn", "--observations", source_path,
            "--mold", external/"mold.json")
        assert learned["rules"] > 0 and learned["mold_bytes"] <= 10240
        target, _ = command("run-new-target", "online-run", examples/"target.py", *shared,
            "--method", "D", "--mold", external/"mold.json", "--expected-digest", learned["mold_digest"],
            "--usage-ledger", external/"usage.jsonl", "--allow-local-execution")
        assert target["run"]["first_confirmed_failure"] is not None
        assert target["execution_profile"]["cross_target_feedback"] is False
        assert target["allow_release"] is False
        no_mold, _ = command("C-without-mold", "online-run", examples/"target.py", *shared,
            "--method", "C", "--usage-ledger", external/"functional-C-usage.jsonl", "--allow-local-execution")
        assert no_mold["run"]["first_confirmed_failure"] is not None
        run("bad-digest-denied", "-m", "tomolab", "online-run", examples/"target.py", *shared,
            "--method", "D", "--mold", external/"mold.json", "--expected-digest", "0"*64,
            "--usage-ledger", external/"bad-usage.jsonl", "--allow-local-execution",
            "--output", external/"bad.json", success=False)
        assert not (external/"bad-usage.jsonl").exists()
        replay, _ = command("C-repeat-token", "online-run", examples/"target.py", *shared,
            "--method", "C", "--usage-ledger", external/"functional-repeat-usage.jsonl", "--allow-local-execution")
        def semantic(value):
            return [(r["input_digest"], r["status"], r["origin"]) for r in value["run"]["observations"]]
        assert semantic(replay) == semantic(no_mold)
        empty_observations = external/"empty-observations.json"
        empty_observations.write_text("[]", encoding="utf-8")
        empty, _ = command("learn-empty-mold", "online-learn", "--observations", empty_observations,
                           "--mold", external/"empty-mold.json")
        assert empty["rules"] == 0
        fallback, _ = command("D-empty-mold-fallback", "online-run", examples/"target.py", *shared,
            "--method", "D", "--mold", external/"empty-mold.json", "--expected-digest", empty["mold_digest"],
            "--usage-ledger", external/"functional-empty-D-usage.jsonl", "--allow-local-execution")
        assert semantic(fallback) == semantic(no_mold)
        assert fallback["run"]["target_calls"] == no_mold["run"]["target_calls"]
        assert fallback["run"]["oracle_calls"] == no_mold["run"]["oracle_calls"]
        def common_states(value):
            return [(e.get("common_policy_state_before"), e.get("common_policy_state_after"))
                    for e in value["run"]["events"]]
        assert common_states(fallback) == common_states(no_mold)
        demo, _ = command("D-end-to-end-demo", "online-demo", "--method", "D", "--workspace", external/"demo",
            "--usage-ledger", external/"demo-usage.jsonl", "--budget", "32", "--shrink-budget", "6",
            "--allow-local-execution")
        assert demo["source_learning"]["rules"] > 0
        result = dict(schema="tomolab-online-installed-wheel-v1", status="PASS",
            wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), checks=records,
            dependency_installation="APPROVED_BYTE_REUSE" if args.reuse_approved_dependencies else "NORMAL_INDEX_INSTALL",
            reused_dependencies=dependencies, source_target_pipeline=True, replay_semantics_equal=True,
            empty_mold_C_D_candidate_rng_and_budget_parity=True,
            functional_target_calls=sum(v["run"]["target_calls"] for v in (source,target,no_mold,replay,fallback,demo))+demo["source_learning"]["target_calls"],
            registered_comparison_reexecuted=False, allow_release=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
