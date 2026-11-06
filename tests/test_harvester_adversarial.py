"""Independent boundary checks using authored API bytes, never external execution."""
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest

from tomolab.discovery.harvester_github import GitHubRestClient, GitHubAPIError, discover_batch, next_page
from tomolab.discovery.harvester_registry import HarvestRegistry


def _response(data, headers=None, status=200):
    return status, headers or {}, json.dumps(data).encode("utf-8")


@pytest.mark.parametrize("endpoint", [
    "https://api.github.com.evil.invalid/repos/example/repo",
    "https://api.github.com@evil.invalid/repos/example/repo",
    "http://api.github.com/repos/example/repo",
    "//evil.invalid/repos/example/repo",
    "/repos/example/repo#ignore-contract",
    "/repos/example/repo/contents/../secret?ref="+"a"*40,
])
def test_untrusted_api_origins_never_reach_authenticated_transport(tmp_path, endpoint):
    calls=[]
    client=GitHubRestClient(tmp_path,transport=lambda *args:calls.append(args))
    with pytest.raises(ValueError):
        client.get(endpoint)
    assert calls==[]


@pytest.mark.parametrize("following", [
    "https://evil.invalid/search/issues?q=approved&per_page=2&page=2",
    "https://api.github.com/search/issues?q=changed&per_page=2&page=2",
    "https://api.github.com/repos/example/repo?per_page=2&page=2",
    "https://api.github.com/search/issues?q=approved&per_page=2&page=1",
])
def test_pagination_cannot_expand_frozen_route_or_query(following):
    with pytest.raises(ValueError):
        next_page('<'+following+'>; rel="next"', '/search/issues?q=approved&per_page=2&page=1')


def test_corrupt_cached_object_is_rejected_before_network_or_304(tmp_path):
    calls=[]
    def transport(endpoint, headers):
        calls.append(headers)
        return _response({"id":1},{"etag":'"authored-v1"'})
    client=GitHubRestClient(tmp_path,transport=transport)
    result=client.get('/repos/example/repo')
    (tmp_path/'objects'/(result['raw_sha256']+'.json')).write_bytes(b'{"id":2}')
    with pytest.raises(GitHubAPIError,match='DIGEST'):
        client.get('/repos/example/repo')
    assert len(calls)==1


def test_non_success_response_cannot_become_a_successful_304_cache(tmp_path):
    replies=iter([_response({"message":"authored denial"},{"etag":'"denied"'},403),
                  (304,{},b'')])
    client=GitHubRestClient(tmp_path,transport=lambda *args:next(replies))
    with pytest.raises(GitHubAPIError):
        client.get('/repos/example/repo')
    # Simulate expiry of the recorded wait; no target or scientific retry occurs.
    client._blocked_until=0
    with pytest.raises(GitHubAPIError,match='304'):
        client.get('/repos/example/repo')


def test_server_credentials_and_cookies_do_not_enter_cache_or_ledger(tmp_path):
    marker='AUTHORED_PRIVATE_HEADER_SENTINEL'
    client=GitHubRestClient(tmp_path,transport=lambda *args:_response({"id":1},
        {"Authorization":"Bearer "+marker,"Set-Cookie":marker,"etag":'"safe"'}))
    client.get('/repos/example/repo')
    assert marker not in json.dumps(client.ledger)
    assert all(marker not in p.read_text(encoding='utf-8') for p in (tmp_path/'index').glob('*.json'))


def test_malformed_search_item_is_recorded_as_hold_in_partial_batch(tmp_path):
    def transport(endpoint, headers):
        if endpoint=='/repos/example/repo':
            return _response({"id":17,"private":False,"full_name":"example/repo","license":{"spdx_id":"MIT"}})
        return _response({"items":["authored malformed row"],"incomplete_results":False})
    client=GitHubRestClient(tmp_path,transport=transport)
    batch=discover_batch(client,['example/repo'],max_candidates=1,max_details=0,max_qualifications=0)
    assert batch['candidates']==[]
    assert batch['holds']
    assert batch['caps']['metadata_received']==1
    assert len(batch['api_ledger'])==2


