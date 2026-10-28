"""Read-only gate for publishing the existing, immutable E7 public files.

This verifies an existing GitHub release. It does not rebuild, tag, publish,
infer PyPI ownership, or turn a missing registry lookup into a name reservation.
"""
import argparse
import configparser
from email.parser import BytesParser
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

REPOSITORY = "hibou04-ops/antemortem-structural-lab"
NAME, VERSION, TAG = "antemortem-structural-lab", "0.7.0a1", "v0.7.0a1"
SOURCE_COMMIT = "2edfb1230bd8519072845d9b9b0e2d4c42ab3837"
TAG_OBJECT = "5a7e9c74cc2aa898e794ef75507d2bc7ad27e566"
RELEASE_ID = 425408252
PREFIX = "antemortem_structural_lab-" + VERSION
PACKAGES = {
    PREFIX + "-py3-none-any.whl": "c15fed1666eac1a1e0878413059de212150eb98f77a919967cc8a7bd84cab979",
    PREFIX + ".tar.gz": "3643ca44dda5ef3feb44a15fea10618421e11e683358ce47dc2e164ec68504e7",
}
CHECKSUM_SHA256 = "c1bd735880170b9eac31d58f866625945b631d1de3a3a3a19e91bb3cc717d480"
API = "https://api.github.com/repos/" + REPOSITORY
ASSETS = "https://github.com/" + REPOSITORY + "/releases/download/" + TAG + "/"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def read_json(url, *, missing=False):
    # Public reads need no account token, so redirects never forward a secret.
    request = Request(url, headers={"User-Agent": "Antemortem-public-distribution-verifier"})
    try:
        with urlopen(request, timeout=45) as response:
            data = response.read(4 * 1024 * 1024 + 1)
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("public metadata exceeded its size bound")
    return json.loads(data)


