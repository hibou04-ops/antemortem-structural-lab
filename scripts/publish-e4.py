"""Normal CI publication, after all regression, installation and isolation jobs.

Only the authorized repository, version and main push can publish. Existing tags
and release assets are verified, never replaced. No private files are uploaded.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

REPO = "hibou04-ops/antemortem-structural-lab"
VERSION = "0.4.0a1"
TAG = "v" + VERSION


def gh(*args, check=True):
    return subprocess.run(["gh", *args], check=check, capture_output=True,
                          text=True, encoding="utf-8")


def main():
    if (os.environ.get("GITHUB_REPOSITORY") != REPO or
            os.environ.get("GITHUB_EVENT_NAME") != "push" or
            os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("publication requires the authorized main CI push")
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version != VERSION:
        raise ValueError("version differs from authorized E4 prerelease")
    head = os.environ["GITHUB_SHA"]
    assets = sorted(Path("dist").iterdir())
    expected = {f"antemortem_structural_lab-{VERSION}-py3-none-any.whl",
                f"antemortem_structural_lab-{VERSION}.tar.gz"}
    if {p.name for p in assets} != expected:
        raise ValueError("unexpected distribution assets")
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}
    checksum = Path("dist/SHA256SUMS.txt")
    checksum.write_text("".join(f"{sums[p.name]}  {p.name}\n" for p in assets), encoding="ascii")
    assets.append(checksum)
    sums[checksum.name] = hashlib.sha256(checksum.read_bytes()).hexdigest()
    ref = gh("api", f"repos/{REPO}/git/ref/tags/{TAG}", check=False)
    if ref.returncode:
        if "HTTP 404" not in ref.stderr:
            raise RuntimeError("cannot determine whether release tag exists: " + ref.stderr)
        gh("release", "create", TAG, "--repo", REPO, "--target", head,
           "--prerelease", "--title", TAG + " — E4 structural QA integration",
           "--notes-file", f"docs/releases/{TAG}.md", *map(str, assets))
    remote_ref = json.loads(gh("api", f"repos/{REPO}/git/ref/tags/{TAG}").stdout)
    if remote_ref["object"]["type"] != "commit" or remote_ref["object"]["sha"] != head:
        raise ValueError("existing tag does not point to the validated main commit")
    release = json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}").stdout)
    if release["draft"] or not release["prerelease"]:
        raise ValueError("release is not a published prerelease")
    if {a["name"] for a in release["assets"]} != set(sums):
        raise ValueError("remote asset names differ; existing assets will not be replaced")
    with tempfile.TemporaryDirectory(prefix="e4-release-readback-") as folder:
        gh("release", "download", TAG, "--repo", REPO, "--dir", folder)
        downloaded = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in Path(folder).iterdir() if p.is_file()}
        if downloaded != sums:
            raise ValueError("remote release bytes differ from built assets")
    receipt = {"status": "PUBLISHED_AND_BYTE_VERIFIED", "commit": head,
               "tag": TAG, "url": release["html_url"], "sha256": sums,
               "generalization": "NOT_ESTABLISHED"}
    Path("release-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