def _blob(raw,path,license_spdx=None):
    result={"encoding":"base64","content":base64.b64encode(raw).decode(),"size":len(raw),
        "sha":hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),"path":path,"type":"file"}
    if license_spdx is not None:
        result['license']={"spdx_id":license_spdx}
    return result


def _authored_provenance_transport(*, malformed_commit=False):
    buggy=b'def implementation(point):\n    return point + 1\n'
    fixed=b'def implementation(point):\n    return point\n'
    fixed_blob=_blob(fixed,'src.py')
    def transport(endpoint,headers):
        route=urlsplit(endpoint).path
        if route=='/repos/example/repo':
            return _response({"id":17,"private":False,"full_name":"example/repo","license":{"spdx_id":"MIT"}})
        if route=='/search/issues':
            return _response({"items":[{"number":1,"title":"Fix authored functional fixture", "html_url":"https://github.com/example/repo/pull/1","pull_request":{}}],"incomplete_results":False})
        if route=='/repos/example/repo/pulls/1':
            return _response({"number":1,"base":{"repo":{"full_name":"example/repo"},"sha":"c"*40},"head":{"sha":"d"*40},"merged":True,"merge_commit_sha":"b"*40,"body":"Authored bytes only; no commands execute."})
        if route=='/repos/example/repo/commits/'+"b"*40:
            return _response([] if malformed_commit else {"sha":"b"*40,"parents":[{"sha":"a"*40}]})
        if route=='/repos/example/repo/pulls/1/files':
            return _response([{"filename":"src.py","status":"modified","sha":fixed_blob['sha'],"additions":1,"deletions":1,"patch":"@@ -1 +1 @@\n-old\n+new"},
                {"filename":"tests/test_authored.py","status":"added","sha":"e"*40,"additions":1,"deletions":0,"patch":"@@ -0,0 +1 @@\n+assert identity(1)==1"}])
        if route=='/repos/example/repo/license':
            return _response(_blob(b'Authored Apache-2.0 license bytes','LICENSE','Apache-2.0'))
        if route=='/repos/example/repo/contents/src.py':
            ref=parse_qs(urlsplit(endpoint).query)['ref'][0]
            return _response(_blob(fixed if ref=="b"*40 else buggy,'src.py'))
        raise AssertionError(endpoint)
    return transport


def test_fixed_revision_license_identity_comes_from_fixed_license_response(tmp_path):
    client=GitHubRestClient(tmp_path,transport=_authored_provenance_transport())
    batch=discover_batch(client,['example/repo'],max_candidates=1,max_details=1,max_qualifications=1)
    candidate=batch['candidates'][0]
    assert candidate['license']['revision']=="b"*40
    assert candidate['license']['spdx_id']=='Apache-2.0'
    assert candidate['license']['status']=='ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW'
    assert candidate['stage']=='PROVENANCE_VERIFIED'
    assert 'DEVELOPMENT_ELIGIBLE' not in json.dumps(candidate)


def test_non_object_commit_retains_candidate_and_partial_provenance(tmp_path):
    client=GitHubRestClient(tmp_path,transport=_authored_provenance_transport(malformed_commit=True))
    batch=discover_batch(client,['example/repo'],max_candidates=1,max_details=1,max_qualifications=1)
    assert len(batch['candidates'])==1
    assert batch['holds']
    assert batch['candidates'][0]['fixed_revision'] is None
    assert batch['candidates'][0]['stage']=='DISCOVERED'


def test_dangling_registry_symlink_cannot_redirect_an_append(tmp_path):
    store=HarvestRegistry(tmp_path/'workspace')
    target=tmp_path/'outside-journal.jsonl'
    try:
        store.path.symlink_to(target)
    except (OSError,NotImplementedError):
        pytest.skip('symlink capability unavailable on this host')
    with pytest.raises(ValueError):
        store.append('BATCH',{'authored':True},batch_id='authored-batch')
    assert not target.exists()


def _authored_candidate(tmp_path):
    client=GitHubRestClient(tmp_path/'cache',transport=_authored_provenance_transport())
    return discover_batch(client,['example/repo'],max_candidates=1,max_details=1,max_qualifications=1)['candidates'][0]


