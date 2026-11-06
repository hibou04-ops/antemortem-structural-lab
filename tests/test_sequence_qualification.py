"""First-party specification and mocked controller checks; upstream execution0."""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path

import pytest

from tomolab.discovery import sequence_qualification as q
from tomolab.discovery import harvester_execution as execution
from tomolab.discovery.schema import digest
from test_harvester_execution import mock_launcher
from test_harvester_review import candidate_fixture, review_fixture, ORACLE

IMAGE="sha256:"+"a"*64


def public_manifest():
    return json.loads((Path(__file__).parents[1]/"docs/SEQUENCE_QUALIFICATION_V7_20261101.json").read_bytes())


def fixture_manifest(monkeypatch):
    candidate=candidate_fixture();review=review_fixture(candidate)
    monkeypatch.setitem(q.ORACLE_SOURCES,"WHOLE_VALUE_COUNT_SORT",ORACLE)
    case=dict(case_id=candidate["candidate_id"],projection=q.public_projection(candidate),source_path="module.py",function="implementation",
        function_identity=review["function_identity"],contract=review["contract"],witness=[1,1],witness_origin="AUTHORED_FIXTURE_NOT_REAL_RESEARCH",
        oracle_key="WHOLE_VALUE_COUNT_SORT",oracle_sha256=review["oracle_sha256"],reset_sha256=review["reset_adapter_sha256"],
        lineage=review["lineage"],review_ids=review["review_ids"],oracle_independence_basis=review["oracle_independence_basis"],
        review_digest=review["review_digest"],static_contract_support_digest="d"*64,contract_scope="AUTHORED_FIXTURE")
    manifest=dict(schema=q.SCHEMA,track=q.TRACK,plan_digest="b"*64,scope="AUTHORED_FIXTURE_ONLY",cases=[case],
        resource_caps=dict(target_calls=6,oracle_calls=6,fresh_reset_count=12,fresh_containers=12,
            controller_seconds=600,per_call_seconds=30,cleanup_reserve_seconds=20),
        historical_text=dict(track="TRACK_TEXT",qualified=1,reproduced=1,this_run_target_calls=0,this_run_oracle_calls=0))
    manifest["manifest_digest"]=digest(manifest)
    monkeypatch.setattr(q,"APPROVED_MANIFEST_DIGEST",manifest["manifest_digest"])
    payloads={"source0":candidate["source_blobs"][0]["text"].encode(),"source1":candidate["source_blobs"][1]["text"].encode(),
        "license":candidate["license"]["text"].encode()}
    urls={url:payloads[role] for role,url,_,_ in q._urls(case)}
    downloads=[]
    def download(url,**kwargs):
        downloads.append(url)
        return urls[url]
    monkeypatch.setattr(q,"_download",download)
    return manifest,downloads


class AuthoredCleanup:
    """Simulated cleanup evidence, never real boundary proof."""
    def __init__(self,deadline):self.deadline=deadline
    def factory(self):return execution._launcher()
    def evidence(self):return dict(status="PASS",create_attempted=True,cleanup=[dict(status="PASS",removed=True,absence_verified=True)],cli_calls=[])


@pytest.mark.parametrize("point,expected",[([20,10],[10,20]),([0],[0]),([99,0,99,10],[0,10,99,99]),([1,0],[0,1])])
def test_whole_value_counting_spec_preserves_multiset_and_order(point,expected):
    original=deepcopy(point)
    assert q.whole_value_reference(point)==expected and point==original


def test_whole_value_spec_matches_declarative_order_over_bounded_small_product():
    for n in range(1,5):
        for point in itertools.product((0,1,10,20,99),repeat=n):
            assert q.whole_value_reference(list(point))==sorted(point)


@pytest.mark.parametrize("point,expected",[([1],[2]),([0,0],[0,1]),([0,0,9],[0,1,0]),([9,9],[1,0,0]),([0,9,9],[1,0,0]),([0],[1])])
def test_decimal_spec_explicitly_preserves_width_and_carry(point,expected):
    original=deepcopy(point)
    assert q.decimal_increment_reference(point)==expected and point==original


def test_decimal_spec_mathematical_value_width_and_digit_range():
    for n in range(1,5):
        for point in itertools.product((0,1,9),repeat=n):
            result=q.decimal_increment_reference(list(point))
            assert int("".join(map(str,result)))==int("".join(map(str,point)))+1
            assert len(result)>=len(point) and len(result)<=len(point)+1
            assert all(type(x) is int and 0<=x<=9 for x in result)


@pytest.mark.parametrize("point",[[],[True],[1.0],[[1]],[100],"1"])
def test_own_sort_spec_rejects_unsupported_input_without_coercion(point):
    with pytest.raises(ValueError):q.whole_value_reference(point)


