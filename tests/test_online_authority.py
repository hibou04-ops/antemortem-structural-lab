"""The online profile adds local feedback without weakening E8/final authority."""
from copy import deepcopy
import pytest
from tomolab.discovery.evaluation_usage import UsageLedger, IDENTITY_FIELDS
from tomolab.discovery.schema import digest


def setup(tmp_path):
    authority = digest({"review": "authored-functional"})
    ledger = UsageLedger(tmp_path/"usage.jsonl", authority_id=authority)
    profile = dict(schema="tomolab-online-execution-profile-v1", scope="EXPERIMENTAL_PROBE",
                   authority_id=authority, algorithm_digest=digest("code"),
                   initial_knowledge_digest=digest("mold"), configuration_digest=digest("config"),
                   target_local_feedback=True, cross_target_feedback=False,
                   final_evaluation_authorized=False, publication_authorized=False)
    identity = {name:digest({name:"identity"}) for name in IDENTITY_FIELDS}
    return ledger, profile, identity


def test_online_consumption_blocks_reuse_and_final(tmp_path):
    ledger, profile, identity = setup(tmp_path)
    row = ledger.claim_experimental([identity], profile, expected_profile=deepcopy(profile))
    assert ledger.inspect()["open_claim_ids"] == [row["claim_id"]]
    with pytest.raises(PermissionError):
        ledger.claim_experimental([identity], profile, expected_profile=profile)
    with pytest.raises(PermissionError):
        ledger.claim([identity], dict(status="PASS", bindings=dict(authority_id=ledger.authority_id)))
    ledger.complete(row["claim_id"], {"status":"COMPLETE"})
    assert ledger.inspect()["open_claim_ids"] == []


@pytest.mark.parametrize("field,value", [
    ("target_local_feedback", False), ("cross_target_feedback", True),
    ("publication_authorized", True), ("final_evaluation_authorized", True),
    ("scope", "FINAL_TARGET"), ("schema", "tomolab-corroboration-permit-v1")])
def test_no_authority_upgrade(tmp_path, field, value):
    ledger, profile, identity = setup(tmp_path)
    changed = dict(profile, **{field:value})
    with pytest.raises(PermissionError):
        ledger.claim_experimental([identity], changed, expected_profile=changed)
    assert not ledger.path.exists()


def test_host_binding_not_just_self_rehash(tmp_path):
    ledger, profile, identity = setup(tmp_path)
    changed = dict(profile, algorithm_digest=digest("different code"))
    with pytest.raises(PermissionError):
        ledger.claim_experimental([identity], changed, expected_profile=profile)
    assert not ledger.path.exists()


def test_shared_receipt_preserves_online_mapping_order_and_old_default(tmp_path):
    import hashlib
    import json
    import time
    from tomolab.e8r3_cli import save_receipt
    value = {"input": {"b": 1, "a": 2}}
    old, online = tmp_path/"old.json", tmp_path/"online.json"
    save_receipt(value, old, main_started=time.perf_counter())
    save_receipt(value, online, main_started=time.perf_counter(), preserve_mapping_order=True)
    assert old.read_bytes() == (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)+"\n").encode()
    assert list(json.loads(online.read_text())["input"]) == ["b", "a"]
    io = json.loads((tmp_path/"online.json.io.json").read_text())
    assert io["receipt_sha256"] == hashlib.sha256(online.read_bytes()).hexdigest()