def _authored_review(candidate, **overrides):
    from tomolab.discovery.harvester_review import make_review, static_source_review
    from tomolab.discovery.schema import digest
    buggy=next(row for row in candidate['source_blobs'] if row['revision']==candidate['buggy_revision'])
    fixed=next(row for row in candidate['source_blobs'] if row['revision']==candidate['fixed_revision'])
    original=dict(project=candidate['repository'],path=buggy['path'],function='implementation')
    identity=dict(canonical_function_identity=digest(dict(original,revision=candidate['buggy_revision'])),
        cross_revision_function_key=digest(original),implementation_sha256=buggy['sha256'],
        normalized_ast_clone_sha256=static_source_review(buggy['text'])['functions'][0]['normalized_ast_clone_sha256'])
    options=dict(contract={'kind':'int','low':-5,'high':5},implementation_sha256=buggy['sha256'],
        fixed_implementation_sha256=fixed['sha256'],oracle_sha256=hashlib.sha256(b'authored independent specification Oracle').hexdigest(),
        reset_adapter_sha256=hashlib.sha256(b'authored fresh-reset adapter').hexdigest(),function_identity=identity,
        lineage=dict(source_lineage_id='authored-a',project_id=candidate['repository'].replace('/', '.'),mechanism_id='authored-mechanism',independence_id='authored-unit'),
        review_ids={name:'authored-'+name for name in ('contract_review_id','oracle_review_id','reset_review_id','license_review_id','reviewer_id')},
        oracle_independence_basis='Authored functional fixture with an independently stated expected-behavior contract; no real project claim.')
    options.update(overrides)
    return make_review(candidate,**options)


def test_verified_parent_sha_advances_only_to_review_queue(tmp_path):
    from tomolab.discovery.harvester_review import assess_candidate
    candidate=_authored_candidate(tmp_path)
    result=assess_candidate(candidate)
    assert result['status']=='HOLD_REVIEW'
    assert result['completed_stages']==['DISCOVERED','PROVENANCE_VERIFIED']


def test_absent_consumed_registry_cannot_silently_authorize_independent_source(tmp_path):
    from tomolab.discovery.harvester_review import build_consumed_registry
    with pytest.raises(ValueError):
        build_consumed_registry(root=tmp_path/'missing-public-registry')


def test_final_or_validation_split_is_not_accepted_as_development_review(tmp_path):
    candidate=_authored_candidate(tmp_path)
    for split in ('final','validation'):
        with pytest.raises(PermissionError):
            _authored_review(candidate,split=split)


def test_fixed_implementation_bytes_cannot_be_renamed_independent_oracle(tmp_path):
    candidate=_authored_candidate(tmp_path)
    fixed=next(row for row in candidate['source_blobs'] if row['revision']==candidate['fixed_revision'])
    with pytest.raises(ValueError,match='Oracle'):
        _authored_review(candidate,oracle_sha256=fixed['sha256'])


def test_a_reshashed_review_cannot_change_discovered_candidate_binding(tmp_path):
    from tomolab.discovery.harvester_review import validate_review_bundle
    from tomolab.discovery.schema import digest
    candidate=_authored_candidate(tmp_path)
    review=_authored_review(candidate)
    review['metadata_digest']='f'*64
    review['review_digest']=digest({k:v for k,v in review.items() if k!='review_digest'})
    with pytest.raises(ValueError,match='exact discovered'):
        validate_review_bundle(candidate,review)


def test_source_review_never_executes_top_level_instructions(tmp_path):
    from tomolab.discovery.harvester_review import static_source_review
    marker=tmp_path/'must-not-exist'
    source='from pathlib import Path\nPath('+repr(str(marker))+').write_text("UNTRUSTED")\ndef implementation(point):\n    return point\n'
    result=static_source_review(source)
    assert result['host_imported'] is False
    assert result['status']=='STATIC_ONLY'
    assert not marker.exists()


def test_rehashed_function_fingerprint_cannot_bypass_consumed_clone_guard(tmp_path):
    from tomolab.discovery.harvester_review import validate_review_bundle
    from tomolab.discovery.schema import digest
    candidate=_authored_candidate(tmp_path)
    review=_authored_review(candidate)
    review['function_identity']['normalized_ast_clone_sha256']='f'*64
    review['review_digest']=digest({k:v for k,v in review.items() if k!='review_digest'})
    with pytest.raises(ValueError,match='fingerprints'):
        validate_review_bundle(candidate,review)


