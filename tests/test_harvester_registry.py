import json
import pytest
from tomolab.discovery.harvester_registry import HarvestRegistry

def test_append_and_restart_preserve_candidate_review_and_batch_history(tmp_path):
    store=HarvestRegistry(tmp_path)
    candidate={"candidate_id":"candidate-a","repository":"example/repo"}
    assert store.register(candidate,{"status":"HOLD_REVIEW"},batch_id="batch-a")["status"]=="COMMITTED"
    before=store.path.read_bytes()
    assert HarvestRegistry(tmp_path).register(candidate,{"status":"REJECTED"},batch_id="batch-b")["status"]=="ALREADY_REGISTERED"
    assert store.path.read_bytes()==before
    store.review("candidate-a",{"status":"REJECTED"},{"reason":"observed duplicate"},None,batch_id="review-a")
    assert store.path.read_bytes().startswith(before)
    resumed=HarvestRegistry(tmp_path)
    assert resumed.assessments()["candidate-a"]["status"]=="REJECTED"
    assert resumed.known_candidate_ids()==("candidate-a",)

def test_same_event_is_idempotent_but_conflicting_payload_is_rejected(tmp_path):
    store=HarvestRegistry(tmp_path)
    store.append("BATCH",{"calls":1},batch_id="batch",event_id="event")
    assert store.append("BATCH",{"calls":1},batch_id="batch",event_id="event")["status"]=="ALREADY_COMMITTED"
    with pytest.raises(ValueError,match="conflict"):
        store.append("BATCH",{"calls":0},batch_id="batch",event_id="event")

def test_truncated_and_tampered_history_fail_closed_without_repair(tmp_path):
    store=HarvestRegistry(tmp_path)
    store.append("BATCH",{"calls":1},batch_id="batch")
    original=store.path.read_bytes()
    store.path.write_bytes(original[:-1])
    with pytest.raises(ValueError,match="partial"):
        store.records()
    assert store.path.read_bytes()==original[:-1]
    store.path.write_bytes(original.replace(b'"calls":1',b'"calls":0'))
    with pytest.raises(ValueError,match="digest"):
        store.records()

def test_lock_contention_does_not_delete_other_writer_lock(tmp_path):
    store=HarvestRegistry(tmp_path)
    lock=tmp_path/'registry.jsonl.lock'
    lock.write_text('other writer')
    with pytest.raises(FileExistsError):
        store.append("BATCH",{},batch_id="batch")
    assert lock.read_text()=='other writer'

def test_profile_supplement_preserves_original_candidate_and_review_state(tmp_path):
    from tomolab.harvester_demo import AuthoredGitHubTransport, REPOSITORIES
    from tomolab.discovery.harvester_github import GitHubRestClient, discover_batch
    from tomolab.discovery.harvester_review import candidate_profile
    client=GitHubRestClient(tmp_path/'cache',transport=AuthoredGitHubTransport())
    batch=discover_batch(client,REPOSITORIES,max_candidates=4,max_details=4,max_qualifications=4)
    candidate=batch['candidates'][0]
    registry=HarvestRegistry(tmp_path/'registry')
    registry.register(candidate,{'status':'HOLD_REVIEW'},batch_id='batch')
    before=registry.path.read_bytes()
    profile=candidate_profile(candidate)
    registry.record_profile(candidate['candidate_id'],profile,batch_id='supplement')
    after=registry.path.read_bytes()
    assert after.startswith(before) and registry.candidates()[candidate['candidate_id']]==candidate
    assert registry.assessments()[candidate['candidate_id']]['status']=='HOLD_REVIEW'
    assert registry.profiles()[candidate['candidate_id']]==profile
    registry.record_profile(candidate['candidate_id'],profile,batch_id='supplement')
    assert registry.path.read_bytes()==after
