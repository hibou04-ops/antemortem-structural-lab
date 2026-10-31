"""Independent, read-only archive audit. Never import package code or extract archives.

Inputs must be separately downloaded public distributions and public metadata.
This is not the publisher's validation script or a research evaluation.
"""
import argparse
import base64
import configparser
import csv
from email.parser import BytesParser
from email.policy import default
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tomllib
import zipfile

NAME = "antemortem-structural-lab"
VERSION = "0.8.0a1"
SOURCE = "3ece4df3bd01abe6aae58ef8a01bf4b01515f689"
PREFIX = "antemortem_structural_lab-" + VERSION
NAMES = {"wheel": PREFIX + "-py3-none-any.whl", "sdist": PREFIX + ".tar.gz"}
LIMIT = 64 * 1024 * 1024
PRIVATE_PATH = re.compile(r"(^|/)(?:\.git(?:/|$)|\.env(?:\.[^/]*)?(?:/|$)|PRIVATE_[^/]*(?:/|$)|research/e[1-9](?:[-_][^/]*)?(?:/|$)|e[89][-_](?:private|evidence|evaluation)[^/]*/|e8[-_]r[1-4][-_](?:private|evidence|evaluation)[^/]*/)", re.I)
PATTERNS = {
    "github_credential": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,})"),
    "openai_like_credential": re.compile(rb"sk-[A-Za-z0-9_-]{30,}"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "personal_windows_path": re.compile(rb"[A-Za-z]:[/\\]+Users[/\\]+[^/\\\s\"']+", re.I),
    "personal_posix_path": re.compile(rb"/(?:home|Users)/(?:hibou|hibou04)(?:/|\b)", re.I),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or ".." in parts or "\\" in name or ":" in parts[0]:
        raise ValueError("unsafe archive member name")


def load_archive(path):
    result = {}
    total = 0
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            rows = [(row.filename, row.file_size, (row.external_attr >> 16) & 0o170000, row)
                    for row in archive.infolist() if not row.is_dir()]
            for name, size, mode, row in rows:
                safe_name(name)
                if name in result or mode == 0o120000:
                    raise ValueError("duplicate or symbolic-link wheel member")
                if size > LIMIT or total + size > LIMIT:
                    raise ValueError("archive size exceeds audit budget")
                result[name] = archive.read(row)
                total += size
    else:
        with tarfile.open(path, "r:gz") as archive:
            rows = archive.getmembers()
            for row in rows:
                safe_name(row.name)
                if row.isdir():
                    continue
                if not row.isfile() or row.name in result:
                    raise ValueError("non-regular or duplicate sdist member")
                if row.size > LIMIT or total + row.size > LIMIT:
                    raise ValueError("archive size exceeds audit budget")
                result[row.name] = archive.extractfile(row).read()
                total += row.size
        top = {PurePosixPath(name).parts[0] for name in result}
        if top != {PREFIX}:
            raise ValueError("unexpected source distribution root")
        result = {name[len(PREFIX)+1:]: value for name, value in result.items()}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--pypi-json", type=Path, required=True)
    p.add_argument("--github-release-json", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    checks = []
    findings = []
    def check(name, passed, **details):
        checks.append(dict(check=name, passed=bool(passed), **details))
    receipt = dict(schema="tomolab-independent-public-package-audit-v1", version=VERSION,
        source_sha=SOURCE, scope="STATIC_PUBLIC_ARCHIVES_NO_PACKAGE_CODE_EXECUTED", checks=checks,
        findings=findings, limitations=[
            "Pattern scanning is bounded and cannot prove absence of every secret or private datum.",
            "Declared optional dependency metadata is recorded; installation and behavior require a separate audit.",
            "Archive integrity and metadata do not establish research utility, security isolation, or correctness.",
            "Public JSON data is an input to this audit; its transport provenance must be recorded separately."])
    try:
        root = args.source_root.resolve()
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        check("pinned_source_commit", head == SOURCE, actual=head)
        project = tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]
        check("source_distribution_identity", project["name"] == NAME and project["version"] == VERSION)
        current = {p.name for p in args.directory.iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz")}
        check("exact_two_distribution_filenames", current == set(NAMES.values()), observed=sorted(current))
        public = json.loads(args.pypi_json.read_text(encoding="utf-8"))
        release = json.loads(args.github_release_json.read_text(encoding="utf-8"))
        check("pypi_version_identity_not_yanked", public["info"]["name"] == NAME and
              public["info"]["version"] == VERSION and public["info"].get("yanked") is False)
        check("github_public_experimental_prerelease", release["tag_name"] == "v"+VERSION and
              release["draft"] is False and release["prerelease"] is True)
        registry = {row["filename"]: row for row in public["urls"]}
        gh = {row["name"]: row for row in release["assets"]}
        check("pypi_exact_two_files", set(registry) == set(NAMES.values()) and len(public["urls"]) == 2)
        check("github_four_expected_uploaded_assets", set(gh) == set(NAMES.values()) |
              {"SHA256SUMS.txt", "release-manifest.json"} and len(release["assets"]) == 4)
        archives = {}
        license_names = ["LICENSE", *sorted(str(p.relative_to(root).as_posix())
                         for p in (root/"benchmarks/historical/vendor").glob("*-LICENSE.txt"))]
        check("source_four_license_texts", len(license_names) == 4)
        runtime = {str(p.relative_to(root).as_posix()): p.read_bytes() for p in (root/"tomolab").rglob("*.py")}
        all_assets = {}
        for kind, name in NAMES.items():
            path = args.directory/name
            data = path.read_bytes()
            row = registry[name]
            checksum = digest(data)
            check(kind+"_public_registry_byte_hash_size", checksum == row["digests"]["sha256"] and
                  len(data) == row["size"] and row["yanked"] is False,
                  filename=name, sha256=checksum, size=len(data))
            check(kind+"_github_same_hash_size", gh[name]["digest"] == "sha256:"+checksum and
                  gh[name]["size"] == len(data))
            all_assets[kind] = dict(name=name, sha256=checksum, size=len(data))
            members = load_archive(path)
            archives[kind] = members
            check(kind+"_bounded_safe_unique_regular_members", True, files=len(members))
            inventory = {n for n in members if n.startswith("tomolab/") and n.endswith(".py")}
            check(kind+"_exact_runtime_inventory", inventory == set(runtime), modules=len(runtime))
            check(kind+"_runtime_bytes_match_pinned_source", all(members.get(n) == b for n,b in runtime.items()))
            metadata_path = PREFIX+".dist-info/METADATA" if kind == "wheel" else "PKG-INFO"
            raw = members[metadata_path]
            metadata = BytesParser(policy=default).parsebytes(raw)
            body = raw.replace(b"\r\n", b"\n").split(b"\n\n", 1)[1].decode("utf-8")
            source_readme = (root/"README.md").read_text(encoding="utf-8")
            check(kind+"_metadata_name_version_python", metadata["Name"] == NAME and
                  metadata["Version"] == VERSION and metadata["Requires-Python"] == project["requires-python"])
            check(kind+"_english_description_equals_source", body.rstrip("\n") == source_readme.rstrip("\n"))
            check(kind+"_license_expression", metadata["License-Expression"] == project["license"])
            check(kind+"_license_file_inventory", set(metadata.get_all("License-File", [])) == set(license_names))
            check(kind+"_extras_inventory", set(metadata.get_all("Provides-Extra", [])) == set(project["optional-dependencies"]))
            for relative in license_names:
                member = PREFIX+".dist-info/licenses/"+relative if kind == "wheel" else relative
                check(kind+"_license_original_text:"+relative, members.get(member) == (root/relative).read_bytes())
            for dest, patterns in tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["data-files"].items():
                for pattern in patterns:
                    for source in root.glob(pattern):
                        relative = source.relative_to(root).as_posix()
                        member = PREFIX+".data/data/"+dest+"/"+source.name if kind == "wheel" else relative
                        check(kind+"_declared_data_file:"+relative, members.get(member) == source.read_bytes())
            for member, content in members.items():
                if PRIVATE_PATH.search(member) or ("EVIDENCE" in member.upper() and member.lower().endswith(".zip")):
                    findings.append(dict(artifact=kind, member=member, category="private_path_pattern"))
                for label, pattern in PATTERNS.items():
                    if pattern.search(content):
                        findings.append(dict(artifact=kind, member=member, category=label))
            check(kind+"_bounded_private_material_scan", not any(f["artifact"] == kind for f in findings))
        wheel = archives["wheel"]
        entries = configparser.ConfigParser()
        entries.read_string(wheel[PREFIX+".dist-info/entry_points.txt"].decode("utf-8"))
        check("console_entry_point", dict(entries["console_scripts"]) == project["scripts"])
        wheel_info = BytesParser(policy=default).parsebytes(wheel[PREFIX+".dist-info/WHEEL"])
        check("pure_python_wheel_tag", wheel_info["Root-Is-Purelib"] == "true" and
              wheel_info.get_all("Tag") == ["py3-none-any"])
        record_name = PREFIX+".dist-info/RECORD"
        records = list(csv.reader(io.StringIO(wheel[record_name].decode("utf-8"))))
        record_files = [r[0] for r in records]
        check("wheel_record_exact_inventory", len(record_files) == len(set(record_files)) and set(record_files) == set(wheel))
        record_matches = True
        for name, hashed, size in records:
            if name == record_name:
                record_matches = record_matches and hashed == size == ""
            else:
                expected = "sha256="+base64.urlsafe_b64encode(hashlib.sha256(wheel[name]).digest()).rstrip(b"=").decode()
                record_matches = record_matches and hashed == expected and size == str(len(wheel[name]))
        check("wheel_record_all_file_hashes_and_sizes", record_matches)
        for name in ["pyproject.toml", "MANIFEST.in", "README.md", "README.ko.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"]:
            check("sdist_source_document:"+name, archives["sdist"].get(name) == (root/name).read_bytes())
        source_docs = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root/"docs").rglob("*.md")}
        check("sdist_declared_markdown_docs", all(archives["sdist"].get(name) == data
              for name, data in source_docs.items()), documents=len(source_docs))
        check("public_pypi_description_matches_pinned_readme", public["info"]["description"] == (root/"README.md").read_text(encoding="utf-8"))
        receipt.update(assets=all_assets, source_runtime_modules=len(runtime),
            pypi_metadata_sha256=digest(args.pypi_json.read_bytes()),
            github_release_metadata_sha256=digest(args.github_release_json.read_bytes()))
    except Exception as error:
        receipt["input_error"] = dict(type=type(error).__name__, message=str(error)[:500])
    failed = [c["check"] for c in checks if not c["passed"]]
    receipt["failed_checks"] = failed
    receipt["status"] = "PASS_STATIC_PUBLIC_PACKAGE_AUDIT" if not failed and "input_error" not in receipt else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=True)+"\n", encoding="utf-8")
    print(json.dumps({"status":receipt["status"], "checks":len(checks), "failed_checks":failed,
                      "findings":findings, "input_error":receipt.get("input_error")}))
    return int(receipt["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