def test_public_projection_has_no_upstream_bodies_or_private_routes():
    manifest=public_manifest();q.validate_manifest(manifest)
    text=json.dumps(manifest)
    assert "drive.google" not in text and "C:\\" not in text and "G:\\" not in text
    assert len(manifest["cases"])==2
    assert manifest["resource_caps"]["target_calls"]==manifest["resource_caps"]["oracle_calls"]==12
    assert manifest["resource_caps"]["fresh_reset_count"]==24
    assert manifest["historical_text"]["reexecuted"] is False
    for case in manifest["cases"]:
        assert all("text" not in row for row in case["projection"]["source_blobs"])
        assert "text" not in case["projection"]["license"]
        assert all("text" not in row for row in case["projection"]["test_evidence"]["patches"])


def test_manifest_rehash_cannot_self_authorize_unreviewed_case(tmp_path,monkeypatch):
    manifest=public_manifest();manifest["cases"][0]["witness"]=[30,20]
    manifest["manifest_digest"]=digest({k:v for k,v in manifest.items() if k!="manifest_digest"})
    monkeypatch.setattr(q,"_download",lambda *a,**k:pytest.fail("must not download"))
    with pytest.raises(PermissionError):q.run_sequence_qualification(tmp_path/"never",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)
    assert not (tmp_path/"never").exists()


@pytest.mark.parametrize("external,review",[(False,False),(True,False),(False,True)])
def test_dual_opt_in_default_disables_download_subprocess_and_external_calls(tmp_path,monkeypatch,external,review):
    monkeypatch.setattr(q,"_download",lambda *a,**k:pytest.fail("disabled path must not download"))
    monkeypatch.setattr(execution,"execute_reviewed_case",lambda *a,**k:pytest.fail("disabled path must not enter OCI"))
    value=q.run_sequence_qualification(tmp_path/"disabled",manifest=public_manifest(),image=IMAGE,
        allow_external_execution=external,trusted_review=review)["receipt"]
    assert value["status"]=="HOLD_EXECUTION" and value["wrapper_execution_attempts"]==0
    assert value["actual_entry_counts"]==dict(external_target_calls=0,external_oracle_calls=0,external_reset_calls=0)
    assert value["m0_status"]=="NOT_EXECUTED" and value["m0_pair_count"]==0
    assert value["this_run_text_target_calls"]==value["this_run_text_oracle_calls"]==0


@pytest.mark.parametrize("value",[1,"true",None])
def test_truthy_nonbool_is_not_execution_or_review_authority(tmp_path,value):
    with pytest.raises(PermissionError):q.run_sequence_qualification(tmp_path/"x",manifest=public_manifest(),image=IMAGE,allow_external_execution=value,trusted_review=True)
    with pytest.raises(PermissionError):q.run_sequence_qualification(tmp_path/"y",manifest=public_manifest(),image=IMAGE,allow_external_execution=True,trusted_review=value)


def test_one_use_workspace_cannot_retry_or_overwrite(tmp_path,monkeypatch):
    location=tmp_path/"once"
    q.run_sequence_qualification(location,manifest=public_manifest(),image=IMAGE)
    with pytest.raises(FileExistsError):q.run_sequence_qualification(location,manifest=public_manifest(),image=IMAGE)


