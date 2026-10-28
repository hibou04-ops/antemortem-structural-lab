"""Real CLI integration using only authored, bounded public functions.

One run of this file uses at most 128 Target/Oracle pairs. The common-record
validation fixture is data-only and is never reported as an executed batch.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.discovery.development_evidence import DevelopmentEvidenceArchive
from tomolab.discovery.knowledge import KnowledgeArchive
from tomolab.discovery.schema import digest

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=ROOT/"examples/partial"
PRIMITIVE_CALLS=0


def run(*args,expected=0,parse=True):
    result=subprocess.run([sys.executable,"-X","utf8","-m","tomolab",*map(str,args)],cwd=ROOT,
        text=True,encoding="utf-8",capture_output=True,timeout=60)
    assert result.returncode==expected,(result.stderr,result.stdout)
    return json.loads(result.stdout) if parse and result.stdout.strip() else result.stdout


def save(path,value):
    path.write_text(json.dumps(value),encoding="utf-8")
    return path


def count(result):
    global PRIMITIVE_CALLS
    PRIMITIVE_CALLS+=result["actual_primitive_calls"]
    assert PRIMITIVE_CALLS<=256


@pytest.fixture(scope="module")
def authored_demo(tmp_path_factory,record_testsuite_property):
    folder=tmp_path_factory.mktemp("authored-semantic-cli")
    path=folder/"demo.json"
    run("semantic-demo","--budget","8","--output",path)
    result=json.loads(path.read_text(encoding="utf-8"));count(result)
    yield path,result,folder
    record_testsuite_property("E8R1_CLI_authored_primitive_calls",PRIMITIVE_CALLS)
    record_testsuite_property("E8R1_CLI_real_project_calls",0)


def test_commands_help_and_authored_demo_connect_partial_rule_plan_and_oracle(authored_demo):
    for command in ("semantic-learn","semantic-inspect","semantic-plan","semantic-validate","semantic-run","semantic-demo"):
        assert "usage:" in run(command,"--help",parse=False)
    no_qa=subprocess.run([sys.executable,"-S","-X","utf8","-m","tomolab","semantic-demo"],cwd=ROOT,
        text=True,encoding="utf-8",capture_output=True,timeout=30)
    assert no_qa.returncode==2 and "[qa]" in no_qa.stderr
    _,result,_=authored_demo
    exact=result["exact_and_sufficient"]["EXACT_FAILURE_PREDICATE"]
    partial=result["exact_and_sufficient"]["SUFFICIENT_FAILURE_CONDITION"]
    assert exact["source_claim_status"]=="CONTRADICTED" and partial["source_claim_status"]=="OBSERVED_WITHIN_SOURCE"
    assert exact["source_statistics"]==partial["source_statistics"]==dict(TP=2,FP=0,FN=1,TN=1,UNKNOWN=0)
    assert result["selection_changed"] and result["run"]["generator_feedback"]==0
    assert result["run"]["target_calls"] and result["run"]["oracle_calls"]
    assert result["run"]["replay_status"]=="MATCHED_TWICE"
    assert result["scope"]=="AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH"
    assert result["independent_corroboration"]=="NOT_ESTABLISHED" and result["external_transfer"]=="NOT_EXECUTED_READINESS_BLOCKED"


def test_common_bundle_learning_inspection_parent_lineage_and_source_plan(authored_demo):
    demo_path,demo,folder=authored_demo
    ledger=DevelopmentEvidenceArchive.from_snapshot(demo["evidence_bundle"])
    first=ledger.accepted_records()[0]
    old=KnowledgeArchive.from_failure_log(first["spec"],
        [ledger.generator_evidence(r["record_id"]) for r in ledger.accepted_records()],first["provenance"]["origin"])
    old_path=save(folder/"legacy.json",old.freeze());before=old_path.read_bytes()
    archive=folder/"learned.json"
    run("semantic-learn","--bundle",demo_path,"--implementation-hash",first["implementation_hash"],
        "--spec-hash",first["public_spec_hash"],"--parent-snapshot",old_path,"--output",archive)
    assert old_path.read_bytes()==before
    learned=json.loads(archive.read_text(encoding="utf-8"))
    assert learned["schema"]=="tomolab-knowledge-archive-v2" and learned["frozen"]
    assert learned["derived_from"]["parent_archive_sha256"]==old.snapshot()["receipt"]["sha256"]
    inspected=run("semantic-inspect","--archive",archive)
    assert inspected["target_calls"]==inspected["oracle_calls"]==0
    assert inspected["semantic_claim_count"]>inspected["unique_expressions"]
    assert all("confusion_evidence" in row and "counterevidence" in row for row in inspected["claims"])
    planned=run("semantic-plan","--archive",archive,"--spec",EXAMPLES/"spec.json","--provenance",EXAMPLES/"provenance.json",
        "--purpose","SOURCE_DEVELOPMENT","--budget","8","--guidance-budget","4","--pool-size","32")
    assert planned["target_calls"]==planned["oracle_calls"]==0 and planned["final_feedback_allowed"] is False
    assert planned["gate"]["claims"] and any(c["source"]=="PARTIAL_CONDITION_PROBE" for c in planned["candidates"])
    blocked=run("semantic-plan","--archive",archive,"--spec",EXAMPLES/"spec.json","--provenance",EXAMPLES/"provenance.json",
        "--budget","4","--guidance-budget","2","--pool-size","16")
    assert not blocked["gate"]["claims"] and blocked["target_calls"]==blocked["oracle_calls"]==0
    run("semantic-plan","--archive",archive,"--spec",EXAMPLES/"spec.json","--provenance",EXAMPLES/"provenance.json",
        "--allow-unvalidated-empirical",expected=2)


def test_data_only_source_validation_forks_and_preserves_parent(authored_demo):
    demo_path,demo,folder=authored_demo
    original=demo_path.read_bytes();parent=demo["archive"]
    record=deepcopy(demo["evidence_bundle"]["journal"][0]["record"])
    point={"x":2,"y":0};raw=digest(["authored-data-only-validation",point])
    record.update(record_id="authored-data-only-new-normal",generation_id="E8R1-DATA-ONLY-VALIDATION",
        producer_tool="AuthoredDataOnlyFixture",input_or_trace=point)
    record["observed_failure_or_refutation"].update(status="REFUTATION",actual_result=2,oracle_result=2)
    bindings=dict(implementation_hash=record["implementation_hash"],oracle_identity=record["oracle_identity"],
        oracle_hash=record["oracle_hash"],public_spec_hash=record["public_spec_hash"],input_hash=digest(point),original_receipt_sha256=raw)
    for name in ("oracle_validation_receipt","domain_validity","replay_status","execution_receipt"):
        record[name]["bindings"]=deepcopy(bindings)
    record["execution_receipt"].update(execution_kind="CACHED_REPLAY",target_calls=0,oracle_calls=0,
        original_target_calls=3,original_oracle_calls=3,original_receipt_sha256=raw)
    record["provenance"].update(evidence_origin="AUTHORED_DATA_ONLY_VALIDATION_FIXTURE",source_record_sha256=raw)
    ledger=DevelopmentEvidenceArchive("E8R1-DATA-ONLY-VALIDATION");ledger.ingest(record,trusted_host=True)
    batch=save(folder/"validation.json",ledger.snapshot());output=folder/"validated.json"
    arguments=("semantic-validate","--archive",demo_path,"--bundle",batch,
        "--implementation-hash",record["implementation_hash"],"--spec-hash",record["public_spec_hash"],
        "--generation-id","E8-R1-NEW-VALIDATION")
    run(*arguments,expected=2)
    run(*arguments,"--approve-development-evidence","--output",output)
    value=json.loads(output.read_text())
    assert value["additional_target_calls"]==value["additional_oracle_calls"]==0
    assert value["accepted_model_observations"]==1 and value["archive"]["source_validation_observations"]==1
    assert demo_path.read_bytes()==original and parent["source_validation_observations"]==0
    assert value["archive"]["source_validation_journal"][0]["frozen_before_sha256"]==parent["receipt"]["sha256"]
    assert run("semantic-inspect","--archive",output)["external_transfer"]=="NOT_EXECUTED_READINESS_BLOCKED"
    run(*arguments,"--approve-development-evidence","--output",demo_path,expected=2)
    assert demo_path.read_bytes()==original


def run_arguments(target=EXAMPLES/"target.py",origin=EXAMPLES/"provenance.json",review=EXAMPLES/"oracle-validation.json"):
    return ("semantic-run",target,"--oracle-file",EXAMPLES/"oracle.py","--spec",EXAMPLES/"spec.json",
        "--provenance",origin,"--oracle-validation",review,"--method","A","--budget","6")


def test_execution_approval_policy_budget_and_file_pins_precede_module_import(tmp_path):
    target=tmp_path/"never-import.py"
    target.write_text("raise AssertionError('unapproved module imported')\ndef implementation(x,y):return x+y\n",encoding="utf-8")
    origin=json.loads((EXAMPLES/"provenance.json").read_text());origin["implementation_sha256"]=hashlib.sha256(target.read_bytes()).hexdigest()
    review=json.loads((EXAMPLES/"oracle-validation.json").read_text());review["implementation_hash"]=origin["implementation_sha256"]
    review["receipt_sha256"]=digest({k:v for k,v in review.items() if k!="receipt_sha256"})
    origin_path=save(tmp_path/"origin.json",origin);review_path=save(tmp_path/"review.json",review)
    arguments=run_arguments(target,origin_path,review_path)
    run(*arguments,expected=2)
    run(*arguments,"--allow-local-execution","--budget","2",expected=2)
    changed=save(tmp_path/"changed-policy.json",dict(review["comparison_policy"],absolute_tolerance=1))
    run(*arguments,"--allow-local-execution","--comparison-policy",changed,expected=2)
    origin["implementation_sha256"]="0"*64;save(origin_path,origin)
    run(*arguments,"--allow-local-execution",expected=2)


def test_actual_source_cli_executes_with_replay_budget_and_without_transfer(authored_demo):
    path,_,_=authored_demo
    result=run(*run_arguments(),"--method","C","--archive",path,"--allow-local-execution",
        "--guidance-budget","2","--pool-size","16")
    count(result)
    assert 0<result["target_calls"]<=6 and 0<result["oracle_calls"]<=6
    assert result["generator_feedback"]==0 and result["archive_updated"] is False
    assert result["external_transfer"]=="NOT_EXECUTED_READINESS_BLOCKED"
    assert result["oracle_validation_receipt_sha256"]==json.loads((EXAMPLES/"oracle-validation.json").read_text())["receipt_sha256"]