def test_truthy_nonboolean_is_not_accountable_review_authority(tmp_path):
    from tomolab.discovery.harvester_review import assess_candidate
    candidate=_authored_candidate(tmp_path)
    review=_authored_review(candidate)
    for flag in ('yes',1,{'reviewed':True}):
        try:
            result=assess_candidate(candidate,review=review,trusted_review=flag)
        except (PermissionError,ValueError,TypeError):
            continue
        assert 'ORACLE_REVIEWED' not in result['completed_stages']
        assert result['status']!='DEVELOPMENT_ELIGIBLE'


def test_external_execution_opt_in_is_boolean_and_precedes_staging(tmp_path,monkeypatch):
    from tomolab.discovery import harvester_execution as execution
    attempts=[]
    monkeypatch.setattr(execution,'_launcher',lambda:attempts.append('must-not-launch'))
    for allowed,trusted in ((False,True),(True,False),('yes',True),(True,'yes'),(1,True)):
        output=tmp_path/('blocked-'+str(len(attempts)))
        with pytest.raises(PermissionError):
            execution.execute_reviewed_case({}, {}, {},variant='buggy',input=0,image='authored-image',
                output_directory=output,allow_external_execution=allowed,trusted_review=trusted)
        assert not output.exists()
    assert attempts==[]


def test_source_bundle_creation_hashes_but_never_imports_upstream_source(tmp_path):
    from tomolab.discovery.harvester_execution import make_source_bundle
    marker=tmp_path/'host-import-would-create-this'
    upstream='from pathlib import Path\nPath('+repr(str(marker))+').write_text("UNTRUSTED")\ndef implementation(point):\n    return point\n'
    bundle=make_source_bundle(upstream,'def implementation(point):\n    return point\n',
        'def reference(point):\n    return point\n','def reset():\n    return True\n')
    assert bundle['files']['buggy']['sha256']==hashlib.sha256(upstream.encode()).hexdigest()
    assert not marker.exists()


def test_rehashed_source_bundle_export_cannot_change_reviewed_callable():
    from tomolab.discovery.harvester_execution import make_source_bundle,validate_source_bundle
    from tomolab.discovery.schema import digest
    bundle=make_source_bundle('def implementation(point):\n    return point+1\n',
        'def implementation(point):\n    return point\n','def reference(point):\n    return point\n','def reset():\n    return True\n')
    review=dict(implementation_sha256=bundle['files']['buggy']['sha256'],
        fixed_implementation_sha256=bundle['files']['fixed']['sha256'],oracle_sha256=bundle['files']['oracle']['sha256'],
        reset_adapter_sha256=bundle['files']['reset']['sha256'],exports={name:row['function'] for name,row in bundle['files'].items()})
    bundle['files']['buggy']['function']='other_function'
    bundle['bundle_digest']=digest({k:v for k,v in bundle.items() if k!='bundle_digest'})
    with pytest.raises(ValueError,match='exports'):
        validate_source_bundle(bundle,review=review)


def test_controller_output_limit_is_enforced_on_authored_host_fixture():
    import sys
    from tomolab.discovery.harvester_execution import _bounded_run,ExecutionOutputLimit
    with pytest.raises(ExecutionOutputLimit):
        _bounded_run([sys.executable,'-c','import sys; sys.stdout.write("x"*600000); sys.stdout.flush()'],timeout=5)


def test_controller_timeout_stops_authored_host_fixture():
    import sys
    import subprocess
    from tomolab.discovery.harvester_execution import _bounded_run
    with pytest.raises(subprocess.TimeoutExpired):
        _bounded_run([sys.executable,'-c','import time; time.sleep(5)'],timeout=0.1)


def test_complete_external_execution_requires_immutable_runtime_identity(tmp_path,monkeypatch):
    from test_harvester_execution import mock_launcher,execute_fixture
    from test_harvester_review import candidate_fixture,review_fixture,resign
    from tomolab.discovery.harvester_execution import validate_execution_receipt
    mock_launcher(monkeypatch)
    receipt=execute_fixture(tmp_path,'buggy')
    receipt['runtime_digest']=None
    resign(receipt,'sha256')
    with pytest.raises(ValueError):
        validate_execution_receipt(candidate_fixture(),review_fixture(),receipt)


