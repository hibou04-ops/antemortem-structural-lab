"""Actual CLI functional fixtures; no private or real-project target execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_e8_evidence import record
from test_e8_readiness import different_implementation
from tomolab.discovery.schema import digest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT/"examples/evidence"


def run(*args, expected=0):
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "tomolab", *map(str,args)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == expected, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_cli_common_import_inspect_learn_and_corroborate(tmp_path):
    source = [record("S-positive",0,True), record("S-negative",1,False)]
    c = [different_implementation(record("C-positive",0,True),2), different_implementation(record("C-negative",1,False),2)]
    records = save(tmp_path/"records.json",source+c)
    bundle, knowledge, frozen = (tmp_path/name for name in ("bundle.json","source.json","frozen.json"))
    run("evidence-import","--records",records,"--generation-id","E8-AUTHORED","--parent-generation","E7-AUTHORED",
        "--approve-execution-receipts","--output",bundle)
    summary = run("evidence-inspect","--bundle",bundle)
    assert summary["eligible_records"] == 4 and summary["valid_failures"] == 2
    assert summary["target_calls"] == summary["oracle_calls"] == summary["new_target_calls"] == 0
    run("evidence-learn","--bundle",bundle,"--implementation-hash","1"*64,"--spec-hash",source[0]["public_spec_hash"],"--output",knowledge)
    assert json.loads(knowledge.read_text())["frozen"] is False
    run("evidence-corroborate","--archive",knowledge,"--bundle",bundle,"--implementation-hash","2"*64,
        "--spec-hash",source[0]["public_spec_hash"],"--approve-development-evidence","--output",frozen)
    snapshot = json.loads(frozen.read_text())
    assert snapshot["frozen"] and any(claim["status"] == "SUPPORTED_WITHIN_SCOPE" for claim in snapshot["claims"])


def test_cli_import_and_corroboration_require_review_approval(tmp_path):
    missing = tmp_path/"absent.json"
    run("evidence-import","--records",missing,"--generation-id","E8-AUTHORED",expected=2)
    run("evidence-corroborate","--archive",missing,"--bundle",missing,
        "--implementation-hash","1"*64,"--spec-hash","2"*64,expected=2)


def test_cli_same_source_observation_never_claims_independent_qualification(tmp_path):
    source = [record("S-positive",0,True),record("S-negative",1,False)]
    records = save(tmp_path/"records.json",source); bundle=tmp_path/"bundle.json"; knowledge=tmp_path/"source.json"
    run("evidence-import","--records",records,"--generation-id","E8-AUTHORED","--parent-generation","E7-AUTHORED",
        "--approve-execution-receipts","--output",bundle)
    run("evidence-learn","--bundle",bundle,"--implementation-hash","1"*64,"--spec-hash",source[0]["public_spec_hash"],"--output",knowledge)
    result=run("evidence-corroborate","--archive",knowledge,"--bundle",bundle,"--implementation-hash","1"*64,
        "--spec-hash",source[0]["public_spec_hash"],"--approve-development-evidence")
    assert not any(claim["independent_contrastive_origins"] for claim in result["claims"])
    assert not any(claim["status"] == "SUPPORTED_WITHIN_SCOPE" for claim in result["claims"])


def test_cli_readiness_missing_inputs_and_files_emit_explicit_not_executed(tmp_path):
    blocked=run("readiness-check",expected=3)
    assert blocked["status"] == "NOT_EXECUTED_READINESS_BLOCKED"
    assert blocked["bindings"]["target_calls"] == blocked["bindings"]["oracle_calls"] == 0
    absent=run("readiness-check","--evidence",tmp_path/"absent.json",expected=3)
    assert "READINESS_BLOCKED_NO_VALID_FAILURE" in absent["blockers"]
    bad=save(tmp_path/"bad.json",["malformed-constructor-input"])
    assert run("readiness-check","--bundle",bad,expected=3)["status"] == "NOT_EXECUTED_READINESS_BLOCKED"
    demo=run("readiness-demo")
    assert demo["scope"] == "AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH"
    assert demo["source_count"] == demo["corroboration_count"] == demo["target_count"] == 0


def collector_arguments(target=EXAMPLES/"target.py",oracle=EXAMPLES/"oracle.py",spec=EXAMPLES/"spec.json",
                        provenance=EXAMPLES/"provenance.json",review=EXAMPLES/"oracle-validation.json"):
    return ("evidence-collect",target,"--oracle-file",oracle,"--spec",spec,"--provenance",provenance,
        "--oracle-validation",review,"--function-identity","authored-identity","--generation-id","E8-CLI-AUTHORED",
        "--budget","8","--max-calls","16")


def test_cli_collector_invalid_authorization_contract_or_budget_never_imports(tmp_path):
    marker=tmp_path/"imported"
    target=tmp_path/"target.py"
    target.write_text("from pathlib import Path\nPath("+repr(str(marker))+").touch()\ndef implementation(value): return value\n",encoding="utf-8")
    origin=json.loads((EXAMPLES/"provenance.json").read_text()); origin["implementation_sha256"]=hashlib.sha256(target.read_bytes()).hexdigest()
    provenance=save(tmp_path/"provenance.json",origin)
    arguments=collector_arguments(target=target,provenance=provenance)
    run(*arguments,expected=2)
    assert not marker.exists()
    bad_review=json.loads((EXAMPLES/"oracle-validation.json").read_text()); bad_review["oracle_hash"]="0"*64
    review=save(tmp_path/"bad-review.json",bad_review)
    run(*collector_arguments(target=target,provenance=provenance,review=review),"--allow-local-execution",expected=2)
    assert not marker.exists()
    run(*arguments,"--allow-local-execution","--budget","0",expected=2)
    assert not marker.exists()
    origin["implementation_sha256"]="0"*64; save(provenance,origin)
    run(*arguments,"--allow-local-execution",expected=2)
    assert not marker.exists()


def test_actual_authored_collector_cli_with_sixteen_primitive_call_cap(tmp_path):
    # This is the only test in this file executing a collector target/Oracle.
    # Root's functional budget reserves <=16 calls here and <=16 in full QA.
    output=tmp_path/"authored-collection.json"
    run(*collector_arguments(),"--allow-local-execution","--output",output)
    result=json.loads(output.read_text())
    assert result["schema"] == "tomolab-native-development-collection-v1"
    assert 0 < result["summary"]["actual_primitive_calls"] <= 16
    assert result["evidence_bundle"]["journal"]
    summary=run("evidence-inspect","--bundle",output)
    assert summary["valid_failures"] >= 1
    assert summary["new_target_calls"]+summary["new_oracle_calls"] <= 16
    assert summary["independence"] == "NOT_INFERRED_FROM_PRODUCER_OR_RECEIPT_HASH"


def test_cli_context_selection_does_not_drop_unqualified_rows_to_find_a_source(tmp_path):
    records=save(tmp_path/"records.json",[record("normal-only",1,False)])
    bundle=tmp_path/"bundle.json"
    run("evidence-import","--records",records,"--generation-id","E8-AUTHORED","--parent-generation","E7-AUTHORED",
        "--approve-execution-receipts","--output",bundle)
    run("evidence-learn","--bundle",bundle,"--implementation-hash","1"*64,
        "--spec-hash",record()["public_spec_hash"],expected=2)
