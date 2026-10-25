from pathlib import Path
from unittest.mock import patch

import pytest

from tomolab.cli import main
from tomolab.engine import run_experiment
from tomolab.jev import JevError, _make_request, choose, resolve_route
from tomolab.mri import inspect_file, predicted_trace, static_proposals

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def run(case="nested_equal", **kwargs):
    return run_experiment(EXAMPLES / f"{case}.py", trusted_execution=True, **kwargs)


def test_mri_reads_static_guards_but_does_not_execute_source():
    ins = inspect_file(EXAMPLES / "nested_equal.py")
    assert len(ins.guards) == 2
    assert ins.guards[0].name == "x"
    assert ins.guards[1].ancestors == (ins.guards[0].line,)
    proposals = static_proposals(ins, -25, 25)
    assert proposals[0].inputs == (17, 0)
    assert proposals[1].inputs == (0, -3)
    assert len(ins.source_sha256) == 64
    assert ins.guards[1].line not in predicted_trace(ins, (0, -3))


def test_cross_feedback_identifies_counterexample_and_two_step_dependency():
    result = run(budget=8, mode="cross")
    assert result.status == "ORACLE_CONTRADICTION_FOUND"
    assert len(result.observations) == 2
    assert result.observations[0].inputs == (17, 0)
    assert result.observations[1].inputs == (17, -3)
    assert result.observations[1].origin == "feedback"
    assert result.observations[1].contradicts_oracle
    assert "ORACLE_CONTRADICTION_FOUND" == result.as_dict()["status"]
    assert not result.as_dict()["structural_model_disagreements"]


def test_ablation_do_not_detect_with_two_calls_in_designed_fixture():
    for mode in ("mri", "cast", "parallel"):
        result = run(budget=2, mode=mode, seed=7)
        assert result.status == "NO_COUNTEREXAMPLE_FOUND"
    assert run(budget=2, mode="cross").status == "ORACLE_CONTRADICTION_FOUND"


def test_other_fixture_types():
    for case in ("nested_ge_le", "nested_lt_eq"):
        result = run(case, budget=4)
        assert result.status == "ORACLE_CONTRADICTION_FOUND"
        assert result.observations[-1].origin == "feedback"


def test_correct_implementation_is_never_falsely_refuted():
    for mode in ("mri", "cast", "parallel", "cross"):
        result = run("correct", mode=mode, budget=20)
        assert result.status == "NO_COUNTEREXAMPLE_FOUND"
        assert all(not o.contradicts_oracle for o in result.observations)


def test_tested_contradiction_not_equivalent_to_universal_correctness():
    result = run("correct", budget=4)
    assert result.status == "NO_COUNTEREXAMPLE_FOUND"
    assert "not independent universal truth" in result.as_dict()["oracle_scope"]


def test_execution_requires_opt_in():
    with pytest.raises(PermissionError):
        run_experiment(EXAMPLES / "correct.py")


def test_static_inspection_does_not_import_target(tmp_path):
    target = tmp_path / "side_effect.py"
    marker = tmp_path / "marker"
    target.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('BAD')\n"
        "def implementation(x):\n    if x == 4:\n        return 9\n    return x\n"
    )
    result = inspect_file(target)
    assert len(result.guards) == 1
    assert not marker.exists()


def test_unsupported_condition_is_disclosed(tmp_path):
    target = tmp_path / "complex.py"
    target.write_text("def implementation(x):\n    if x * 2 == 8:\n        return 1\n    return 0\n")
    ins = inspect_file(target)
    assert not ins.guards
    assert "unsupported" in ins.limitations[0]


def test_jev_request_is_typed_and_restricted(monkeypatch):
    ins = inspect_file(EXAMPLES / "nested_equal.py")
    proposals = static_proposals(ins, -25, 25)
    req = _make_request(proposals, {"tested": 2})
    assert req["model"] == "typesafe-ai/jev"
    assert req["questions"]["next"]["type"] == "choice"
    assert "source_file" not in str(req)
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevError):
        choose(proposals, {}, key=None)


def test_jev_response_is_allowlisted():
    ins = inspect_file(EXAMPLES / "nested_equal.py")
    proposals = static_proposals(ins, -25, 25)
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return b'{"answers":{"next":{"choice":"p1"}}}'
    with patch("tomolab.jev.urllib.request.urlopen", return_value=Response()):
        assert choose(proposals, {"tested": 1}, key="fake-only") == 1
    class Bad(Response):
        def read(self, limit):
            return b'{"answers":{"next":{"choice":"unauthorized"}}}'
    with patch("tomolab.jev.urllib.request.urlopen", return_value=Bad()):
        with pytest.raises(JevError):
            choose(proposals, {}, key="fake-only")


