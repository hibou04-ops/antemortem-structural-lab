"""Verify the unreleased numerical CLI pipeline from a genuinely installed wheel.

Normal CI uses a fresh environment and normal QA dependency installation. The
explicit offline option copies only already-approved installed distributions;
its receipt never calls that a fresh public-index dependency installation.
"""
import argparse
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
    records = []
    dependency_reuse = []
    with tempfile.TemporaryDirectory(prefix="e8r2-installed-wheel-") as folder:
        external = Path(folder).resolve()
        assert not external.is_relative_to(project)
        venv.EnvBuilder(with_pip=True).create(external/"env")
        python = external/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")

        def run(label, *arguments, expected=0):
            completed = subprocess.run([str(python), "-I", "-X", "utf8", *map(str, arguments)],
                cwd=external, env=env, text=True, encoding="utf-8", capture_output=True, timeout=180)
            records.append({"check": label, "returncode": completed.returncode,
                            "expected_success": expected == 0})
            if (completed.returncode == 0) != (expected == 0):
                raise RuntimeError(label+": "+(completed.stderr or completed.stdout)[-6000:])
            return completed.stdout, completed.stderr

        def command(label, *arguments):
            stdout, _ = run(label, "-m", "tomolab", *arguments)
            if stdout.strip():
                return json.loads(stdout)
            if "--output" in arguments:
                return json.loads(Path(arguments[arguments.index("--output")+1]).read_text(encoding="utf-8"))
            raise ValueError(label+": CLI returned no JSON receipt")

        run("base-wheel-offline-install", "-m", "pip", "install", "--no-index", "--no-deps", wheel)
        run("base-pip-check", "-m", "pip", "check")
        stdout, _ = run("installed-version-origin", "-c",
            "import json,sys,inspect,tomolab;from importlib.metadata import version;"
            "print(json.dumps({'version':version('antemortem-structural-lab'),'file':inspect.getfile(tomolab),'prefix':sys.prefix}))")
        identity = json.loads(stdout)
        assert identity["version"] == wheel.name.split("-")[1]
        assert Path(identity["file"]).resolve().is_relative_to((external/"env").resolve())
        run("base-cli-help", "-m", "tomolab", "--help")
        _, missing_qa = run("missing-qa-fails-closed", "-c",
            "from tomolab.discovery.numerical_guidance import generate_numerical_candidates;"
            "generate_numerical_candidates('A',size=1,max_examples=8)", expected=1)
        assert "hypothesis" in missing_qa.lower() and "ModuleNotFoundError" in missing_qa
        if args.reuse_approved_dependencies:
            stdout, _ = run("fresh-environment-library-path", "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])")
            target_library = Path(stdout.strip()).resolve()
            assert target_library.is_relative_to((external/"env").resolve())
            for name in ("hypothesis", "sortedcontainers", "psutil", "z3-solver"):
                installed = distribution(name)
                library = Path(installed.locate_file("")).resolve()
                copied, byte_count = 0, 0
                file_digests = {}
                for item in installed.files or []:
                    source = Path(installed.locate_file(item)).resolve()
                    if not source.is_relative_to(library) or not source.is_file():
                        continue  # Console scripts outside the library are not needed.
                    relative = source.relative_to(library)
                    destination = (target_library/relative).resolve()
                    if not destination.is_relative_to(target_library):
                        raise ValueError("dependency copy escaped fresh library")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    data = destination.read_bytes()
                    assert data == source.read_bytes()
                    file_digests[relative.as_posix()] = hashlib.sha256(data).hexdigest()
                    copied += 1; byte_count += len(data)
                assert copied
                inventory = json.dumps(file_digests, sort_keys=True, separators=(",", ":")).encode()
                dependency_reuse.append({"distribution": name, "version": installed.version,
                    "copied_library_files": copied, "bytes": byte_count,
                    "file_inventory_digest": hashlib.sha256(inventory).hexdigest()})
        else:
            run("fresh-qa-solver-dependency-install", "-m", "pip", "install", f"{wheel}[qa,solver]")
        run("qa-pip-check", "-m", "pip", "check")
        stdout, _ = run("installed-numerical-module-origins", "-c",
            "import json,inspect;from tomolab.discovery import numerical_guidance,numerical_service,numerical_source;"
            "print(json.dumps([inspect.getfile(m) for m in (numerical_guidance,numerical_service,numerical_source)]))")
        origins = json.loads(stdout)
        assert all(Path(path).resolve().is_relative_to((external/"env").resolve()) for path in origins)
        stdout, _ = run("bundled-example-location", "-c", "from tomolab.cli import EXAMPLES;print(EXAMPLES)")
        examples = Path(stdout.strip())
        assert examples.resolve().is_relative_to((external/"env").resolve())
        guide_dir = examples/"numerical"
        for name in ("source-guide.json", "source-approval.json", "source-guide.sha256"):
            assert (guide_dir/name).is_file(), name
        common = ["--seed", "7", "--size", "4", "--max-examples", "128", "--budget", "16", "--shrink-budget", "0"]
        workspace = external/"authored-public-workspace"
        authored = command("authored-preparation-compile-worker-oracle-demo", "numerical-demo",
            "--workspace", workspace, *common)
        assert authored["archive_kind"] == "AUTHORED_PROVIDED_DIAGNOSTICS"
        assert authored["preparation_target_calls"] == authored["preparation_oracle_calls"] == 2
        assert authored["run"]["status"] == "COMPLETE"
        assert authored["allow_release"] is False
        recipe_file, compiled_file = external/"prepared.json", external/"compiled.json"
        prepared = command("standalone-prepare", "numerical-prepare", "--archive", workspace/"archive.json", "--output", recipe_file)
        compiled = command("standalone-compile", "numerical-compile", "--archive", workspace/"archive.json",
            "--recipe", recipe_file, "--output", compiled_file)
        assert prepared["recipe"]["origin_type"] == "SOURCE_CALIBRATED_GUIDANCE"
        assert compiled["artifact"]["source_archive_digest"] == prepared["recipe"]["provenance"]["source_archive_digest"]
        assert json.loads(compiled_file.read_text(encoding="utf-8"))["artifact"] == compiled["artifact"]
        artifact_path, approval_path, pin_path = external/"compiled-guide.json", external/"compiled-approval.json", external/"compiled-guide.sha256"
        artifact_path.write_text(json.dumps(compiled["artifact"]), encoding="utf-8")
        approval_path.write_text(json.dumps(compiled["approval_receipt"]), encoding="utf-8")
        pin_path.write_text(compiled["artifact"]["artifact_digest"]+"\n", encoding="ascii")
        guide_arguments = ["--guide", artifact_path, "--approval", approval_path, "--expected-digest-file", pin_path]
        inspected = command("standalone-inspect-no-execution", "numerical-inspect", *guide_arguments)
        assert inspected["execution"] == "NOT_EXECUTED" and inspected["target_calls"] == inspected["oracle_calls"] == 0
        _, denied = run("explicit-execution-approval-required", "-m", "tomolab", "numerical-run", *guide_arguments, *common, expected=1)
        assert "--allow-local-execution" in denied
        methods = {}
        for method in ("A", "B", "C", "D"):
            result = command("installed-method-"+method, "numerical-run", *guide_arguments,
                "--method", method, "--replays", workspace/"replays.json", "--known-inputs", workspace/"replays.json",
                "--allow-local-execution", *common)
            assert result["status"] == "COMPLETE", result.get("error")
            assert 0 < result["oracle_calls"] == result["target_calls"] <= 16
            assert result["guide_unchanged"] and not result["allow_release"]
            methods[method] = {"target_calls": result["target_calls"], "oracle_calls": result["oracle_calls"],
                "receipt_sha256": result["receipt_sha256"], "status": result["status"]}
        compared = command("installed-four-way-comparison-receipt", "numerical-compare", *guide_arguments,
            "--replays", workspace/"replays.json", "--known-inputs", workspace/"replays.json",
            "--allow-local-execution", *common)
        assert compared["status"] == "COMPLETE" and set(compared["summaries"]) == {"A", "B", "C", "D"}
        assert compared["allow_release"] is False and compared["independent_C"] == 0
        actual = command("bundled-real-compact-guide-functional-run", "numerical-demo", *common)
        assert actual["archive_kind"] == "PREVIOUSLY_APPROVED_REAL_SOURCE_GUIDE"
        assert actual["preparation_target_calls"] == actual["preparation_oracle_calls"] == 0
        assert actual["run"]["status"] == "COMPLETE"
        assert actual["run"]["boundary"]["full_archive_transmitted"] is False
        report = {"schema": "tomolab-e8r2-installed-wheel-verification-v1", "status": "PASS",
            "scope": "FUNCTIONAL_INSTALLED_WHEEL_NOT_RESEARCH", "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "version": identity["version"],
            "isolated_fresh_venv": True, "outside_source_checkout": True,
            "installed_module_origins_confirmed": True, "bundled_numerical_examples_confirmed": True,
            "qa_dependency_installation": "APPROVED_EXISTING_DEPENDENCIES_REUSED_NOT_FRESH_INDEX_INSTALL"
                if args.reuse_approved_dependencies else "FRESH_NORMAL_INDEX_INSTALL",
            "approved_dependency_reuse": dependency_reuse,
            "missing_qa_failed_closed": True, "authored_archive_kind": authored["archive_kind"],
            "authored_preparation_target_calls": authored["preparation_target_calls"],
            "authored_preparation_oracle_calls": authored["preparation_oracle_calls"],
            "standalone_pipeline_methods": methods,
            "actual_public_guide_source_archive_digest": json.loads((guide_dir/"source-guide.json").read_text(encoding="utf-8"))["source_archive_digest"],
            "real_source_archive_validated_in_this_check": False,
            "comparison_is_functional_not_research_batch": True,
            "checks": records, "check_count": len(records), "pypi_uploads": 0,
            "research_final_batch_executed": False, "allow_release": False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
