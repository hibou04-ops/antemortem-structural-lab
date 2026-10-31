"""Product approval is narrow and cannot stand in for CI or installation."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("product_release_gate", ROOT/"scripts/check-product-release.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def write(root, name, value):
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.fixture
def product(tmp_path):
    root = tmp_path
    (root/"docs").mkdir()
    (root/"tomolab").mkdir()
    (root/"dist").mkdir()
    (root/"pyproject.toml").write_text(
        '[project]\nname="antemortem-structural-lab"\nversion="0.8.0a1"\n'
        '[project.urls]\nRepository="https://github.com/hibou04-ops/antemortem-structural-lab"\n', encoding="utf-8")
    (root/"README.md").write_text('Experimental 0.8.0a1: pip install "antemortem-structural-lab[qa]"', encoding="utf-8")
    (root/"README.ko.md").write_text('A online-run → online-replay; D Source 선택 기능', encoding="utf-8")
    (root/"docs/MIGRATION_0_8.md").write_text('Preserve 0.7.0a1; experimental product 0.8.0a1', encoding="utf-8")
    (root/"tomolab/online_cli.py").write_text("p.add_argument('--method', choices=('A','B','C','D'), default='A')\n", encoding="utf-8")
    auth = dict(schema=gate.SCHEMA, repository=gate.REPOSITORY, version="0.8.0a1", tag="v0.8.0a1",
        product_publication_authorized=True, prerelease=True, approval_source="USER_EXPLICIT_2026-11-01",
        research_revision=gate.RESEARCH_REVISION, research_qualification_granted=False,
        final_evaluation_authorized=False, existing_versions_immutable=True,
        scope="EXPERIMENTAL_PRODUCT_PUBLICATION_ONLY", study_reruns_authorized=False,
        distribution_policy="ONE_VERIFIED_BUILD_SHARED_BETWEEN_GITHUB_AND_PYPI",
        workflow="publish-pypi.yml", environment="pypi")
    write(root, "docs/PRODUCT_RELEASE_AUTHORIZATION.json", auth)
    write(root, "docs/E8_RELEASE_AUTHORIZATION.json", {"status":"NOT_AUTHORIZED_READINESS_BLOCKED"})
    for name in ("ONLINE_PROFILE.json", "HISTORICAL_PROFILE.json"):
        write(root, "docs/"+name, dict(frozen_config=dict(allow_release=False),
            profile=dict(publication_authorized=False, final_evaluation_authorized=False)))
    write(root, "docs/HISTORICAL_RESULTS.json", dict(allow_release=False))
    for name in ("antemortem_structural_lab-0.8.0a1-py3-none-any.whl",
                 "antemortem_structural_lab-0.8.0a1.tar.gz"):
        (root/"dist"/name).write_bytes(b"validated-artifact:"+name.encode())
    source = "a"*40
    ci = dict(repository=gate.REPOSITORY, source_sha=source, workflow="Python tests", event="push",
        head_branch="main", conclusion="success", run_id=1234, status="PASS",
        required_jobs=[dict(name="tests (ubuntu-latest, 3.12)", conclusion="success"),
                       dict(name="product-installation", conclusion="success")])
    installed = dict(schema="tomolab-product-installation-v1", status="PASS", source_sha=source, version="0.8.0a1",
        wheel_sha256=gate.sha(root/"dist/antemortem_structural_lab-0.8.0a1-py3-none-any.whl"),
        sdist_sha256=gate.sha(root/"dist/antemortem_structural_lab-0.8.0a1.tar.gz"),
        base_install_verified=True, qa_solver_verified=True, sdist_install_verified=True,
        readme_commands_verified=True, outside_checkout_verified=True,
        default_A_without_source_learning=True, dependency_installation="NORMAL_INDEX_INSTALL",
        registered_research_reexecuted=False,
        installations=[dict(artifact=kind, distribution_version="0.8.0a1", default_method="A",
            source_collection_calls=0, source_learning_rules=0, product_target_calls=20,
            product_oracle_calls=20, replay_status="REPRODUCED",
            module_origins=["Lib/site-packages/tomolab/online_cli.py"]) for kind in ("wheel", "sdist")],
        checks=[dict(check="wheel:install", returncode=0, expected_success=True),
                dict(check="base:missing-QA-guidance", returncode=2, expected_success=False)])
    return root, source, write(root, "ci.json", ci), write(root, "installed.json", installed)


def evaluate(product, **changes):
    root, source, ci, installed = product
    values = dict(source_sha=source, actual_head=source, ci_receipt=ci,
                  installation_receipt=installed, required_jobs=["product-installation"])
    values.update(changes)
    return gate.evaluate(root, **values)


def mutate(path, function):
    value = json.loads(path.read_text(encoding="utf-8"))
    function(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_static_is_never_upload_authorization(product):
    root, *_ = product
    value = gate.evaluate(root, static=True)
    assert value["status"] == "STATIC_ONLY_NOT_UPLOAD_AUTHORIZATION"
    assert value["product_publication_authorized"] is False
    assert value["research_allow_release"] is False


def test_approved_product_requires_actual_identity_bound_receipts(product):
    result = evaluate(product)
    assert result["product_publication_authorized"] is True
    assert result["research_allow_release"] is False
    assert result["research_execution_authorized"] is False
    assert result["ci_run_id"] == 1234


@pytest.mark.parametrize("field,value", [
    ("research_qualification_granted", True), ("final_evaluation_authorized", True),
    ("existing_versions_immutable", False), ("product_publication_authorized", False),
    ("repository", "someone/else"), ("version", "0.7.0a1"), ("prerelease", False),
    ("approval_source", "INFERRED"), ("research_revision", "b"*40)])
def test_product_approval_cannot_broaden_scope(product, field, value):
    path = product[0]/"docs/PRODUCT_RELEASE_AUTHORIZATION.json"
    mutate(path, lambda v: v.update({field:value}))
    with pytest.raises(ValueError, match="authorization differs"):
        evaluate(product)


def test_research_publication_stays_blocked(product):
    mutate(product[0]/"docs/HISTORICAL_PROFILE.json",
           lambda v: v["profile"].update(publication_authorized=True))
    with pytest.raises(ValueError, match="research authorization changed"):
        evaluate(product)


def test_no_C_or_D_automatic_product_default(product):
    (product[0]/"tomolab/online_cli.py").write_text("p.add_argument('--method', default='D')", encoding="utf-8")
    with pytest.raises(ValueError, match="default must be A"):
        evaluate(product)


@pytest.mark.parametrize("field,value", [("event","pull_request"), ("head_branch","research"),
    ("source_sha","b"*40), ("conclusion","failure"), ("status","PENDING"), ("run_id",0)])
def test_unvalidated_CI_does_not_authorize_upload(product, field, value):
    mutate(product[2], lambda v: v.update({field:value}))
    with pytest.raises(ValueError):
        evaluate(product)


def test_missing_or_failed_required_job_blocks(product):
    mutate(product[2], lambda v: v.update(required_jobs=[dict(name="other", conclusion="success")]))
    with pytest.raises(ValueError, match="jobs missing"):
        evaluate(product)


@pytest.mark.parametrize("field,value", [("status","NOT_EXECUTED"), ("source_sha","b"*40),
    ("sdist_install_verified",False), ("default_A_without_source_learning",False),
    ("outside_checkout_verified",False), ("registered_research_reexecuted",True),
    ("dependency_installation","APPROVED_BYTE_REUSE")])
def test_installation_must_be_actual_normal_CI_not_self_description(product, field, value):
    mutate(product[3], lambda v: v.update({field:value}))
    with pytest.raises(ValueError):
        evaluate(product)


def test_expected_failure_is_a_real_command_check(product):
    assert evaluate(product)["product_publication_authorized"] is True
    mutate(product[3], lambda v: v["checks"][1].update(returncode=0))
    with pytest.raises(ValueError, match="command receipts"):
        evaluate(product)


def test_rebuilt_or_tampered_asset_requires_new_validation(product):
    (product[0]/"dist/antemortem_structural_lab-0.8.0a1.tar.gz").write_bytes(b"different-build")
    with pytest.raises(ValueError, match="artifact differs: sdist"):
        evaluate(product)


def test_missing_evidence_or_different_checkout_fails_closed(product):
    with pytest.raises(ValueError, match="actual CI and installation"):
        evaluate(product, installation_receipt=None)
    with pytest.raises(ValueError, match="checkout differs"):
        evaluate(product, actual_head="b"*40)


def test_static_mode_cannot_be_mixed_with_publication_receipts(product):
    with pytest.raises(ValueError, match="static-only"):
        evaluate(product, static=True)
