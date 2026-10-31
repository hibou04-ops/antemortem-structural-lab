"""Verify prepare-guide/runtime/audit from an isolated installed R3 wheel.

All actual Source inputs in this functional check are reported by digest so
they can be excluded from later development validation. This is not a new
research batch. No upload, tag, release, or production-code change occurs.
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
    parser.add_argument("wheel", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reuse-approved-dependencies", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    if args.wheel:
        wheel = args.wheel.resolve(strict=True)
    else:
        version = tomllib.loads((project/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        matches = list((project/"dist").glob(f"antemortem_structural_lab-{version}-*.whl"))
        if len(matches) != 1:
            raise ValueError("exactly one candidate wheel is required")
        wheel = matches[0].resolve(strict=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    records, reused, runs, source_inputs = [], [], [], set()
    with tempfile.TemporaryDirectory(prefix="e8r3-installed-wheel-") as folder:
        external = Path(folder).resolve()
        assert not external.is_relative_to(project)
        venv.EnvBuilder(with_pip=True).create(external/"env")
        python = external/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")

        def run(label, *arguments, success=True):
            started = time.perf_counter()
            completed = subprocess.run([str(python), "-I", "-X", "utf8", *map(str, arguments)],
                cwd=external, env=env, text=True, encoding="utf-8", capture_output=True, timeout=180)
            records.append(dict(check=label, returncode=completed.returncode,
                expected_success=success, entire_process_wall_seconds=time.perf_counter()-started))
            if (completed.returncode == 0) != success:
                raise RuntimeError(label+": "+(completed.stderr or completed.stdout)[-6000:])
            return completed

        def command(label, *arguments):
            output = external/(label+".json")
            run(label, "-m", "tomolab", *arguments, "--output", output)
            value = json.loads(output.read_text(encoding="utf-8"))
            companion = json.loads(Path(str(output)+".io.json").read_text(encoding="utf-8"))
            assert companion["receipt_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
            assert companion["receipt_bytes"] == len(output.read_bytes())
            return value, companion

        run("base-wheel-offline-install", "-m", "pip", "install", "--no-index", "--no-deps", wheel)
        run("base-pip-check", "-m", "pip", "check")
        result = run("installed-r3-module-origin", "-c",
            "import inspect,json;from importlib.metadata import version;"
            "from tomolab import e8r3_cli;from tomolab.discovery import numerical_response,numerical_prepared;"
            "print(json.dumps({'version':version('antemortem-structural-lab'),"
            "'files':[inspect.getfile(m) for m in (e8r3_cli,numerical_response,numerical_prepared)]}))")
        identity = json.loads(result.stdout)
        assert identity["version"] == wheel.name.split("-")[1]
        assert all(Path(name).resolve().is_relative_to(external/"env") for name in identity["files"])
        if args.reuse_approved_dependencies:
            target = Path(run("fresh-library-location", "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])").stdout.strip()).resolve()
            assert target.is_relative_to(external/"env")
            for name in ("hypothesis", "sortedcontainers", "psutil", "z3-solver"):
                installed = distribution(name)
                library = Path(installed.locate_file("")).resolve()
                inventory = {}
                for item in installed.files or []:
                    source = Path(installed.locate_file(item)).resolve()
                    if not source.is_relative_to(library) or not source.is_file():
                        continue
                    relative = source.relative_to(library)
                    destination = (target/relative).resolve()
                    if not destination.is_relative_to(target):
                        raise ValueError("dependency copy escaped fresh environment")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    data = destination.read_bytes()
                    assert data == source.read_bytes()
                    inventory[relative.as_posix()] = hashlib.sha256(data).hexdigest()
                assert inventory
                reused.append(dict(distribution=name, version=installed.version, files=len(inventory),
                    inventory_sha256=hashlib.sha256(json.dumps(inventory, sort_keys=True,
                        separators=(",", ":")).encode()).hexdigest()))
        else:
            run("fresh-normal-qa-solver-install", "-m", "pip", "install", f"{wheel}[qa,solver]")
        run("qa-pip-check", "-m", "pip", "check")
        archive = external/"authored-public-archive.json"
        # The only preparation Source calls are these two already-published
        # diagnostics. This invokes the installed helper without running a demo.
        prepared_fixture = run("installed-authored-public-archive", "-c",
            "import json,sys;from pathlib import Path;from tomolab.e8r2_cli import functional_archive;"
            "from tomolab.discovery.numerical_guidance import numerical_input_digest;"
            "Path(sys.argv[1]).write_text(json.dumps(functional_archive()),encoding='utf-8');"
            "print(json.dumps([numerical_input_digest({'a':[v]*3,'b':[v]*3}) for v in (0.1,0.25)]))",
            archive)
        preparation_inputs = json.loads(prepared_fixture.stdout)
        source_inputs.update(preparation_inputs)
        prepared_dir, approval_state = external/"prepared-guide", external/"trusted-host-approval.json"
        prepared, prepared_io = command("installed-prepare-guide", "numerical-prepare-guide",
            "--archive", archive, "--prepared-dir", prepared_dir, "--approval-state", approval_state)
        preparation = prepared["result"]
        pin = preparation["artifact_digest"]
        assert preparation["metrics"]["full_archive_validation_invocations"] == 2
        assert preparation["metrics"]["calibration_invocations"] == 2
        assert preparation["metrics"]["compilation_invocations"] == 1
        common = ["--seed", "7", "--size", "3", "--max-examples", "64",
                  "--budget", "12", "--shrink-budget", "0", "--allow-local-execution"]
        guided = ["--method", "D", "--prepared-dir", prepared_dir,
                  "--approval-state", approval_state, "--expected-digest", pin]
        for profile, method in (("runtime", "D"), ("audit", "D"), ("runtime", "B")):
            label = "installed-"+profile+"-"+method
            outer, io = command(label, "numerical-"+profile, *(guided if method == "D" else ["--method", "B"]), *common)
            execution = outer["result"]
            if method == "D":
                assert execution["prepared_load"]["full_archive_validation_invocations"] == 0
                assert execution["prepared_load"]["calibration_invocations"] == 0
                assert execution["prepared_load"]["compilation_invocations"] == 0
                execution = execution["run"]
            assert execution["status"] == "COMPLETE", execution.get("error")
            assert execution["verification_profile"] == profile
            assert execution["primary_generation_executions"] == 1
            assert execution["reference_generation_executions"] == int(profile == "audit")
            assert execution["response_validation_status"] == "PASS"
            assert execution["equivalence_check_status"] == (
                "PASS_FULL_STRUCTURED_SEMANTICS" if profile == "audit" else "NOT_RUN_IN_RUNTIME")
            assert 0 < execution["target_calls"] == execution["oracle_calls"] <= 12
            if method == "B":
                assert execution["guide_digest"] is None
                assert execution["artifact_validation_status"] == "NOT_APPLICABLE_BASELINE_NO_GUIDE"
            inputs = [row["input_digest"] for row in execution["rows"]]
            source_inputs.update(inputs)
            runs.append(dict(method=method, profile=profile, status=execution["status"],
                target_calls=execution["target_calls"], oracle_calls=execution["oracle_calls"],
                source_input_digests=inputs, verification=execution["r3"], io=io))
        assert runs[0]["verification"]["candidate_semantic_digest"] == runs[1]["verification"]["candidate_semantic_digest"]
        report = dict(schema="tomolab-e8r3-installed-wheel-verification-v1", status="PASS",
            scope="FUNCTIONAL_INSTALLED_WHEEL_NOT_RESEARCH_BATCH", wheel=wheel.name,
            wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), version=identity["version"],
            isolated_fresh_venv=True, outside_source_checkout=True,
            installed_r3_module_origins_confirmed=True, runs=runs,
            qa_dependency_installation="APPROVED_EXISTING_DEPENDENCIES_REUSED_NOT_FRESH_INDEX_INSTALL"
                if args.reuse_approved_dependencies else "FRESH_NORMAL_INDEX_INSTALL",
            dependency_reuse=reused, preparation=preparation, preparation_io=prepared_io,
            preparation_target_calls=2, preparation_oracle_calls=2,
            preparation_source_input_digests=preparation_inputs,
            all_functional_source_input_digests=sorted(source_inputs),
            exclude_from_subsequent_source_validation=True,
            actual_source_calls=2+sum(item["target_calls"] for item in runs),
            actual_oracle_calls=2+sum(item["oracle_calls"] for item in runs),
            historical_source_archive_replayed=False, checks=records,
            pypi_uploads=0, research_final_batch_executed=False, allow_release=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