@pytest.mark.parametrize('mutation',['bundle','image'])
def test_buggy_fixed_reproduction_requires_same_frozen_environment(tmp_path,monkeypatch,mutation):
    from copy import deepcopy
    from test_harvester_execution import reproduction_fixture
    from test_harvester_review import candidate_fixture,review_fixture,resign
    from tomolab.discovery.harvester_execution import make_reproduction_receipt
    from tomolab.discovery.schema import digest
    original=reproduction_fixture(tmp_path,monkeypatch)
    buggy=deepcopy(original['buggy'])
    row=buggy[0]['target']
    if mutation=='bundle':
        row['bundle_digest']='f'*64
    else:
        row['boundary']['inspection']['image_id']='sha256:'+'b'*64
        row['boundary']['runtime']['binding']['image_id']='sha256:'+'b'*64
        row['boundary']['runtime']['binding_digest']=digest(row['boundary']['runtime']['binding'])
    resign(row,'sha256')
    result=make_reproduction_receipt(candidate_fixture(),review_fixture(),buggy,original['fixed'])
    assert result['status']=='HOLD_EXECUTION'
    assert result['external_target_calls']==result['external_oracle_calls']==6


@pytest.mark.parametrize('mutation',['same_receipt','same_container'])
def test_repeating_one_call_record_cannot_fake_three_fresh_reproductions(tmp_path,monkeypatch,mutation):
    from copy import deepcopy
    from test_harvester_execution import reproduction_fixture
    from test_harvester_review import candidate_fixture,review_fixture,resign
    from tomolab.discovery.harvester_execution import make_reproduction_receipt
    original=reproduction_fixture(tmp_path,monkeypatch)
    buggy=[deepcopy(original['buggy'][0]) for _ in range(3)]
    fixed=[deepcopy(original['fixed'][0]) for _ in range(3)]
    if mutation=='same_container':
        for branch in (buggy,fixed):
            for index,pair in enumerate(branch):
                for row in pair.values():
                    row['cost']['wall_seconds']+=index*0.001
                    resign(row,'sha256')
    try:
        result=make_reproduction_receipt(candidate_fixture(),review_fixture(),buggy,fixed)
    except (ValueError,PermissionError):
        return
    assert result['status']=='HOLD_EXECUTION'


def test_a_registry_label_alone_cannot_feed_real_recursive_learning(tmp_path):
    from tomolab.discovery.harvester_learning import learn_from_harvest
    registry=HarvestRegistry(tmp_path/'harvest')
    ids=['authored-'+str(index) for index in range(4)]
    for cid in ids:
        registry.register({'candidate_id':cid},{'status':'DEVELOPMENT_ELIGIBLE'},batch_id='authored-registration')
    generation_store=tmp_path/'generations.jsonl'
    with pytest.raises(PermissionError,match='reviewed Oracle'):
        learn_from_harvest(registry.workspace,ids,[],{},generation_store,
            generation_id='G1',allow_reviewed_development=True)
    assert not generation_store.exists()