def test_mocked_exact12_receipts_separate_wrapper_and_actual_external_counts(tmp_path,monkeypatch):
    manifest,downloads=fixture_manifest(monkeypatch)
    calls=mock_launcher(monkeypatch)
    monkeypatch.setattr(q,"_DeadlineLauncher",AuthoredCleanup)
    result=q.run_sequence_qualification(tmp_path/"mocked",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert len(calls)==12 and len(downloads)==3 and result["status"]=="REPRODUCED"
    assert result["wrapper_execution_attempts"]==result["validated_execution_receipts"]==result["actual_distinct_container_ids"]==12
    assert result["actual_entry_counts"]==dict(external_target_calls=6,external_oracle_calls=6,external_reset_calls=12)
    assert result["unknown_external_call_records"]==0 and result["learning_updates"]==0
    assert result["m0_status"]=="NOT_EXECUTED" and result["utility"]==result["oos"]=="NOT_ESTABLISHED"
    assert result["equal_cost_comparison_status"]=="NOT_EXECUTED" and result["equal_cost_pair_count"]==0
    assert result["local_gain"] is result["local_loss"] is result["measurement_unknown"] is None
    assert result["actual_source_host_imports"]==result["actual_source_host_execution"]==0


def test_pinned_source_tamper_holds_before_external_entry(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    monkeypatch.setattr(q,"_download",lambda *a,**k:b"untrusted altered bytes")
    monkeypatch.setattr(execution,"execute_reviewed_case",lambda *a,**k:pytest.fail("must not enter with wrong original bytes"))
    result=q.run_sequence_qualification(tmp_path/"tampered",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert result["status"]=="HOLD_EXECUTION" and result["wrapper_execution_attempts"]==0


def test_first_unknown_cleanup_stops_without_oracle_retry_or_substitution(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch);calls=mock_launcher(monkeypatch)
    class UnknownCleanup(AuthoredCleanup):
        def evidence(self):return dict(status="UNKNOWN",create_attempted=True,cleanup=[])
    monkeypatch.setattr(q,"_DeadlineLauncher",UnknownCleanup)
    result=q.run_sequence_qualification(tmp_path/"cleanup",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert len(calls)==1 and result["status"]=="HOLD_EXECUTION"
    assert result["actual_entry_counts"]==dict(external_target_calls=1,external_oracle_calls=0,external_reset_calls=1)
    assert result["automatic_retries"]==result["substitutions"]==0 and "UNKNOWN_CLEANUP" in result["reasons"]


def test_protocol_exception_after_attempt_preserves_unknown_count_instead_of_zero(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    monkeypatch.setattr(q,"_DeadlineLauncher",AuthoredCleanup)
    def missing(*args,**kwargs):raise OSError("authored lost protocol fixture")
    monkeypatch.setattr(execution,"execute_reviewed_case",missing)
    result=q.run_sequence_qualification(tmp_path/"lost",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert result["wrapper_execution_attempts"]==result["unknown_external_call_records"]==1
    assert all(value is None for value in result["actual_entry_counts"].values())
    assert all(value==0 for value in result["known_call_lower_bound"].values())


def test_official_download_does_not_follow_unreviewed_redirect_or_origin():
    with pytest.raises(ValueError):q._download("http://169.254.169.254/",allowed=set(),timeout=1,maximum=100)


def test_failed_source_preparation_attempt_is_not_reported_as_zero_cost(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    def unavailable(*args,**kwargs):raise TimeoutError("authored network timeout fixture")
    monkeypatch.setattr(q,"_download",unavailable)
    result=q.run_sequence_qualification(tmp_path/"download-failed",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert result["source_preparation_attempts"]==result["source_preparation_unknown_requests"]==1
    assert result["source_preparation_ledger"][0]["response_bytes"] is None
    assert result["wrapper_execution_attempts"]==0 and result["status"]=="HOLD_EXECUTION"


def test_success_response_alias_is_rejected_even_before_hash_restore(monkeypatch):
    url="https://raw.githubusercontent.com/authored/project/"+"1"*40+"/module.py"
    class Response:
        status=200
        def geturl(self):return "https://unreviewed.invalid/alias"
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):pytest.fail("origin must be checked before body acceptance")
    class Opener:
        def open(self,*args,**kwargs):return Response()
    monkeypatch.setattr(q,"build_opener",lambda *args:Opener())
    with pytest.raises(ValueError,match="origin"):q._download(url,allowed={url},timeout=1,maximum=100)


def test_whole_batch_entry_deadline_blocks_before_oci_attempt(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    ticks=iter([0,0,0,0,580,580,580])
    monkeypatch.setattr(q.time,"monotonic",lambda:next(ticks,580))
    monkeypatch.setattr(execution,"execute_reviewed_case",lambda *a,**k:pytest.fail("deadline must block entry"))
    result=q.run_sequence_qualification(tmp_path/"deadline",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True)["receipt"]
    assert result["status"]=="HOLD_EXECUTION" and result["wrapper_execution_attempts"]==0


def test_offline_cache_reproduces_only_authored_fixture_without_any_network(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    original=q._download
    cache=tmp_path/"cache";cache.mkdir();entries={}
    for _,url,_,_ in q._urls(manifest["cases"][0]):
        raw=original(url);sha=hashlib.sha256(raw).hexdigest()
        (cache/(sha+".txt")).write_bytes(raw)
        entries[url]=dict(path=sha+".txt",sha256=sha,bytes=len(raw),role="authored",origin="AUTHORED_TEST")
    (cache/"index.json").write_text(json.dumps(dict(schema="tomolab-offline-sequence-source-v1",entries=entries)))
    monkeypatch.setattr(q,"_download",lambda *a,**k:pytest.fail("offline mode must never use network"))
    mock_launcher(monkeypatch);monkeypatch.setattr(q,"_DeadlineLauncher",AuthoredCleanup)
    result=q.run_sequence_qualification(tmp_path/"offline",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True,source_cache=cache)["receipt"]
    assert result["status"]=="REPRODUCED" and result["additional_source_gets"]==0
    assert result["source_mode"]=="OFFLINE_CACHE_NO_NETWORK_FALLBACK"
    first=next(iter(entries.values()));(cache/first["path"]).write_bytes(b"changed")
    failed=q.run_sequence_qualification(tmp_path/"tampered-offline",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True,source_cache=cache)["receipt"]
    assert failed["status"]=="HOLD_EXECUTION" and failed["wrapper_execution_attempts"]==0


def test_offline_cache_miss_holds_without_downloading_or_entering(tmp_path,monkeypatch):
    manifest,_=fixture_manifest(monkeypatch)
    monkeypatch.setattr(q,"_download",lambda *a,**k:pytest.fail("no cache fallback allowed"))
    monkeypatch.setattr(execution,"execute_reviewed_case",lambda *a,**k:pytest.fail("no missing-source entry"))
    result=q.run_sequence_qualification(tmp_path/"missing",manifest=manifest,image=IMAGE,allow_external_execution=True,trusted_review=True,source_cache=tmp_path/"absent")["receipt"]
    assert result["status"]=="HOLD_EXECUTION" and result["additional_source_gets"]==0
    assert result["wrapper_execution_attempts"]==0
