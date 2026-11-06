"""Verify original E7 distributions against their explicitly mapped Git history.

Publication artifacts and the original verifier remain immutable. This adapter
checks the rewritten refs separately and restores only ten hash-pinned document
views in memory before applying the preserved artifact and product checks.
It never builds, uploads, retags, or modifies a source checkout.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

PUBLICATION_REVISION = "88f01d82a177a75a80df6a42885b0c659a8bac69"
ORIGINAL_SOURCE = "2edfb1230bd8519072845d9b9b0e2d4c42ab3837"
REWRITTEN_SOURCE = "7f01d3656ec799f67eb48c06ab03ee583d60492c"
REWRITTEN_TAG = "aca9955eec70a697d06e49ce24fe9f5ecaaccfb1"
DOCUMENTS = frozenset({
    "CONTRIBUTING.md", "PUBLIC_IMPORT_NOTICE.md", "SECURITY.md",
    "docs/E3_EVALUATION.md", "docs/E5_EVALUATION_REPORT.md",
    "docs/E6_EVALUATION_REPORT.md", "docs/RELEASE_VALIDATION.md",
    "docs/releases/v0.3.0a1.md", "docs/releases/v0.4.0a1.md",
    "docs/releases/v0.7.0a1.md",
})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_verifier(root):
    # Check executable helpers against the pinned Git blobs before importing.
    import subprocess
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)
    if git("rev-parse", "HEAD").decode().strip() != PUBLICATION_REVISION:
        raise ValueError("publication worktree revision differs")
    for name in ("verify-pypi-release.py", "check-public-scope.py"):
        path = "scripts/" + name
        if (root / path).read_bytes() != git("show", PUBLICATION_REVISION + ":" + path):
            raise ValueError("preserved publication helper changed: " + path)
    return load_module(root / "scripts/verify-pypi-release.py", "original_e7_verifier")


def verify_local_refs(root, verifier):
    if (verifier.git(root, "rev-parse", "refs/tags/" + verifier.TAG).decode().strip() != REWRITTEN_TAG
            or verifier.git(root, "rev-parse", verifier.TAG + "^{commit}").decode().strip() != REWRITTEN_SOURCE):
        raise ValueError("rewritten E7 tag object or source commit differs")


def verify_remote_refs(verifier):
    ref = verifier.read_json(verifier.API + "/git/ref/tags/" + verifier.TAG)
    expected = {"sha": REWRITTEN_TAG, "type": "tag", "url": verifier.API + "/git/tags/" + REWRITTEN_TAG}
    if ref.get("object") != expected:
        raise ValueError("remote rewritten E7 annotated tag differs")
    tag = verifier.read_json(verifier.API + "/git/tags/" + REWRITTEN_TAG)
    if tag.get("object", {}).get("type") != "commit" or tag["object"]["sha"] != REWRITTEN_SOURCE:
        raise ValueError("remote rewritten E7 source differs")


def download_original_files(folder, verifier):
    release = verifier.read_json(verifier.API + "/releases/" + str(verifier.RELEASE_ID))
    verifier.validate_release_metadata(release)
    verify_remote_refs(verifier)
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("download directory must be empty")
    checksum = None
    for name, expected in {**verifier.PACKAGES, "SHA256SUMS.txt": verifier.CHECKSUM_SHA256}.items():
        with verifier.urlopen(verifier.ASSETS + name, timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or digest(data) != expected:
            raise ValueError("original public asset hash differs")
        if name == "SHA256SUMS.txt":
            checksum = data
        else:
            with (folder / name).open("xb") as stream:
                stream.write(data)
    parsed = {}
    for line in checksum.decode("ascii").splitlines():
        sha, name = line.split("  ", 1)
        if name in parsed:
            raise ValueError("duplicate original checksum entry")
        parsed[name] = sha
    if parsed != verifier.PACKAGES:
        raise ValueError("original checksum mapping differs")
    return checksum


def document_mapping():
    path = Path(__file__).resolve().parents[1] / "docs/E7_PUBLICATION_HISTORY_MAP.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value["documents"]
    if (value.get("schema") != "e7-publication-document-history-v1"
            or value.get("original_source") != ORIGINAL_SOURCE
            or value.get("rewritten_source") != REWRITTEN_SOURCE
            or len(rows) != len(DOCUMENTS) or {r["path"] for r in rows} != DOCUMENTS):
        raise ValueError("document history map scope differs")
    return rows


def mapped_documents(files, original_sdist, rows, prefix):
    if len(rows) != len(DOCUMENTS) or {r["path"] for r in rows} != DOCUMENTS:
        raise ValueError("document mapping must contain exactly the reviewed paths")
    result = dict(files)
    for row in rows:
        name = row["path"]
        current = files[name]
        original = original_sdist[prefix + "/" + name]
        if digest(current) != row["rewritten_sha256"] or len(current) != row["rewritten_bytes"]:
            raise ValueError("rewritten document differs from its exact mapping: " + name)
        if digest(original) != row["original_sha256"] or len(original) != row["original_bytes"]:
            raise ValueError("original document differs from its exact mapping: " + name)
        result[name] = original
    return result


def preserved_product(root, files, verifier):
    manifest_bytes = files["docs/E7_CODE_FREEZE.json"]
    if (root / "docs/E7_CODE_FREEZE.json").read_bytes() != manifest_bytes:
        raise ValueError("historical E7 manifest was modified")
    manifest = json.loads(manifest_bytes)
    if manifest["product_files"] != 57 or len(manifest["product"]) != 57:
        raise ValueError("historical E7 product inventory changed")
    if DOCUMENTS & set(manifest["product"]):
        raise ValueError("document mapping overlaps frozen product")
    for name, expected in manifest["product"].items():
        if digest(files[name]) != expected:
            raise ValueError("tagged E7 product differs from its original commitment: " + name)
    path = root / "scripts/check-e7-freeze.py"
    if path.read_bytes() != files["scripts/check-e7-freeze.py"]:
        raise ValueError("the historical E7 checker was modified")
    checker = load_module(path, "original_e7_freeze_checker")
    checker.verify(root, manifest)


def verified_source(root, folder, verifier):
    verify_local_refs(root, verifier)
    # The sdist is authenticated before any of its original document bytes are
    # used; its full inventory is checked later by the unchanged verifier.
    for name, expected in verifier.PACKAGES.items():
        if digest((folder / name).read_bytes()) != expected:
            raise ValueError("original distribution hash differs")
    payload = verifier.git(root, "archive", "--format=tar", REWRITTEN_SOURCE)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        files = {m.name: archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
    preserved_product(root, files, verifier)
    original = verifier.archive_files(folder / (verifier.PREFIX + ".tar.gz"))
    return mapped_documents(files, original, document_mapping(), verifier.PREFIX)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--check-registry", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve()
    verifier = checked_verifier(root)
    verify_local_refs(root, verifier)
    checksum = download_original_files(args.directory, verifier) if args.download else None
    files = verified_source(root, args.directory, verifier)
    counts = verifier.verify_package_contents(args.directory, files)
    registry = verifier.registry_state(verifier.read_json(
        "https://pypi.org/pypi/" + verifier.NAME + "/json", missing=True)) if args.check_registry else None
    if registry is not None and registry["status"] != "ALREADY_PUBLISHED_IDENTICAL_FILES":
        raise ValueError("historical PyPI version must retain the identical published files")
    receipt = {"schema": "e7-original-publication-with-rewritten-history-v1", "status": "PASS",
        "publication_revision": PUBLICATION_REVISION, "original_source_commit": verifier.SOURCE_COMMIT,
        "original_tag_object": verifier.TAG_OBJECT, "rewritten_source_commit": REWRITTEN_SOURCE,
        "rewritten_tag_object": REWRITTEN_TAG, "github_release_id": verifier.RELEASE_ID,
        "github_release_live_verified": args.download, "package_sha256": verifier.PACKAGES,
        "public_checksum_file_sha256": digest(checksum) if checksum is not None else None,
        "original_product_files": 57, "mapped_documents": document_mapping(),
        "package_contents": counts, "registry": registry, "upload_performed": False,
        "source_or_tag_modified": False, "original_verifier_modified": False,
        "provenance_scope": "ORIGINAL_ARTIFACTS_WITH_EXACT_DOCUMENT_HISTORY_MAPPING"}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
