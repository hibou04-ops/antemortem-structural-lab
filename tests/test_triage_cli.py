"""Static triage CLI fixtures with no network, source import or target call."""
import argparse
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tomolab import triage_cli
from tomolab.discovery.schema import digest
from test_prequalification_triage import record


def manifest():
    value=record()
    return dict(schema=triage_cli.INPUT_SCHEMA,records=[value],expected_candidate_ids=[value["candidate_id"]],read_plan_sha256="c"*64)


def test_register_and_dispatch_materialize_data_only_static_result(tmp_path,monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,"run",lambda *a,**kw:pytest.fail("static triage cannot launch a process"))
    path=tmp_path/"input.json";output=tmp_path/"new.json"
    path.write_text(json.dumps(manifest()),encoding="utf-8")
    parser=argparse.ArgumentParser();triage_cli.register(parser.add_subparsers(dest="command",required=True))
    args=parser.parse_args(["harvest-triage","--manifest",str(path),"--output",str(output)])
    value=triage_cli.dispatch(args)
    assert value==json.loads(output.read_bytes()) and value["candidate_sequence_int"]==1
    assert value["qualified"]==value["network_requests"]==value["target_calls"]==0
    assert value["sha256"]==digest({k:v for k,v in value.items() if k!="sha256"})
    with pytest.raises(FileExistsError):triage_cli.dispatch(args)


@pytest.mark.parametrize("change",["duplicate","reorder","extra","schema","too_many"])
def test_frozen_batch_manifest_rejects_identity_or_schema_changes(change):
    value=manifest()
    if change=="duplicate":value["records"]*=2
    elif change=="reorder":value["expected_candidate_ids"]=["d"*64]
    elif change=="extra":value["external_command"]="never execute"
    elif change=="schema":value["schema"]="UNKNOWN"
    else:value["records"]*=65
    with pytest.raises(ValueError):triage_cli.triage_manifest(value)


@pytest.mark.parametrize("raw",['{"schema":"a","schema":"b"}','{"schema":NaN}'])
def test_duplicate_or_nonfinite_json_is_not_silently_accepted(tmp_path,raw):
    path=tmp_path/"input.json";path.write_text(raw,encoding="utf-8")
    with pytest.raises(ValueError):triage_cli.dispatch(SimpleNamespace(command="harvest-triage",manifest=path,output=tmp_path/"output.json"))
    assert not (tmp_path/"output.json").exists()


def test_oversized_manifest_rejected_before_json_parse(tmp_path,monkeypatch):
    path=tmp_path/"input.json";path.write_text("{}",encoding="utf-8")
    monkeypatch.setattr(triage_cli,"MAX_MANIFEST_BYTES",1)
    with pytest.raises(ValueError):triage_cli.dispatch(SimpleNamespace(command="harvest-triage",manifest=path,output=tmp_path/"output.json"))


def test_actual_cli_completes_classification_while_preserving_a_row_hold(tmp_path):
    value=manifest();value["records"][0]["files_complete"]=False
    path=tmp_path/"input.json";output=tmp_path/"result.json"
    path.write_text(json.dumps(value),encoding="utf-8")
    run=subprocess.run([sys.executable,"-m","tomolab","harvest-triage","--manifest",str(path),"--output",str(output)],capture_output=True,text=True,timeout=30,check=False)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result["status"]=="COMPLETE" and result["outcomes"]=={"HOLD_INSUFFICIENT_STATIC_EVIDENCE":1}
    assert result["qualified"]==result["target_calls"]==result["oracle_calls"]==0
