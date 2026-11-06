"""Authored mocked OCI behavior, with no claim that a real daemon ran."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.harvester_review import assess_candidate, development_lineage
from tomolab.discovery.online_observe import _snapshot
from tomolab.discovery.schema import canonical, digest
from test_harvester_review import (candidate_fixture,review_fixture,resign,BUGGY,FIXED,ORACLE,RESET)


def bundle_fixture():
    return execution.make_source_bundle(BUGGY,FIXED,ORACLE,RESET)


def boundary_fixture():
    binding = dict(container_id=uuid.uuid4().hex*2,image_id="sha256:"+"a"*64,network="none",read_only_root=True,
        user="65534:65534",cap_drop=["ALL"],no_new_privileges=True,pids_limit=64,memory_bytes=512*1024*1024,cpus=1,
        binds=[dict(destination="/app",read_only=True),dict(destination="/output",read_only=False),
               dict(destination="/boundary",read_only=True)],tmpfs="/tmp:rw,noexec,nosuid,size=64m,mode=1777")
    inspection = dict(binding,status="PASS",inspected_before_start=True)
    mounts = {point:dict(point=point,options=[mode],filesystem="overlay",super_options=[mode])
              for point,mode in (("/","ro"),("/app","ro"),("/boundary","ro"),("/output","rw"),("/tmp","rw"))}
    mounts["/tmp"].update(filesystem="tmpfs",options=["rw","noexec","nosuid"])
    runtime = dict(schema="tomolab-reviewed-historical-boundary-v1",status="PASS",operating_system="Linux",
        uid=65534,gid=65534,effective_capabilities=0,no_new_privileges=True,interfaces=["lo"],mounts=mounts,
        filesystem_probes=[dict(directory=p,outcome="OWNED_PROBE_CREATED_AND_REMOVED") for p in ("/output","/tmp")]+
            [dict(directory=p,outcome="WRITE_DENIED",errno=30) for p in ("/","/app")],
        network_route_probes=[dict(family=family,outcome="NO_EXTERNAL_ROUTE",errno=101,sent_bytes=0) for family in ("IPv4","IPv6")],
        binding=binding,binding_digest=digest(binding),sent_network_bytes=0,
        execution_scope="REVIEWED_HARVESTER_FUNCTIONS_ONLY",host_inspection_required=True,
        protection="CONTAINER_BOUNDARY_NOT_HOSTILE_HOST_PROTECTION")
    return inspection,runtime


def mock_launcher(monkeypatch, *, mutate_result=None):
    calls = []
    def docker_execute(image,command,output,*,timeout,repository):
        calls.append(dict(image=image,command=command,timeout=timeout,repository=repository))
        names = {p.relative_to(repository).as_posix() for p in repository.rglob("*") if p.is_file()}
        assert names == {"runner.py","request.json","sources/buggy.py","sources/fixed.py","sources/oracle.py",
            "sources/reset.py","runtime/tomolab/__init__.py","runtime/tomolab/historical.py",
            "runtime/tomolab/discovery/__init__.py","runtime/tomolab/discovery/schema.py",
            "runtime/tomolab/discovery/online_schema.py","runtime/tomolab/discovery/online_observe.py"}
        assert command == ["python","-I","/app/runner.py"]
        request = json.loads((repository/"request.json").read_text())
        output.mkdir()
        inspection,runtime = boundary_fixture()
        point,variant = request["input"],request["variant"]
        # This expression is the explicitly authored fixture's expected value;
        # no harvested source module is loaded or evaluated by this mock.
        value = sum(point) + (int(len(point)>1 and len(set(point))==1) if variant=="buggy" else 0)
        capture = dict(kind="return",value=_snapshot(value))
        result = dict(schema="tomolab-harvester-container-result-v1",variant=variant,input_digest=request["input_digest"],
            selected_sha256=request["files"][variant]["sha256"],reset_sha256=request["files"]["reset"]["sha256"],
            reset_success=True,external_entry_count=1,external_reset_calls=1,capture=capture,
            semantic_digest=digest(capture),boundary=runtime,diagnostic_output_sha256="0"*64)
        if mutate_result is not None:
            mutate_result(result)
        (output/"container.stdout.log").write_text(canonical(result),encoding="utf-8")
        (output/"host-inspection.json").write_text(canonical(inspection),encoding="utf-8")
        return dict(status="PASS",inspection=inspection)
    monkeypatch.setattr(execution,"_launcher",lambda:SimpleNamespace(docker_execute=docker_execute))
    return calls


def execute_fixture(tmp_path,variant, *, name=None):
    c,r,b = candidate_fixture(),review_fixture(),bundle_fixture()
    return execution.execute_reviewed_case(c,r,b,variant=variant,input=[1,1],image="reviewed-image",
        output_directory=tmp_path/(name or uuid.uuid4().hex),allow_external_execution=True,trusted_review=True)


def reproduction_fixture(tmp_path,monkeypatch):
    mock_launcher(monkeypatch)
    branches = []
    for variant in ("buggy","fixed"):
        repeats = []
        for repeat in range(3):
            repeats.append(dict(target=execute_fixture(tmp_path,variant),oracle=execute_fixture(tmp_path,"oracle")))
        branches.append(repeats)
    return execution.make_reproduction_receipt(candidate_fixture(),review_fixture(),*branches)


def test_external_execution_needs_exact_opt_in_before_any_subprocess(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,"_launcher",lambda:pytest.fail("must not invoke external launcher"))
    c,r,b = candidate_fixture(),review_fixture(),bundle_fixture()
    for opt_in in (False,1,"yes"):
        with pytest.raises(PermissionError):
            execution.execute_reviewed_case(c,r,b,variant="buggy",input=[1,1],image="reviewed-image",
                output_directory=tmp_path/"never-created",allow_external_execution=opt_in,trusted_review=True)
    assert not (tmp_path/"never-created").exists()


def test_minimal_staging_and_exactly_one_external_callable_per_wrapper(tmp_path,monkeypatch):
    calls = mock_launcher(monkeypatch)
    target = execution.OCIReviewedCallable(candidate_fixture(),review_fixture(),bundle_fixture(),variant="buggy",
        image="reviewed-image",workspace=tmp_path/"calls",allow_external_execution=True,trusted_review=True)
    assert target.reset() is True
    assert target([1,1]) == 3
    assert target.ledger["wrapper_entries"] == target.ledger["container_attempts"] == 1
    assert target.ledger["external_target_calls"] == 1 and target.ledger["external_oracle_calls"] == 0
    assert len(calls) == 1 and not calls[0]["repository"].exists()
    oracle = execute_fixture(tmp_path,"oracle")
    assert oracle["external_target_calls"] == 0 and oracle["external_oracle_calls"] == 1


def test_daemon_or_image_failure_has_no_host_fallback_and_preserves_zero_entries(tmp_path,monkeypatch):
    def unavailable():
        raise RuntimeError("authored daemon unavailable fixture")
    monkeypatch.setattr(execution,"_launcher",unavailable)
    receipt = execute_fixture(tmp_path,"buggy",name="unavailable")
    assert receipt["status"] == "HOLD_EXECUTION"
    assert receipt["external_target_calls"] == receipt["external_oracle_calls"] == 0
    assert receipt["host_external_code_imported"] is False
    assert (tmp_path/"unavailable/harvester-execution.json").is_file()


def test_reproduction_needs_buggy_failure_fixed_pass_and_actual_reset_semantics(tmp_path,monkeypatch):
    receipt = reproduction_fixture(tmp_path,monkeypatch)
    assert receipt["status"] == "REPRODUCED"
    assert receipt["external_target_calls"] == receipt["external_oracle_calls"] == 6
    assert receipt["external_reset_calls"] == 12
    c,r = candidate_fixture(),review_fixture()
    assessment = assess_candidate(c,review=r,execution_receipt=receipt,trusted_review=True)
    assert assessment["status"] == "DEVELOPMENT_ELIGIBLE"
    assert development_lineage(c,assessment,r)["input_contract_sha256"] == digest(r["contract"])
    altered = deepcopy(receipt)
    altered["buggy"][0]["target"]["reset_success"] = False
    resign(altered["buggy"][0]["target"],"sha256")
    with pytest.raises(ValueError):
        execution.validate_reproduction_receipt(c,r,resign(altered,"sha256"))


def test_mixed_execution_runtime_or_image_is_held_without_erasing_cost(tmp_path,monkeypatch):
    receipt = reproduction_fixture(tmp_path,monkeypatch)
    altered = deepcopy(receipt["buggy"])
    row = altered[0]["target"]
    row["runtime_digest"] = "f"*64
    resign(row,"sha256")
    result = execution.make_reproduction_receipt(candidate_fixture(),review_fixture(),altered,receipt["fixed"])
    assert result["status"] == "HOLD_EXECUTION"
    assert result["external_target_calls"] == result["external_oracle_calls"] == 6
    assert "FROZEN_BUNDLE_RUNTIME_IMAGE_IDENTITY_MISMATCH" in result["reasons"]


def test_weak_inspection_or_swapped_request_cannot_produce_complete_call(tmp_path,monkeypatch):
    mock_launcher(monkeypatch,mutate_result=lambda r:r["boundary"]["binding"].update(network="bridge"))
    receipt = execute_fixture(tmp_path,"buggy")
    assert receipt["status"] == "HOLD_EXECUTION"
    assert receipt["external_target_calls"] is None
    assert receipt["call_count_status"] == "UNKNOWN_AFTER_CONTAINER_START"


def test_output_and_time_limits_stop_authored_host_probe_processes():
    with pytest.raises(execution.ExecutionOutputLimit):
        execution._bounded_run([sys.executable,"-c","import sys; sys.stdout.write('x'*1000000)"],timeout=5)
    with pytest.raises(subprocess.TimeoutExpired):
        execution._bounded_run([sys.executable,"-c","import time; time.sleep(3)"],timeout=0.1)


def test_reviewed_export_binding_cannot_select_another_oracle_function():
    b = bundle_fixture()
    b["files"]["oracle"]["function"] = "different_answer"
    resign(b,"bundle_digest")
    with pytest.raises(ValueError,match="exports"):
        execution.validate_source_bundle(b,review=review_fixture())


def test_copied_receipts_do_not_become_three_actual_repetitions_or_triple_cost(tmp_path,monkeypatch):
    receipt = reproduction_fixture(tmp_path,monkeypatch)
    duplicated = [deepcopy(receipt["buggy"][0]) for _ in range(3)]
    result = execution.make_reproduction_receipt(candidate_fixture(),review_fixture(),duplicated,receipt["fixed"])
    assert result["status"] == "HOLD_EXECUTION"
    assert "DUPLICATE_EXTERNAL_CALL_RECEIPT" in result["reasons"]
    assert result["external_target_calls"] == result["external_oracle_calls"] == 4
    assert result["external_reset_calls"] == 8
