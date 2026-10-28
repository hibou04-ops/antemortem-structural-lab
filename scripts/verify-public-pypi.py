"""Redownload the real public PyPI files and verify separate fresh installations.

No GitHub distribution or source checkout substitutes for the registry downloads.
Only public, authored functional fixtures run; no consumed research evaluation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
import venv


def release_verifier():
    path = Path(__file__).with_name("verify-pypi-release.py")
    spec = importlib.util.spec_from_file_location("immutable_public_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NotVisibleYet(ValueError):
    pass


def version_files(document, release):
    if document is None:
        raise NotVisibleYet("public version lookup is not visible yet")
    if document.get("info", {}).get("name") != release.NAME or document["info"].get("version") != release.VERSION:
        raise ValueError("public registry Name or Version differs")
    entries = document.get("urls", [])
    names = [item["filename"] for item in entries]
    if len(set(names)) != len(names) or not set(names) <= set(release.PACKAGES):
        raise ValueError("unexpected public PyPI file set")
    for item in entries:
        if item.get("yanked") or item.get("digests", {}).get("sha256") != release.PACKAGES[item["filename"]]:
            raise ValueError("public PyPI file hash differs or is yanked")
        url = urlsplit(item["url"])
        if (url.scheme != "https" or url.hostname != "files.pythonhosted.org" or url.port not in (None, 443)
                or url.username is not None or url.password is not None or url.fragment):
            raise ValueError("public distribution URL must be an official PyPI file URL")
    if set(names) != set(release.PACKAGES):
        raise NotVisibleYet("not all expected public files are visible yet")
    return {item["filename"]: item["url"] for item in entries}


def await_version(release, *, sleep=time.sleep):
    attempts = []
    for delay in (0, 1, 2, 4, 8):
        if delay:
            sleep(delay)
        document = release.read_json("https://pypi.org/pypi/" + release.NAME + "/" + release.VERSION + "/json", missing=True)
        try:
            urls = version_files(document, release)
        except NotVisibleYet:
            attempts.append("VERSION_OR_FILE_NOT_VISIBLE")
            continue
        return urls, attempts + ["VISIBLE_AND_HASH_MATCHED"]
    raise ValueError("public PyPI readback did not become visible; publishing was not retried")


def download_public_files(folder, urls, release):
    folder.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, url in urls.items():
        with urlopen(url, timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != release.PACKAGES[name]:
            raise ValueError("fresh public PyPI file differs from the verified GitHub file")
        with (folder / name).open("xb") as stream:
            stream.write(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    return hashes


def verify_installations(folder, release):
    records, environments = [], []
    env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_INDEX_URL="https://pypi.org/simple",
        PIP_NO_INPUT="1", PYTHONIOENCODING="utf-8")
    env.pop("PIP_EXTRA_INDEX_URL", None)
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="public-pypi-install-") as temporary:
        outside = Path(temporary)
        def run(label, command, *, parse=False):
            tick = time.perf_counter()
            process = subprocess.run(command, cwd=outside, env=env, capture_output=True,
                text=True, encoding="utf-8", timeout=240)
            records.append({"check": label, "returncode": process.returncode,
                "wall_seconds": time.perf_counter() - tick,
                "stdout_sha256": hashlib.sha256(process.stdout.encode()).hexdigest()})
            if process.returncode:
                raise RuntimeError(label + ": " + (process.stderr or process.stdout)[-2000:])
            return json.loads(process.stdout) if parse else process.stdout
        for kind in ("wheel", "sdist"):
            root = outside / kind
            venv.EnvBuilder(with_pip=True).create(root)
            python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            cli = root / ("Scripts/tomolab.exe" if os.name == "nt" else "bin/tomolab")
            package_name = next(name for name in release.PACKAGES if name.endswith(".whl") == (kind == "wheel"))
            requirement = outside / (kind + "-requirement.txt")
            requirement.write_text(release.NAME + "==" + release.VERSION + " --hash=sha256:" + release.PACKAGES[package_name] + "\n", encoding="ascii")
            def py(label, *arguments, parse=False):
                return run(kind + "-" + label, [str(python), "-I", "-X", "utf8", *arguments], parse=parse)
            # Download through the public index again for installation, forcing
            # the selected wheel/sdist and its exact approved file hash. The
            # standalone urllib downloads above are independently retained too.
            binary = "--only-binary=:all:" if kind == "wheel" else "--no-binary=" + release.NAME
            py("public-index-hash-pinned-install", "-m", "pip", "install", "--no-cache-dir", "--no-deps", "--require-hashes", binary, "-r", str(requirement))
            origin_code = ("import json,sys;from pathlib import Path;import tomolab;from importlib.metadata import version;"
                "assert version('antemortem-structural-lab')=='0.7.0a1';"
                "assert Path(tomolab.__file__).resolve().is_relative_to(Path(sys.prefix).resolve());"
                "print(json.dumps({'version':version('antemortem-structural-lab'),'origin':'FRESH_INSTALLED_VENV_OUTSIDE_SOURCE'}))")
            origin = py("installed-import-and-version", "-c", origin_code, parse=True)
            # Literal documentation commands are also exercised. Their base
            # requirement is already installed by the stricter hash-pinned run;
            # record that distinction instead of claiming two cold installs.
            py("documented-version-install-already-installed", "-m", "pip", "install", release.NAME + "==" + release.VERSION)
            py("base-pip-check", "-m", "pip", "check")
            run(kind + "-console-help", [str(cli), "--help"])
            py("module-help", "-m", "tomolab", "--help")
            demo = py("base-authored-demo", "-m", "tomolab", "demo", "--mode", "cross", "--budget", "12", parse=True)
            if demo["status"] != "ORACLE_CONTRADICTION_FOUND":
                raise ValueError("the installed public base fixture did not run as specified")
            py("documented-qa-solver-install", "-m", "pip", "install", release.NAME + "[qa,solver]==" + release.VERSION)
            py("qa-pip-check", "-m", "pip", "check")
            examples = py("installed-public-example-location", "-c", "from tomolab.cli import EXAMPLES; print(EXAMPLES)").strip()
            constraints = py("installed-z3-constraint-check", "-m", "tomolab", "constraints-check", "--spec",
                str(Path(examples) / "mold/spec.json"), "--expression", "x + y == 0", "--solver", "z3", parse=True)
            if constraints["status"] != "SAT":
                raise ValueError("the installed optional solver did not execute the public fixture")
            knowledge = py("qa-authored-knowledge-demo", "-m", "tomolab", "knowledge-demo", "--budget", "16",
                "--guidance-budget", "4", "--pool-size", "16", "--shrink-budget", "16", parse=True)
            if (knowledge["status"] != "COUNTEREXAMPLE_FOUND" or knowledge["counterexample"]["replay"] != "MATCHED_TWICE"
                    or knowledge["final_feedback_allowed"] is not False):
                raise ValueError("the installed public QA fixture did not run as specified")
            py("post-qa-installed-origin", "-c", origin_code, parse=True)
            environments.append({"distribution": kind, "version": origin["version"], "origin": origin["origin"],
                "public_index_install": True, "exact_file_hash_required": release.PACKAGES[package_name],
                "independent_file_redownload_sha256": hashlib.sha256((folder / package_name).read_bytes()).hexdigest(),
                "base_fixture": demo["status"], "qa_fixture": knowledge["status"],
                "solver_fixture": constraints["status"],
                "scope": "PUBLIC_AUTHORED_FUNCTIONAL_FIXTURES_NOT_RESEARCH_EVALUATION"})
    return {"checks": records, "environments": environments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    release = release_verifier()
    root = Path(__file__).resolve().parents[1]
    files = release.source_files(root)
    urls, attempts = await_version(release)
    hashes = download_public_files(args.directory, urls, release)
    contents = release.verify_package_contents(args.directory, files)
    installs = verify_installations(args.directory, release)
    receipt = {"schema": "antemortem-public-pypi-install-verification-v1", "status": "PASS",
        "name": release.NAME, "version": release.VERSION, "source_tag": release.TAG,
        "source_commit": release.SOURCE_COMMIT, "workflow_commit": os.environ.get("GITHUB_SHA"),
        "public_version_url": "https://pypi.org/project/" + release.NAME + "/" + release.VERSION + "/",
        "readback_attempts": attempts, "download_source": "PUBLIC_PYPI_FILES_PYTHONHOSTED_ORG",
        "download_sha256": hashes, "github_public_file_hashes_equal": hashes == release.PACKAGES,
        "downloaded_package_contents": contents, "installation": installs,
        "source_checkout_import": False, "research_evaluation_rerun": False,
        "project_ownership_inferred_from_package_author": False, "upload_performed": False}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
