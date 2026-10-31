"""Install wheel and sdist outside the checkout; run authored product commands.

Normal CI uses the normal package index for declared optional dependencies and
sdist build requirements. Local byte reuse is explicit and reported separately.
No historical implementation, Source collection or research cohort is run.
"""
import argparse
from email.parser import BytesParser
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifacts(root=ROOT, *, directory=None, expected_version=None):
    root = Path(root)
    project = tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if expected_version is not None and version != expected_version:
        raise ValueError("expected version differs from the approved source metadata")
    folder = Path(directory).resolve(strict=True) if directory else root/"dist"
    wheel = folder/f"antemortem_structural_lab-{version}-py3-none-any.whl"
    sdist = folder/f"antemortem_structural_lab-{version}.tar.gz"
    if {p.name for p in folder.iterdir() if p.is_file()} != {wheel.name, sdist.name}:
        raise ValueError("exactly the current-version wheel and sdist are required")
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("one wheel distribution metadata file required")
        wheel_metadata = BytesParser().parsebytes(archive.read(names[0]))
        for name in ("target.py", "oracle.py", "contract.json"):
            if not any(n.endswith("/examples/product/"+name) for n in archive.namelist()):
                raise ValueError("bundled product example missing from wheel: "+name)
    with tarfile.open(sdist) as archive:
        members = [m for m in archive.getmembers() if len(Path(m.name).parts) == 2 and
                   m.name.endswith("/PKG-INFO") and m.isfile()]
        if len(members) != 1:
            raise ValueError("one sdist root package metadata file required")
        source_metadata = BytesParser().parsebytes(archive.extractfile(members[0]).read())
        for name in ("target.py", "oracle.py", "contract.json"):
            if not any(m.name.endswith("/examples/product/"+name) and m.isfile()
                       for m in archive.getmembers()):
                raise ValueError("bundled product example missing from sdist: "+name)
    for metadata in (wheel_metadata, source_metadata):
        if metadata["Name"] != project["name"] or metadata["Version"] != version:
            raise ValueError("built artifact distribution identity differs")
    return version, wheel.resolve(), sdist.resolve()