@pytest.mark.parametrize('verdict',['HOLD_NO_LOCAL_SIGNAL','HOLD_MEASUREMENT'])
def test_negative_or_incomplete_m0_cannot_reach_generation_update(tmp_path,monkeypatch,verdict):
    # Authored registry-control fixture. No public candidate is promoted, no
    # target executes, and no experiment is represented as real evidence.
    from tomolab.discovery import harvester_learning as learning
    from tomolab.discovery.recursive_policy import make_development_manifest
    from tomolab.discovery.schema import digest
    registry=HarvestRegistry(tmp_path/'registry')
    lineages=[dict(source_lineage_id='authored-'+str(i),project_id='authored.project-'+str(i%2),
        mechanism_id='authored-mechanism-'+str(i%2),independence_id='authored-unit-'+str(i),
        implementation_sha256=digest({'authored':i}),oracle_sha256='a'*64,input_contract_sha256='b'*64,
        review_id='authored-review') for i in range(4)]
    experiment='c'*64
    manifest=make_development_manifest(lineages,experiment,evidence_class='REVIEWED_REAL_DEVELOPMENT')
    registry.append('M0',dict(phase='COMPLETE',experiment_contract_sha256=experiment,
        evidence_class='REVIEWED_REAL_DEVELOPMENT',paired_receipt_digests=[],
        measurement_verdict={'status':verdict}),batch_id='authored-m0')
    monkeypatch.setattr(learning,'_qualified_rows',lambda *args:[{'lineage':row} for row in lineages])
    reached=[]
    monkeypatch.setattr(learning,'_append_update',lambda *args,**kwargs:reached.append('must-not-update'))
    with pytest.raises(PermissionError):
        learning.learn_from_harvest(registry.workspace,['candidate-'+str(i) for i in range(4)],[],manifest,
            tmp_path/'generation.jsonl',generation_id='G1',allow_reviewed_development=True)
    assert reached==[]
    assert not (tmp_path/'generation.jsonl').exists()


@pytest.mark.parametrize('condition',['unresolved','unknown','target','oracle','wall'])
def test_research_budget_cannot_ignore_prior_or_unresolved_cost(tmp_path,condition):
    from tomolab.discovery.harvester_learning import _reserve_research_budget
    registry=HarvestRegistry(tmp_path/'budget')
    registry.append('M0',dict(phase='START',experiment_contract_sha256='a'*64,
        evidence_class='REVIEWED_REAL_DEVELOPMENT'),batch_id='authored-start')
    if condition!='unresolved':
        registry.append('M0',dict(phase='COMPLETE',experiment_contract_sha256='a'*64,
            evidence_class='REVIEWED_REAL_DEVELOPMENT',adapter_target_attempts=9000 if condition=='target' else 0,
            adapter_oracle_attempts=9000 if condition=='oracle' else 0,wall_seconds=2500 if condition=='wall' else 0,
            unknown_external_call_records=1 if condition=='unknown' else 0),batch_id='authored-complete')
    before=registry.path.read_bytes()
    with pytest.raises(PermissionError):
        _reserve_research_budget(registry,[])
    assert registry.path.read_bytes()==before


def test_shared_deadline_blocks_next_external_entry_and_reset(monkeypatch):
    from types import SimpleNamespace
    from tomolab.discovery import harvester_learning as learning
    calls=[]
    class Delegate:
        ledger={'wrapper_entries':0}
        timeout=30
        def reset(self):
            calls.append('reset')
            return True
        def __call__(self,point):
            calls.append(point)
            return point
    delegate=Delegate()
    monkeypatch.setattr(learning,'time',SimpleNamespace(perf_counter=lambda:100.0))
    wrapped=learning._DeadlineCallable(delegate,104.0)
    assert wrapped.reset() is False
    with pytest.raises(OSError,match='deadline'):
        wrapped(7)
    assert calls==[]
    assert delegate.ledger['wrapper_entries']==1


def test_shared_deadline_reduces_per_call_timeout_before_entry(monkeypatch):
    from types import SimpleNamespace
    from tomolab.discovery import harvester_learning as learning
    class Delegate:
        ledger={'wrapper_entries':0}
        timeout=30
        def reset(self):
            return True
        def __call__(self,point):
            return self.timeout
    delegate=Delegate()
    monkeypatch.setattr(learning,'time',SimpleNamespace(perf_counter=lambda:100.0))
    wrapped=learning._DeadlineCallable(delegate,120.0)
    assert wrapped(7)==15
    assert wrapped.reset() is True


def test_duplicate_paired_execution_cannot_inflate_m0_signal():
    from test_recursive_policy import fixture_batch
    from tomolab.discovery.harvester_learning import m0_verdict
    receipts,_=fixture_batch([('authored-a','gain'),('authored-b','gain'),
        ('authored-c','neutral_pass'),('authored-d','neutral_failure')])
    lineages=['authored-a','authored-b','authored-c','authored-d']
    assert m0_verdict(receipts,lineages)['status']=='LOCAL_SIGNAL_OBSERVED'
    with pytest.raises(ValueError,match='duplicated'):
        m0_verdict(receipts+[receipts[0]],lineages)
