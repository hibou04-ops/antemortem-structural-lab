"""Separate explicit experimental-product publication from research readiness.

This checker performs no upload, tag, source collection or research execution.
CI receipts must be obtained by the trusted publisher from GitHub, not supplied
by a package's generator. A hash binds bytes; it does not prove a test ran.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "hibou04-ops/antemortem-structural-lab"
RESEARCH_REVISION = "591f802dea6f8ac88a27af3ffd89bd6e1396b318"
SCHEMA = "tomolab-product-release-authorization-v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def static_checks(root, *, version=None, tag=None):
    """Validate product-only policy without granting upload authorization."""
    root = Path(root)
    project = tomllib.loads((root/"pyproject.toml").read_text(encoding="utf-8"))["project"]
    actual = project["version"]
    require(project["name"] == "antemortem-structural-lab", "distribution identity differs")
    require(re.fullmatch(r"\d+\.\d+\.\d+(?:a|b|rc)\d+", actual), "experimental prerelease version required")
    require(project["urls"]["Repository"] == "https://github.com/"+REPOSITORY,
            "repository metadata differs")
    require(version is None or version == actual, "expected version differs")
    require(tag is None or tag == "v"+actual, "expected tag differs")
    auth = read(root/"docs/PRODUCT_RELEASE_AUTHORIZATION.json")
    required = dict(schema=SCHEMA, repository=REPOSITORY, version=actual, tag="v"+actual,
        product_publication_authorized=True, prerelease=True,
        approval_source="USER_EXPLICIT_2026-11-01", research_revision=RESEARCH_REVISION,
        scope="EXPERIMENTAL_PRODUCT_PUBLICATION_ONLY", study_reruns_authorized=False,
        distribution_policy="ONE_VERIFIED_BUILD_SHARED_BETWEEN_GITHUB_AND_PYPI",
        workflow="publish-pypi.yml", environment="pypi",
        research_qualification_granted=False, final_evaluation_authorized=False,
        existing_versions_immutable=True)
    for name, value in required.items():
        require(name in auth and type(auth[name]) is type(value) and auth[name] == value,
                "product-only authorization differs: "+name)
    require(read(root/"docs/E8_RELEASE_AUTHORIZATION.json").get("status") ==
            "NOT_AUTHORIZED_READINESS_BLOCKED", "E8 research publication gate changed")
    for name in ("ONLINE_PROFILE.json", "HISTORICAL_PROFILE.json"):
        profile = read(root/"docs"/name)
        require(profile["frozen_config"]["allow_release"] is False and
                profile["profile"]["publication_authorized"] is False and
                profile["profile"]["final_evaluation_authorized"] is False,
                "historical research authorization changed: "+name)
    require(read(root/"docs/HISTORICAL_RESULTS.json")["allow_release"] is False,
            "historical result release flag changed")
    readme = (root/"README.md").read_text(encoding="utf-8")
    usage = (root/"README.ko.md").read_text(encoding="utf-8")
    migration = (root/"docs/MIGRATION_0_8.md").read_text(encoding="utf-8")
    require(all(text in readme for text in (actual, "[qa]")) and
            ("experimental" in readme.lower() or "실험" in readme),
            "README must name the experimental product version and optional QA installation")
    require(all(text in usage for text in ("online-run", "online-replay", "Source", "A", "D")),
            "product usage must document run/replay, baseline and optional Source guidance")
    require("0.7.0a1" in migration and actual in migration,
            "migration notes must distinguish the preserved public version and new product")
    tree = ast.parse((root/"tomolab/online_cli.py").read_text(encoding="utf-8"))
    defaults = [next((v.value.value for v in node.keywords if v.arg == "default" and
                     isinstance(v.value, ast.Constant)), None)
        for node in ast.walk(tree) if isinstance(node, ast.Call) and
        isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument" and
        node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--method"]
    require(defaults and all(value == "A" for value in defaults), "online product default must be A")
    return dict(version=actual, tag="v"+actual, authorization_sha256=sha(root/"docs/PRODUCT_RELEASE_AUTHORIZATION.json"))


def evaluate(root=ROOT, *, version=None, tag=None, source_sha=None, ci_receipt=None,
             installation_receipt=None, required_jobs=(), static=False, actual_head=None):
    root = Path(root)
    identity = static_checks(root, version=version, tag=tag)
    result = dict(schema="tomolab-product-release-gate-v1", repository=REPOSITORY,
        **identity, status="STATIC_ONLY_NOT_UPLOAD_AUTHORIZATION",
        product_publication_authorized=False, research_allow_release=False,
        research_execution_authorized=False)
    if static:
        require(not any((source_sha, ci_receipt, installation_receipt, required_jobs)),
                "static-only checks do not consume publication receipts")
        return result
    require(isinstance(source_sha, str) and re.fullmatch(r"[a-f0-9]{40}", source_sha),
            "exact source commit required")
    if actual_head is None:
        actual_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                     capture_output=True, check=True).stdout.strip()
    require(actual_head == source_sha, "checkout differs from validated source commit")
    require(ci_receipt is not None and installation_receipt is not None,
            "actual CI and installation receipts are required")
    ci, installed = read(ci_receipt), read(installation_receipt)
    expected = dict(repository=REPOSITORY, source_sha=source_sha, workflow="Python tests",
                    event="push", head_branch="main", conclusion="success", status="PASS")
    require(all(ci.get(k) == v for k, v in expected.items()), "main CI receipt differs")
    require(type(ci.get("run_id")) is int and ci["run_id"] > 0, "actual GitHub CI run ID required")
    jobs = ci.get("required_jobs")
    require(isinstance(jobs, list) and jobs and all(isinstance(j, dict) and
            isinstance(j.get("name"), str) and j["name"] and j.get("conclusion") == "success"
            for j in jobs), "all required CI jobs must have succeeded")
    names = [j["name"] for j in jobs]
    require(len(names) == len(set(names)) and set(required_jobs) <= set(names),
            "required CI jobs missing or duplicated")
    require(installed.get("schema") == "tomolab-product-installation-v1" and
            installed.get("status") == "PASS" and installed.get("source_sha") == source_sha and
            installed.get("version") == identity["version"], "installation receipt identity differs")
    for field in ("base_install_verified", "qa_solver_verified", "sdist_install_verified",
                  "readme_commands_verified", "outside_checkout_verified",
                  "default_A_without_source_learning"):
        require(installed.get(field) is True, "installation evidence missing: "+field)
    require(installed.get("dependency_installation") == "NORMAL_INDEX_INSTALL",
            "publication requires normal-index CI installation; local byte reuse is a separate check")
    require(installed.get("registered_research_reexecuted") is False,
            "product validation must not repeat a research cohort")
    installs = installed.get("installations")
    require(isinstance(installs, list) and len(installs) == 2 and
            {row.get("artifact") for row in installs} == {"wheel", "sdist"},
            "separate wheel and sdist installation evidence required")
    for row in installs:
        require(row.get("distribution_version") == identity["version"] and row.get("default_method") == "A"
                and row.get("source_collection_calls") == row.get("source_learning_rules") == 0
                and type(row.get("product_target_calls")) is int and row["product_target_calls"] > 0
                and row.get("product_oracle_calls") == row["product_target_calls"]
                and row.get("replay_status") == "REPRODUCED",
                "installed product run/replay or Source boundary differs")
        origins = row.get("module_origins")
        require(isinstance(origins, list) and origins and all(isinstance(name, str) and
                not Path(name).is_absolute() and ".." not in Path(name).parts for name in origins),
                "installed import origin evidence required")
    checks = installed.get("checks")
    require(isinstance(checks, list) and checks and all(isinstance(c, dict) and
            type(c.get("returncode")) is int and type(c.get("expected_success")) is bool and
            (c["returncode"] == 0) == c["expected_success"] for c in checks),
            "actual successful installation command receipts required")
    assets = {"wheel": root/"dist"/f"antemortem_structural_lab-{identity['version']}-py3-none-any.whl",
              "sdist": root/"dist"/f"antemortem_structural_lab-{identity['version']}.tar.gz"}
    require({p.name for p in (root/"dist").iterdir() if p.is_file()} == {p.name for p in assets.values()},
            "exact current-version wheel and sdist required")
    for kind, path in assets.items():
        require(path.is_file() and path.stat().st_size > 0 and
                re.fullmatch(r"[a-f0-9]{64}", installed.get(kind+"_sha256", "")) and
                sha(path) == installed[kind+"_sha256"], "validated artifact differs: "+kind)
    result.update(status="PRODUCT_PUBLICATION_AUTHORIZED", product_publication_authorized=True,
                  source_sha=source_sha, ci_run_id=ci["run_id"], validated_jobs=names,
                  ci_receipt_sha256=sha(ci_receipt), installation_receipt_sha256=sha(installation_receipt),
                  assets={kind: dict(name=path.name, sha256=sha(path)) for kind,path in assets.items()})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--static", action="store_true")
    p.add_argument("--version")
    p.add_argument("--tag")
    p.add_argument("--source-sha")
    p.add_argument("--ci-receipt", type=Path)
    p.add_argument("--installation-receipt", type=Path)
    p.add_argument("--required-job", action="append", default=[])
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    value = evaluate(version=args.version, tag=args.tag, source_sha=args.source_sha,
        ci_receipt=args.ci_receipt, installation_receipt=args.installation_receipt,
        required_jobs=args.required_job, static=args.static)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2); stream.write("\n")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