def copy_dependencies(python, external, names, run, *, source_python=None):
    """Reuse only installed distribution bytes, including their metadata."""
    target = Path(run("dependency-library", "-c",
        "import sysconfig;print(sysconfig.get_path('purelib'))").strip()).resolve()
    if not target.is_relative_to(external.resolve()):
        raise ValueError("dependency destination escaped fresh environment")
    if source_python:
        code = ("import json,sys;from importlib.metadata import distribution;"
                "print(json.dumps([{'name':n,'version':distribution(n).version,"
                "'library':str(distribution(n).locate_file('')),'files':[str(p)for p in distribution(n).files]}"
                "for n in sys.argv[1:]]))")
        completed = subprocess.run([str(source_python), "-I", "-c", code, *names],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        sources = json.loads(completed.stdout)
    else:
        sources = [dict(name=name, version=distribution(name).version,
            library=str(distribution(name).locate_file("")),
            files=[str(p) for p in distribution(name).files or ()]) for name in names]
    result = []
    for installed in sources:
        name = installed["name"]
        library = Path(installed["library"]).resolve(strict=True)
        inventory = {}
        for item in installed["files"]:
            source = (library/item).resolve()
            if not source.is_relative_to(library) or not source.is_file():
                continue
            relative = source.relative_to(library)
            destination = (target/relative).resolve()
            if not destination.is_relative_to(target):
                raise ValueError("dependency copy escaped fresh environment")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if source.read_bytes() != destination.read_bytes():
                raise ValueError("approved dependency byte copy differs")
            inventory[relative.as_posix()] = sha(destination)
        if not inventory:
            raise ValueError("installed dependency has no reusable bytes: "+name)
        result.append(dict(name=name, version=installed["version"], files=len(inventory),
            inventory_sha256=hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-sha")
    p.add_argument("--directory", type=Path, help="Two exact candidate or independently downloaded public packages")
    p.add_argument("--version", help="Expected public distribution version")
    p.add_argument("--reuse-approved-dependencies", action="store_true")
    p.add_argument("--approved-build-python", type=Path,
                   help="Explicit approved build environment for local sdist-backend byte reuse")
    args = p.parse_args()
    if args.approved_build_python and not args.reuse_approved_dependencies:
        p.error("--approved-build-python is only for explicit local dependency byte reuse")
    if args.output.exists():
        raise FileExistsError("product installation receipt must be new")
    version, wheel, sdist = artifacts(directory=args.directory, expected_version=args.version)
    source_sha = args.source_sha or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.strip()
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact source commit required")
    checks, installed, reused = [], [], []
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1")
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="tomolab-product-install-") as temporary:
        external = Path(temporary).resolve()
        if external.is_relative_to(ROOT):
            raise ValueError("product installation must be outside the checkout")
        for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
            workspace = external/kind
            workspace.mkdir()
            venv.EnvBuilder(with_pip=True).create(workspace/"env")
            python = workspace/"env"/("Scripts/python.exe" if os.name == "nt" else "bin/python")

            def run(label, *argv, success=True):
                tick = time.perf_counter()
                value = subprocess.run([str(python), "-I", "-X", "utf8", *map(str, argv)],
                    cwd=workspace, env=env, text=True, encoding="utf-8", capture_output=True, timeout=300)
                checks.append(dict(check=kind+":"+label, returncode=value.returncode,
                    expected_success=success, process_wall_seconds=time.perf_counter()-tick))
                if (value.returncode == 0) != success:
                    raise RuntimeError(kind+":"+label+": "+(value.stderr or value.stdout)[-5000:])
                return value.stdout if success else value.stdout+value.stderr

            def command(label, *argv):
                path = workspace/(label+".json")
                run(label, "-m", "tomolab", *argv, "--output", path)
                value = json.loads(path.read_text(encoding="utf-8"))
                io = json.loads(Path(str(path)+".io.json").read_text(encoding="utf-8"))
                if io["receipt_sha256"] != sha(path):
                    raise ValueError("CLI export and I/O receipt differ")
                return value, path

            if kind == "sdist" and args.reuse_approved_dependencies:
                reused.extend(copy_dependencies(python, workspace, ("setuptools", "wheel", "packaging"), run,
                                                source_python=args.approved_build_python))
            install = ["-m", "pip", "install", "--no-deps"]
            if kind == "wheel" or args.reuse_approved_dependencies:
                install.append("--no-index")
            if kind == "sdist" and args.reuse_approved_dependencies:
                install.append("--no-build-isolation")
            run("base-install", *install, artifact)
            run("base-pip-check", "-m", "pip", "check")
            metadata = json.loads(run("installed-origin-version", "-c",
                "import inspect,json,importlib.metadata as m;from tomolab import cli,online_cli;"
                "print(json.dumps({'version':m.version('antemortem-structural-lab'),"
                "'origins':[inspect.getfile(x)for x in(cli,online_cli)],'examples':str(cli.EXAMPLES)}))"))
            if metadata["version"] != version or not all(Path(x).resolve().is_relative_to(workspace/"env")
                                                        for x in metadata["origins"]):
                raise ValueError("product import came from outside installed distribution")
            examples = Path(metadata["examples"]).resolve()
            if not examples.is_relative_to(workspace/"env"):
                raise ValueError("examples came from the source checkout")
            product = examples/"product"
            if version not in run("version", "-m", "tomolab", "--version"):
                raise ValueError("CLI version differs from distribution metadata")
            run("help", "-m", "tomolab", "--help")
            run("base-no-hypothesis", "-c", "import importlib.util;assert importlib.util.find_spec('hypothesis') is None")
            denied = workspace/"denied.json"
            denied_ledger = workspace/"denied.jsonl"
            message = run("optional-QA-guidance", "-m", "tomolab", "online-run", product/"target.py",
                "--oracle-file", product/"oracle.py", "--contract", product/"contract.json",
                "--usage-ledger", denied_ledger, "--allow-local-execution", "--output", denied, success=False)
            if "antemortem-structural-lab[qa]" not in message or denied.exists() or denied_ledger.exists():
                raise ValueError("base install must explain QA before target/ledger/output execution")
            if args.reuse_approved_dependencies:
                reused.extend(copy_dependencies(python, workspace,
                    ("hypothesis", "sortedcontainers", "psutil", "z3-solver"), run))
            else:
                run("normal-index-qa-solver-install", "-m", "pip", "install", str(artifact)+"[qa,solver]")
            run("qa-solver-pip-check", "-m", "pip", "check")
            run("qa-solver-imports", "-c", "import hypothesis,psutil,z3;assert z3.Solver().check()==z3.sat")
            demo, _ = command("README-default-demo", "online-demo", "--workspace", workspace/"demo",
                "--usage-ledger", workspace/"demo-usage.jsonl", "--budget", "24", "--shrink-budget", "6",
                "--allow-local-execution")
            source = demo["source_learning"]
            if demo["run"]["method"] != "E9_A" or source.get("enabled") is not False or any(
                    source[name] != 0 for name in ("target_calls", "oracle_calls", "rules")):
                raise ValueError("default product demo must use A without Source collection or learning")
            result, result_path = command("README-product-run", "online-run", product/"target.py",
                "--oracle-file", product/"oracle.py", "--contract", product/"contract.json",
                "--usage-ledger", workspace/"product-usage.jsonl", "--budget", "24", "--shrink-budget", "6",
                "--allow-local-execution")
            if result["run"]["method"] != "E9_A" or not result["run"]["first_confirmed_failure"]:
                raise ValueError("authored product example did not exercise default A and confirmation")
            replay, _ = command("README-product-replay", "online-replay", result_path,
                "--source", product/"target.py", "--oracle-file", product/"oracle.py",
                "--contract", product/"contract.json", "--allow-local-execution")
            if replay.get("status") != "COMPLETE" or replay.get("replay_status") != "REPRODUCED":
                raise ValueError("bound installed-product replay did not reproduce")
            checked = json.loads(run("solver-contract", "-m", "tomolab", "constraints-check", "--spec",
                examples/"mold/spec.json", "--expression", "x + y == 0", "--solver", "z3"))
            if checked["status"] != "SAT":
                raise ValueError("installed solver extra did not satisfy its public contract")
            console = workspace/"env"/("Scripts/tomolab.exe" if os.name == "nt" else "bin/tomolab")
            console_started = time.perf_counter()
            console_result = subprocess.run([str(console), "--version"], cwd=workspace, env=env,
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            checks.append(dict(check=kind+":console-entry-point", returncode=console_result.returncode,
                               expected_success=True, process_wall_seconds=time.perf_counter()-console_started))
            if console_result.returncode or version not in console_result.stdout:
                raise ValueError("installed console entry point differs")
            installed.append(dict(artifact=kind, distribution_version=version,
                module_origins=[Path(x).resolve().relative_to(workspace/"env").as_posix() for x in metadata["origins"]],
                product_example_sha256={name: sha(product/name) for name in ("target.py", "oracle.py", "contract.json")},
                default_method="A", source_collection_calls=0, source_learning_rules=0,
                product_target_calls=result["run"]["target_calls"], product_oracle_calls=result["run"]["oracle_calls"],
                replay_status=replay["replay_status"], export_json_sha256=sha(result_path)))
    receipt = dict(schema="tomolab-product-installation-v1", status="PASS", source_sha=source_sha,
        version=version, wheel_sha256=sha(wheel), sdist_sha256=sha(sdist), checks=checks,
        installations=installed, base_install_verified=True, qa_solver_verified=True,
        sdist_install_verified=True, readme_commands_verified=True, outside_checkout_verified=True,
        default_A_without_source_learning=True,
        dependency_installation="APPROVED_BYTE_REUSE" if args.reuse_approved_dependencies else "NORMAL_INDEX_INSTALL",
        reused_dependencies=reused, registered_research_reexecuted=False, historical_code_executed=False,
        readme_sha256=sha(ROOT/"README.md"), korean_readme_sha256=sha(ROOT/"README.ko.md"),
        product_validation_wall_seconds=time.perf_counter()-started,
        research_allow_release=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2); stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
