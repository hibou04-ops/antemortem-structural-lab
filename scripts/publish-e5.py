"""Gated E5 publication: annotated tag, verified draft, then public prerelease.

Only normal GitHub Actions credentials are used. Existing tags/assets are never
overwritten. A rerun verifies an already published release without republishing.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile

REPO = "hibou04-ops/antemortem-structural-lab"
VERSION = "0.5.0a1"
TAG = "v"+VERSION
PRESERVED_SOURCE_COMMIT = "473092b529a6593a890a5efc7f492433d269371e"


def command(*args, check=True):
    return subprocess.run(args,check=check,capture_output=True,text=True,encoding="utf-8")


def gh(*args,check=True):
    return command("gh",*args,check=check)


def api(path,missing=False):
    result = gh("api",f"repos/{REPO}/{path}",check=False)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("GitHub read failed: "+result.stderr)
    return json.loads(result.stdout)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_release():
    """The release-by-tag endpoint omits drafts; authenticated listing includes them."""
    matches = []
    for page in range(1, 11):
        releases = api(f"releases?per_page=100&page={page}")
        matches.extend(release for release in releases if release["tag_name"] == TAG)
        if len(matches) > 1:
            raise ValueError("ambiguous release tag; preserve all existing drafts")
        if len(releases) < 100:
            return matches[0] if matches else None
    raise ValueError("release listing exceeded its bound")


def resolve_tag(ref):
    target = ref["object"]
    for _ in range(4):
        if target["type"] == "commit":
            return target["sha"]
        if target["type"] != "tag":
            raise ValueError("release tag does not identify a commit")
        target = api("git/tags/"+target["sha"])["object"]
    raise ValueError("tag indirection exceeds bound")


def verify_source_assets(folder):
    """Compare artifact code/docs with this checked-out, validated main tree."""
    root = Path.cwd()
    wheel = folder/f"antemortem_structural_lab-{VERSION}-py3-none-any.whl"
    source = folder/f"antemortem_structural_lab-{VERSION}.tar.gz"
    names = command("git","ls-files","-z").stdout.split("\0")
    with zipfile.ZipFile(wheel) as archive:
        for name in names:
            if name.startswith("tomolab/") and name.endswith(".py"):
                if archive.read(name) != (root/name).read_bytes():
                    raise ValueError("wheel source differs from validated main: "+name)
        for name in ("README.md","README.ko.md","SECURITY.md"):
            packaged = f"antemortem_structural_lab-{VERSION}.data/data/share/antemortem-structural-lab/{name}"
            if archive.read(packaged) != (root/name).read_bytes():
                raise ValueError("wheel document differs from validated main")
    with tarfile.open(source) as archive:
        tracked = set(names)
        for member in archive.getmembers():
            if member.isfile():
                name = member.name.split("/",1)[1]
                if name in tracked and archive.extractfile(member).read() != (root/name).read_bytes():
                    raise ValueError("sdist differs from validated main: "+name)


def verify_download(release,head,expected,folder):
    if release["tag_name"] != TAG or not release["prerelease"]:
        raise ValueError("unexpected release tag or label")
    ref = api("git/ref/tags/"+TAG)
    if ref["object"]["type"] != "tag" or resolve_tag(ref) != head:
        raise ValueError("tag differs from validated main")
    if {a["name"] for a in release["assets"]} != expected:
        raise ValueError("unexpected release assets; nothing will be replaced")
    gh("release","download",TAG,"--repo",REPO,"--dir",str(folder))
    hashes = {p.name:sha(p) for p in folder.iterdir() if p.is_file()}
    if set(hashes) != expected:
        raise ValueError("downloaded asset names differ")
    parsed = {}
    for line in (folder/"SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        digest,name = line.split("  ",1)
        if name in parsed or not re.fullmatch(r"[0-9a-f]{64}",digest):
            raise ValueError("invalid checksum manifest")
        parsed[name] = digest
    if set(parsed) != expected-{"SHA256SUMS.txt"} or any(hashes[name] != digest for name,digest in parsed.items()):
        raise ValueError("downloaded release checksum mismatch")
    for asset in release["assets"]:
        if asset.get("digest") and asset["digest"] != "sha256:"+hashes[asset["name"]]:
            raise ValueError("GitHub asset digest mismatch")
    verify_source_assets(folder)
    return hashes


def main():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_EVENT_NAME") != "push"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("publication requires the authorized main CI push")
    ci_head = os.environ["GITHUB_SHA"]
    head = os.environ.get("E5_RELEASE_SOURCE_SHA",ci_head)
    if not all(re.fullmatch(r"[0-9a-f]{40}",value) for value in (head,ci_head)):
        raise ValueError("invalid main commit")
    if command("git","rev-parse","HEAD").stdout.strip() != head:
        raise ValueError("checked-out source differs from release source")
    if head != ci_head:
        if head != PRESERVED_SOURCE_COMMIT:
            raise ValueError("recovery must preserve the validated E5 tag source")
        command("git","merge-base","--is-ancestor",head,ci_head)
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version != VERSION:
        raise ValueError("version differs from authorized E5 prerelease")
    expected_packages = {f"antemortem_structural_lab-{VERSION}-py3-none-any.whl",f"antemortem_structural_lab-{VERSION}.tar.gz"}
    dist = Path("dist")
    if {p.name for p in dist.iterdir() if p.is_file()} != expected_packages:
        raise ValueError("unexpected build assets")
    expected = expected_packages|{"SHA256SUMS.txt"}
    existing = find_release()
    if existing is not None and not existing["draft"]:
        with tempfile.TemporaryDirectory(prefix="e5-existing-release-") as folder:
            hashes = verify_download(existing,head,expected,Path(folder))
        status = "EXISTING_RELEASE_BYTE_VERIFIED"
    else:
        ref = api("git/ref/tags/"+TAG,missing=True)
        if ref is None:
            command("git","-c","user.name=github-actions[bot]","-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "tag","-a",TAG,"-m","Antemortem Structural Lab "+TAG,head)
            command("git","push","origin","refs/tags/"+TAG)
            ref = api("git/ref/tags/"+TAG)
        if ref["object"]["type"] != "tag" or resolve_tag(ref) != head:
            raise ValueError("existing annotated tag differs; it will not be overwritten")
        hashes = {name:sha(dist/name) for name in sorted(expected_packages)}
        (dist/"SHA256SUMS.txt").write_text("".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)),encoding="ascii")
        hashes["SHA256SUMS.txt"] = sha(dist/"SHA256SUMS.txt")
        if existing is None:
            gh("release","create",TAG,"--repo",REPO,"--verify-tag","--prerelease","--latest=false","--draft",
               "--title",TAG+" (experimental)","--notes-file",f"docs/releases/{TAG}.md")
            existing = find_release()
            if existing is None:
                raise ValueError("new draft is missing from authenticated release listing")
        present = {a["name"] for a in existing["assets"]}
        if not present <= expected:
            raise ValueError("unexpected draft assets")
        if expected-present:
            gh("release","upload",TAG,"--repo",REPO,*[str(dist/name) for name in sorted(expected-present)])
        draft = api("releases/"+str(existing["id"]))
        if not draft["draft"]:
            raise ValueError("draft unexpectedly published before validation")
        with tempfile.TemporaryDirectory(prefix="e5-draft-readback-") as folder:
            downloaded = verify_download(draft,head,expected,Path(folder))
        if downloaded != hashes:
            raise ValueError("draft bytes differ from this build; no assets will be overwritten")
        gh("release","edit",TAG,"--repo",REPO,"--draft=false","--prerelease","--latest=false")
        status = "PUBLISHED_AND_BYTE_VERIFIED"
    published = find_release()
    if published["draft"] or not published["prerelease"]:
        raise ValueError("release publication readback failed")
    with tempfile.TemporaryDirectory(prefix="e5-public-readback-") as folder:
        final_hashes = verify_download(published,head,expected,Path(folder))
    if hashes != final_hashes:
        raise ValueError("public bytes differ from verified draft")
    receipt = {"status":status,"commit":head,"source_commit":head,"ci_commit":ci_head,
               "publication_helper_sha256":sha(Path(__file__)),"tag":TAG,"annotated_tag":True,
               "url":published["html_url"],"sha256":final_hashes,
               "draft_verified_before_publication":True if status == "PUBLISHED_AND_BYTE_VERIFIED" else "NOT_OBSERVED_IN_THIS_RUN",
               "external_generalization":"NOT_ESTABLISHED"}
    Path("release-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,indent=2))


if __name__ == "__main__":
    main()