def source_files(root):
    if (git(root, "rev-parse", "refs/tags/" + TAG).decode().strip() != TAG_OBJECT
            or git(root, "rev-parse", TAG + "^{commit}").decode().strip() != SOURCE_COMMIT):
        raise ValueError("the immutable E7 tag object or source commit changed")
    payload = git(root, "archive", "--format=tar", SOURCE_COMMIT)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        files = {member.name: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile()}
    original_manifest = files["docs/E7_CODE_FREEZE.json"]
    if (root / "docs/E7_CODE_FREEZE.json").read_bytes() != original_manifest:
        raise ValueError("historical E7 manifest was modified")
    manifest = json.loads(original_manifest)
    if manifest["product_files"] != 57:
        raise ValueError("historical E7 product inventory changed")
    for name, expected in manifest["product"].items():
        if digest(files[name]) != expected:
            raise ValueError("tagged E7 product differs from its original commitment")
    # Original checker stays intact; the current branch must still match all 57
    # evaluated product bytes, even when channel documentation has changed.
    path = root / "scripts/check-e7-freeze.py"
    if path.read_bytes() != files["scripts/check-e7-freeze.py"]:
        raise ValueError("the historical E7 checker was modified")
    spec = importlib.util.spec_from_file_location("preserved_e7_commitment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify(root, manifest)
    return files


def validate_release_metadata(release):
    if (release.get("id") != RELEASE_ID or release.get("tag_name") != TAG
            or release.get("draft") is not False or release.get("prerelease") is not True):
        raise ValueError("the approved public E7 prerelease differs")
    entries = release.get("assets", [])
    expected = {**PACKAGES, "SHA256SUMS.txt": CHECKSUM_SHA256}
    if len(entries) != len(expected) or {entry["name"] for entry in entries} != set(expected):
        raise ValueError("unexpected public E7 asset set")
    for entry in entries:
        if (entry.get("digest") != "sha256:" + expected[entry["name"]]
                or entry.get("browser_download_url") != ASSETS + entry["name"]):
            raise ValueError("public E7 asset identity or digest differs")


def download_assets(folder):
    release = read_json(API + "/releases/" + str(RELEASE_ID))
    validate_release_metadata(release)
    ref = read_json(API + "/git/ref/tags/" + TAG)
    if ref.get("object") != {"sha": TAG_OBJECT, "type": "tag", "url": API + "/git/tags/" + TAG_OBJECT}:
        raise ValueError("public E7 annotated tag changed")
    tag = read_json(API + "/git/tags/" + TAG_OBJECT)
    if tag.get("object", {}).get("type") != "commit" or tag["object"]["sha"] != SOURCE_COMMIT:
        raise ValueError("public E7 tag source changed")
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("download directory must be empty; preserve earlier verification files")
    checksum_data = None
    for name in [*PACKAGES, "SHA256SUMS.txt"]:
        # Only known public URLs, no Authorization header, no external program
        # collection or execution. Each download is checked before proceeding.
        with urlopen(ASSETS + name, timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("public asset exceeded its download bound")
        expected = PACKAGES.get(name, CHECKSUM_SHA256)
        if digest(data) != expected:
            raise ValueError("downloaded public E7 asset hash differs")
        if name == "SHA256SUMS.txt":
            checksum_data = data
        else:
            with (folder / name).open("xb") as stream:
                stream.write(data)
    return {"release": release, "checksum_data": checksum_data}


def safe_name(name):
    path = PurePosixPath(name)
    if not name or not path.parts or "\\" in name or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise ValueError("unsafe archive member path")
    return name


def archive_files(path):
    result = {}
    size = 0
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 4096:
                raise ValueError("archive member bound exceeded")
            for item in members:
                name = safe_name(item.filename)
                if item.is_dir():
                    continue
                kind = (item.external_attr >> 16) & 0o170000
                if kind not in (0, 0o100000):
                    raise ValueError("archive links or special files are forbidden")
                size += item.file_size
                if size > MAX_ARCHIVE_BYTES or name in result:
                    raise ValueError("oversize or duplicate archive member")
                result[name] = archive.read(item)
    else:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            if len(members) > 4096:
                raise ValueError("archive member bound exceeded")
            for item in members:
                name = safe_name(item.name)
                if item.isdir():
                    continue
                if not item.isfile():
                    raise ValueError("archive links or special files are forbidden")
                size += item.size
                if size > MAX_ARCHIVE_BYTES or name in result:
                    raise ValueError("oversize or duplicate archive member")
                result[name] = archive.extractfile(item).read()
    return result


def verify_metadata(raw):
    metadata = BytesParser().parsebytes(raw)
    if metadata.get("Name") != NAME or metadata.get("Version") != VERSION:
        raise ValueError("distribution Name or Version differs")


def verify_package_contents(folder, files, *, expected_hashes=None):
    expected_hashes = PACKAGES if expected_hashes is None else expected_hashes
    paths = list(folder.iterdir())
    if {p.name for p in paths} != set(expected_hashes) or any(not p.is_file() or p.is_symlink() for p in paths):
        raise ValueError("publish directory must contain exactly the approved wheel and sdist")
    for name, expected in expected_hashes.items():
        if digest((folder / name).read_bytes()) != expected:
            raise ValueError("distribution file hash differs")
    inspector_path = Path(__file__).with_name("check-public-scope.py")
    spec = importlib.util.spec_from_file_location("preserved_public_scope", inspector_path)
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    runtime = {name for name in files if name.startswith("tomolab/") and name.endswith(".py")}
    wheel = archive_files(folder / (PREFIX + "-py3-none-any.whl"))
    dist_info = PREFIX + ".dist-info/"
    share = PREFIX + ".data/data/share/antemortem-structural-lab/"
    verify_metadata(wheel[dist_info + "METADATA"])
    config = configparser.ConfigParser()
    config.read_string(wheel[dist_info + "entry_points.txt"].decode("utf-8"))
    if config["console_scripts"].get("tomolab") != "tomolab.cli:main":
        raise ValueError("wheel CLI entry point differs")
    if {name for name in wheel if name.startswith("tomolab/")} != runtime:
        raise ValueError("wheel runtime module inventory differs from the tagged source")
    metadata_names = {"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD", "licenses/LICENSE"}
    for name, data in wheel.items():
        inspector.inspect(name, data)
        if name.startswith(dist_info) and name[len(dist_info):] in metadata_names:
            continue
        source_name = name[len(share):] if name.startswith(share) else name
        if source_name not in files or data != files[source_name]:
            raise ValueError("wheel member differs from tagged public source: " + name)
    sdist = archive_files(folder / (PREFIX + ".tar.gz"))
    source_prefix = PREFIX + "/"
    if any(not name.startswith(source_prefix) for name in sdist):
        raise ValueError("unexpected source distribution root")
    sdist = {name[len(source_prefix):]: value for name, value in sdist.items()}
    verify_metadata(sdist["PKG-INFO"])
    required = runtime | {"pyproject.toml", "README.md", "README.ko.md", "docs/E7_CODE_FREEZE.json"}
    if not required <= set(sdist):
        raise ValueError("sdist omits tagged product or provenance files")
    project = tomllib.loads(sdist["pyproject.toml"].decode("utf-8"))["project"]
    if project["name"] != NAME or project["version"] != VERSION:
        raise ValueError("sdist project metadata differs")
    generated = {"PKG-INFO", "setup.cfg"} | {"antemortem_structural_lab.egg-info/" + name for name in
        ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt")}
    for name, data in sdist.items():
        inspector.inspect(name, data)
        if name in generated:
            continue
        if name not in files or data != files[name]:
            raise ValueError("sdist member differs from tagged public source: " + name)
    return {"wheel_members": len(wheel), "sdist_members": len(sdist), "runtime_modules": len(runtime)}


def registry_state(document):
    if document is None:
        return {"status": "PROJECT_LOOKUP_404_NOT_NAME_RESERVATION", "publish_required": True}
    if document.get("info", {}).get("name") != NAME:
        raise ValueError("registry project name differs")
    entries = document.get("releases", {}).get(VERSION)
    if entries is None:
        return {"status": "VERSION_NOT_PRESENT_OWNERSHIP_MUST_BE_VERIFIED_SEPARATELY", "publish_required": True}
    if (len(entries) != len(PACKAGES) or {entry["filename"] for entry in entries} != set(PACKAGES)
            or any(entry.get("yanked") or entry.get("digests", {}).get("sha256") != PACKAGES[entry["filename"]] for entry in entries)):
        raise ValueError("registry version contains conflicting or incomplete files; nothing will be overwritten")
    return {"status": "ALREADY_PUBLISHED_IDENTICAL_FILES", "publish_required": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--check-registry", action="store_true")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    if args.github_output and not (args.download and args.check_registry):
        raise ValueError("publication output requires live release and registry verification")
    root = Path(__file__).resolve().parents[1]
    files = source_files(root)
    if args.download:
        downloaded = download_assets(args.directory)
        checksum_data = downloaded["checksum_data"]
        if digest(checksum_data) != CHECKSUM_SHA256:
            raise ValueError("public checksum file differs")
        parsed = {}
        for line in checksum_data.decode("ascii").splitlines():
            sha, name = line.split("  ", 1)
            if name in parsed or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("invalid public checksum entry")
            parsed[name] = sha
        if parsed != PACKAGES:
            raise ValueError("public checksum package mapping differs")
    counts = verify_package_contents(args.directory, files)
    registry = (registry_state(read_json("https://pypi.org/pypi/" + NAME + "/json", missing=True))
                if args.check_registry else {"status": "NOT_CHECKED", "publish_required": None})
    receipt = {"schema": "antemortem-pypi-existing-release-verification-v1", "status": "PASS",
        "source_tag": TAG, "source_tag_object": TAG_OBJECT, "source_commit": SOURCE_COMMIT,
        "workflow_commit": os.environ.get("GITHUB_SHA"), "github_release_id": RELEASE_ID,
        "github_release_live_verified": args.download, "package_sha256": PACKAGES,
        "public_checksum_file_sha256": CHECKSUM_SHA256, "original_and_current_product_files": 57,
        "public_checksum_file_text": checksum_data.decode("ascii") if args.download else None,
        "package_contents": counts, "registry": registry, "account_ownership_inferred": False,
        "provenance_scope": "EXISTING_GITHUB_ASSETS_NOT_REBUILT_AND_NOT_NEW_RESEARCH_EVIDENCE",
        "upload_performed": False}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    if args.github_output:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write("publish_required=" + str(registry["publish_required"]).lower() + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