def test_benchmark_output(tmp_path):
    output = tmp_path / "bench.json"
    assert main(["bench", "--budget", "2", "--seeds", "2", "--output", str(output)]) == 0
    import json
    data = json.loads(output.read_text())
    scores = {row["mode"]: row for row in data["summary"]}
    assert scores["cross"]["detected"] == 6
    assert scores["mri"]["detected"] == 0
    assert all(row["clean_false_alerts"] == 0 for row in scores.values())


def test_invalid_options_rejected():
    with pytest.raises(ValueError):
        run(budget=0)
    with pytest.raises(ValueError):
        run(mode="other")
    with pytest.raises(ValueError):
        run(use_jev=True, mode="mri")


def test_jev_can_change_selection_and_need_not_improve_accuracy(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-secret")
    # First turn has two legal outer branches; a deliberately suboptimal mocked choice
    # is selected. This explicitly tests that Jev cannot be assumed beneficial.
    with patch("tomolab.engine.choose", return_value=1):
        result = run("two_paths", mode="cross", budget=1, use_jev=True)
    assert result.observations[0].inputs == (-14, 0)
    assert result.decision_provider == "jev_live_typesafe"
    assert result.decision_calls == 1
    assert result.status == "NO_COUNTEREXAMPLE_FOUND"


def test_jev_no_credential_does_not_claim_live_use(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = run("two_paths", budget=1, use_jev=True)
    assert result.decision_provider == "jev_error_deterministic_fallback"
    assert result.decision_calls == 1
    assert result.decision_fallbacks == 1
    assert result.observations[0].inputs == (17, 0)


def test_replay_reproduces_specific_failure(tmp_path):
    from tomolab.replay import replay_evidence
    import json
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(run(budget=2).as_dict()))
    assert replay_evidence(evidence, trusted_execution=True)["status"] == "REPRODUCED"
    with pytest.raises(PermissionError):
        replay_evidence(evidence)


def test_replay_fails_closed_on_drift(tmp_path):
    from tomolab.replay import replay_evidence
    import json
    target = tmp_path / "target.py"
    target.write_bytes((EXAMPLES / "nested_equal.py").read_bytes())
    original = run_experiment(target, trusted_execution=True, budget=2)
    file = tmp_path / "evidence.json"
    file.write_text(json.dumps(original.as_dict()))
    target.write_text(target.read_text().replace("return x + y + 1", "return x + y + 2"))
    assert replay_evidence(file, trusted_execution=True)["status"] == "SOURCE_DRIFT"


def test_empty_evidence_does_not_report_verification(tmp_path):
    from tomolab.replay import replay_evidence
    import json
    file = tmp_path / "evidence.json"
    file.write_text(json.dumps(run("correct", budget=2).as_dict()))
    assert replay_evidence(file, trusted_execution=True)["status"] == "NO_FINDINGS"


def test_separate_oracle_detects_error_and_hashes_independently(tmp_path):
    from tomolab.replay import replay_evidence
    import json
    target = tmp_path / "target.py"
    target.write_bytes((EXAMPLES / "nested_equal.py").read_bytes())
    oracle_file = tmp_path / "independent_oracle.py"
    oracle_file.write_text("def reference(x, y):\n    return x + y\n")
    result = run_experiment(target, oracle_path=oracle_file, budget=2, trusted_execution=True)
    assert result.status == "ORACLE_CONTRADICTION_FOUND"
    assert result.source["source_sha256"] != result.source["oracle_source_sha256"]
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(result.as_dict()))
    assert replay_evidence(evidence, trusted_execution=True)["status"] == "REPRODUCED"
    oracle_file.write_text(oracle_file.read_text() + "# changed\n")
    assert replay_evidence(evidence, trusted_execution=True)["status"] == "ORACLE_DRIFT"


def test_replay_with_relocated_source_file(tmp_path):
    from tomolab.replay import replay_evidence
    import json
    result = run(budget=2)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(result.as_dict()))
    moved = tmp_path / "copied.py"
    moved.write_bytes((EXAMPLES / "nested_equal.py").read_bytes())
    assert replay_evidence(evidence, source_override=moved,
                           oracle_override=moved, trusted_execution=True)["status"] == "REPRODUCED"


