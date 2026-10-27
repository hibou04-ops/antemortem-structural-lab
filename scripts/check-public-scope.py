"""Inspect explicit Git files and every wheel/sdist member before publication."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATH = re.compile(r"(^|/)(PRIVATE_[^/]*|research/(e1|e2|e3|e4|e5|e6|e7)(/|$)|SYNC(/|$)|HISTORY(/|$)|e[567]-evaluation(/|$)|final_suite\.py$)", re.I)
SECRET = re.compile(rb"gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,}")
PERSONAL_PATH = re.compile(rb"[A-Za-z]:[/\\]+Users[/\\]+[A-Za-z0-9_.-]+", re.I)


def inspect(name, data):
    if FORBIDDEN_PATH.search(name) or ("EVIDENCE" in name.upper() and name.lower().endswith(".zip")):
        raise ValueError(f"private path: {name}")
    if SECRET.search(data) or PERSONAL_PATH.search(data):
        raise ValueError(f"credential or personal path detected: {name}")


def main():
    # Untracked public additions are included, with ignore rules active. Nothing
    # is staged here; the release operator must review the explicit file list.
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            cwd=ROOT, capture_output=True, check=True)
    names = sorted(set(x for x in result.stdout.decode().split("\0") if x))
    for name in names:
        path = ROOT / name
        if path.is_file():
            inspect(name, path.read_bytes())
    staged = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                            cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    staged = [name for name in staged if name]
    for name in staged:
        data = subprocess.run(["git", "show", ":" + name], cwd=ROOT,
                              capture_output=True, check=True).stdout
        inspect(name, data)
    assets = []
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    expected_assets = {f"antemortem_structural_lab-{version}-py3-none-any.whl",
                       f"antemortem_structural_lab-{version}.tar.gz"}
    actual_assets = {p.name for p in (ROOT / "dist").glob("*") if p.is_file()}
    if actual_assets != expected_assets:
        raise ValueError("Expected exactly the current-version wheel and sdist")
    for path in sorted((ROOT / "dist").glob("*")):
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    inspect(name, archive.read(name))
                assert "tomolab/mold/engine.py" in archive.namelist()
                assert "tomolab/mold/worker.py" in archive.namelist()
                assert "tomolab/discovery/worker.py" in archive.namelist()
                assert "tomolab/discovery/service.py" in archive.namelist()
                assert "tomolab/discovery/temporal_worker.py" in archive.namelist()
                assert "tomolab/discovery/temporal_service.py" in archive.namelist()
                assert "tomolab/discovery/knowledge_worker.py" in archive.namelist()
                assert "tomolab/discovery/knowledge_service.py" in archive.namelist()
                assert "tomolab/discovery/knowledge_store.py" in archive.namelist()
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if member.isfile():
                        inspect(member.name, archive.extractfile(member).read())
        else:
            raise ValueError(f"unexpected release asset: {path.name}")
        assets.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    print(json.dumps({"status": "PASS", "source_files": len(names),
                      "staged_blobs_checked": len(staged), "assets": assets}, indent=2))


if __name__ == "__main__":
    main()
