"""Phase C regression checks: no executable oracle, strict claim compiler."""
import json
from pathlib import Path

import pytest

from tomolab.claim import SCHEMA, compile_claim, replay_claim, run_claim
from tomolab.cli import main

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "claim_only"
SWAP = "두 정수 입력의 순서를 바꿔도 반환값은 같다"
SHIFT = "첫 번째 정수 입력을 1 증가시키면 반환값도 1 증가한다"
MONOTONE = "첫 번째 정수 입력을 1 증가시키면 반환값이 감소하지 않는다"


def run(name, claim, **opts):
    return run_claim(CASES / f"{name}.py", claim, trusted_execution=True, **opts)


@pytest.mark.parametrize("name,claim", [
    ("symmetry_bug", SWAP), ("shift_bug", SHIFT), ("monotone_bug", MONOTONE),
])
def test_cross_refutes_without_oracle(name, claim):
    result = run(name, claim, mode="cross", budget=12)
    assert result["schema"] == SCHEMA
    assert result["status"] == "CLAIM_REFUTED"
    assert result["oracle_function"] is None
    assert result["target_calls"] == 6
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["obligation_violated"]
    assert finding["stable_on_repeat"]
    assert finding["origin"] == "mri_cast_feedback"
    assert (CASES / f"{name}.py").read_text().find("def reference") == -1


def test_bundled_control_survives_three_properties():
    for claim in (SWAP, SHIFT, MONOTONE):
        result = run("sum_clean", claim, budget=12)
        assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
        assert not result["findings"]


def test_insufficient_property_cannot_certify_correctness():
    result = run("symmetric_not_sum", SWAP, budget=12)
    assert result["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    # This function returns x*x+y*y, NOT x+y; the swap law cannot detect it.
    assert not result["findings"]


def test_unknown_claim_fail_closed_without_importing_target(tmp_path):
    marker = tmp_path / "BAD_MARKER"
    bad = tmp_path / "side_effect.py"
    bad.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
                   "def implementation(x:int, y:int)->int: return x+y\n")
    with pytest.raises(ValueError, match="UNSUPPORTED_CLAIM"):
        run_claim(bad, "This code is completely safe", trusted_execution=True)
    assert not marker.exists()


def test_compile_is_nonexecuting_and_accepts_limited_exact_english():
    contract = compile_claim("Swapping the two integer inputs does not change the result.")
    assert contract.kind == "swap"
    assert contract.obligation == "f(x,y) == f(y,x)"
    assert compile_claim(SWAP).contract_sha256 != contract.contract_sha256


def test_false_sense_of_semantic_coverage_is_rejected():
    for s in ("always safe", "returns the sum x+y", "Does not change", ""):
        with pytest.raises(ValueError, match="UNSUPPORTED_CLAIM"):
            compile_claim(s)


def test_run_requires_opt_in():
    with pytest.raises(PermissionError):
        run_claim(CASES / "symmetry_bug.py", SWAP)


def test_budget_counts_all_three_function_invocations():
    assert run("symmetry_bug", SWAP, budget=3)["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert run("symmetry_bug", SWAP, budget=3)["target_calls"] == 3
    assert run("symmetry_bug", SWAP, budget=6)["status"] == "CLAIM_REFUTED"
    with pytest.raises(ValueError):
        run("symmetry_bug", SWAP, budget=2)


def test_replay_and_source_drift(tmp_path):
    source = tmp_path / "target.py"
    source.write_bytes((CASES / "symmetry_bug.py").read_bytes())
    result = run_claim(source, SWAP, trusted_execution=True)
    file = tmp_path / "evidence.json"
    file.write_text(json.dumps(result))
    assert replay_claim(file, trusted_execution=True)["status"] == "REPRODUCED"
    source.write_text(source.read_text().replace("return x + y + 1", "return x + y + 2"))
    assert replay_claim(file, trusted_execution=True)["status"] == "SOURCE_DRIFT"


def test_contract_hash_tamper_refuses_replay(tmp_path):
    result = run("symmetry_bug", SWAP)
    result["claim"]["formal_obligation"] = "f(x,y) = true (not!)"
    file = tmp_path / "corrupt.json"
    file.write_text(json.dumps(result))
    assert replay_claim(file, trusted_execution=True)["status"] == "CONTRACT_DRIFT"


def test_empty_replay_does_not_infer_correctness(tmp_path):
    result = run("sum_clean", SWAP)
    file = tmp_path / "clean.json"
    file.write_text(json.dumps(result))
    assert replay_claim(file, trusted_execution=True)["status"] == "NO_FINDINGS"


def test_exception_is_not_mislabelled_as_a_refutation(tmp_path):
    source = tmp_path / "exception.py"
    source.write_text("def implementation(x:int,y:int)->int:\n    raise ValueError('not a violation')\n")
    result = run_claim(source, SWAP, trusted_execution=True, budget=6)
    assert result["status"] == "INCONCLUSIVE_EXECUTION"
    assert all(not o["obligation_violated"] for o in result["observations"])


def test_cli_claim_compile_and_run(tmp_path):
    outfile = tmp_path / "claim.json"
    assert main(["claim-run", str(CASES / "symmetry_bug.py"), "--claim", SWAP,
                 "--allow-local-execution", "--output", str(outfile)]) == 0
    data = json.loads(outfile.read_text(encoding="utf-8"))
    assert data["oracle_function"] is None
    assert data["status"] == "CLAIM_REFUTED"
    assert main(["claim-replay", str(outfile), "--allow-local-execution"]) == 0


def test_cli_benchmark_output(tmp_path):
    outfile = tmp_path / "bench.json"
    assert main(["claim-bench", "--seeds", "2", "--budget", "12", "--output", str(outfile)]) == 0
    results = json.loads(outfile.read_text())
    modes = {r["mode"]: r for r in results["summary"]}
    assert modes["cross"]["refuted"] == 6
    assert modes["cross"]["false_refutations"] == 0
    assert all(r["clean_trials"] == 8 for r in modes.values())