def test_mutating_target_during_import_fails_closed(tmp_path):
    target = tmp_path / "mutating.py"
    target.write_text(
        "from pathlib import Path\n"
        "p = Path(__file__)\n"
        "p.write_text(p.read_text() + '# tampered\\n')\n"
        "def implementation(x):\n    if x == 4:\n        return 4\n    return x\n"
        "def reference(x):\n    return x\n"
    )
    with pytest.raises(ValueError, match="source changed during target import"):
        run_experiment(target, trusted_execution=True, budget=1)

# v0.1.1 direct TypeSafe authentication contract. All HTTP calls are mocked.
def test_typesafe_direct_route_prefers_direct_key_even_when_gateway_key_exists(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-typesafe")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "secret-gateway")
    route = resolve_route()
    assert route.provider == "typesafe"
    assert route.endpoint == "https://api.typesafe.ai/v1/systemone"
    assert route.model == "jev-latest"
    assert route.key == "secret-typesafe"


def test_typesafe_direct_request_uses_type_safe_model_and_key(monkeypatch):
    import json
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-direct")
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    proposals = static_proposals(inspect_file(EXAMPLES / "nested_equal.py"), -25, 25)
    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return b'{"answers":{"next":{"type":"choice","choice":"p1","confidence":0.77}}}'

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 8
        return Response()

    with patch("tomolab.jev.urllib.request.urlopen", side_effect=fake_urlopen):
        selected = choose(proposals, {"tested": 1}, provider="typesafe")
    assert selected == 1
    assert len(calls) == 1
    req = calls[0]
    assert req.full_url == "https://api.typesafe.ai/v1/systemone"
    assert req.get_header("Authorization") == "Bearer secret-direct"
    body = json.loads(req.data)
    assert body["model"] == "jev-latest"
    assert body["questions"]["next"]["type"] == "choice"
    assert "source_file" not in str(body)
    assert "secret-direct" not in str(body)
    assert "github" not in str(body).lower()


def test_explicit_vercel_route_does_not_use_typesafe_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-typesafe")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "secret-gateway")
    route = resolve_route(provider="vercel")
    assert route.provider == "vercel"
    assert route.model == "typesafe-ai/jev"
    assert route.endpoint == "https://ai-gateway.vercel.sh/v1/evaluate"
    assert route.key == "secret-gateway"


def test_direct_key_is_not_silently_used_for_vercel(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-typesafe")
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    with pytest.raises(JevError, match="AI_GATEWAY_API_KEY"):
        resolve_route(provider="vercel")


def test_live_direct_result_is_distinguishable_from_fallback(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-direct")
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return b'{"answers":{"next":{"choice":"p1"}}}'

    with patch("tomolab.jev.urllib.request.urlopen", return_value=Response()):
        result = run("two_paths", budget=1, mode="cross", use_jev=True,
                     jev_provider="typesafe")
    assert result.decision_provider == "jev_live_typesafe"
    assert result.decision_fallbacks == 0
    assert result.decision_calls == 1
    assert result.observations[0].inputs == (-14, 0)


def test_live_jev_failure_does_not_leak_secret_or_retry_other_provider(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-direct")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "secret-gateway")
    proposals = static_proposals(inspect_file(EXAMPLES / "nested_equal.py"), -25, 25)
    calls = []

    def failing(request, timeout):
        calls.append(request.full_url)
        raise ValueError("Server accidentally exposed secret-direct")

    with patch("tomolab.jev.urllib.request.urlopen", side_effect=failing):
        with pytest.raises(JevError) as e:
            choose(proposals, {}, provider="typesafe")
    assert len(calls) == 1
    assert calls == ["https://api.typesafe.ai/v1/systemone"]
    assert "secret-direct" not in str(e.value)
    assert "secret-gateway" not in str(e.value)


def test_provider_validation_precedes_execution():
    with pytest.raises(ValueError, match="jev_provider"):
        run("two_paths", budget=1, use_jev=True, jev_provider="unrecognized")


def test_mixed_jev_calls_are_not_reported_as_all_live(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy")
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    attempts = [0]
    def first_succeeds_then_fails(*args, **kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            return 1
        raise JevError("down")
    with patch("tomolab.engine.choose", side_effect=first_succeeds_then_fails) as mocked:
        result = run("two_paths", mode="cross", budget=3, use_jev=True)
    assert mocked.call_count >= 1
    # The provider label must never say a completely successful live session
    # when at least one attempted Jev choice fell back to deterministic.
    if result.decision_fallbacks:
        assert not result.decision_provider.startswith("jev_live_")
        assert result.decision_live_calls + result.decision_fallbacks == result.decision_calls
