from pathlib import Path

import pytest

from tomolab.discovery.workflow_audit import condition_value, audit_workflow

ROOT = Path(__file__).parents[1]
BRANCH = "feat/post-v7-v8-execution-20261101"


def test_new_branch_runs_exactly_four_functional_environments_and_one_oci_control():
    result = audit_workflow(ROOT/".github/workflows/tests.yml", branch=BRANCH)
    active = {row["name"] for row in result["jobs"] if row["expected"] == "RUN"}
    assert active == {"harvester-functional", "qualification-oci"}
    assert result["definitions"] == 15
    assert result["expected_run_jobs"] == 5 and result["expected_skipped_jobs"] == 13
    assert result["runtime_execution"] == result["network_requests"] == 0


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_new_branch_without_opt_in_cannot_run_research_or_publication(event):
    result = audit_workflow(ROOT/".github/workflows/tests.yml", branch=BRANCH, event=event)
    assert all(row["expected"] == "SKIP" for row in result["jobs"])
    publish = audit_workflow(ROOT/".github/workflows/publish-pypi.yml", branch=BRANCH, event=event)
    assert all(row["expected"] == "SKIP" for row in publish["jobs"])


@pytest.mark.parametrize("expression", ["__import__('os')", "secrets.TOKEN", "github.missing", "startsWith('a')", "[x for x in 'a']"])
def test_unknown_expression_fails_closed_without_python_eval(expression):
    with pytest.raises(ValueError):
        condition_value(expression, dict(github=dict(head_ref="x")))


def test_branch_fallback_boolean_and_string_conditions_are_exact():
    context = dict(github=dict(head_ref="", ref_name=BRANCH, event_name="pull_request"))
    assert condition_value("startsWith(github.head_ref || github.ref_name, 'feat/post-v7-') && github.event_name == 'pull_request'", context)
    assert not condition_value("!startsWith(github.ref_name, 'feat/post-v7-')", context)
