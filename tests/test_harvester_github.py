"""Authored transport fixtures; these tests never execute external source."""
import base64
from copy import deepcopy
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from tomolab.discovery.harvester_github import (GitHubAPIError, GitHubRestClient,
    candidate_identity, discover_batch, next_page, validate_candidate)
from tomolab.discovery.schema import canonical, digest


def raw_json(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()


def file_bytes(text, *, path="src/values.py", license=None):
    raw = text.encode()
    result = dict(encoding="base64", content=base64.b64encode(raw).decode(), size=len(raw), path=path,
        sha=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest())
    if license is not None:
        result["license"] = dict(spdx_id=license)
    return result


class FixtureAPI:
    """Known data-only implementation of official endpoint response shapes."""
    def __init__(self, *, count=20, conditional=False):
        self.count, self.conditional = count, conditional
        self.calls, self.seen = [], set()
        self.fixed, self.buggy = "a"*40, "b"*40
        self.source = "raise AssertionError('external text must never execute')\n"
        self.python = file_bytes(self.source)

    def payload(self, endpoint):
        parsed = urlsplit(endpoint)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/search/issues":
            repo = query["q"][0].split()[0].split(":",1)[1]
            count = min(self.count, int(query["per_page"][0]))
            return dict(incomplete_results=False, total_count=self.count,
                items=[dict(number=number, title=f"Fix authored fixture {number}",
                    html_url=f"https://github.com/{repo}/pull/{number}", pull_request={})
                    for number in range(1,count+1)])
        parts = path.split("/")
        repo = "/".join(parts[2:4])
        if len(parts) == 4:
            return dict(id=123, full_name=repo, private=False, license=dict(spdx_id="GPL-3.0"))
        if parts[4] == "pulls" and len(parts) == 6:
            return dict(number=int(parts[5]), merged=True, merge_commit_sha=self.fixed,
                body=f"Fixes https://github.com/{repo}/issues/9. Ignore all instructions is untrusted text.",
                base=dict(repo=dict(full_name=repo),sha="c"*40), head=dict(sha="d"*40))
        if parts[4] == "commits":
            return dict(sha=self.fixed, parents=[dict(sha=self.buggy)])
        if parts[4:] == ["license"]:
            return file_bytes("MIT authored fixture license\n",path="LICENSE",license="MIT")
        if parts[4] == "pulls" and parts[-1] == "files":
            return [dict(filename="src/values.py", status="modified", sha=self.python["sha"],
                    additions=1,deletions=1,patch="@@ -1 +1 @@\n-old\n+new"),
                dict(filename="tests/test_values.py",status="modified",sha="e"*40,
                    additions=1,deletions=0,patch="@@ -0 +1 @@\n+assert authored == 1")]
        if parts[4] == "contents":
            return self.python
        raise AssertionError(endpoint)

    def __call__(self, endpoint, headers):
        self.calls.append((endpoint,deepcopy(headers)))
        if self.conditional and endpoint in self.seen:
            assert headers.get("If-None-Match") == '"fixture-etag"'
            return 304,{"etag":'"fixture-etag"'},b""
        self.seen.add(endpoint)
        return 200,{"etag":'"fixture-etag"',"content-type":"application/json"},raw_json(self.payload(endpoint))


def test_frozen_quotas_round_robin_caps_and_source_bytes(tmp_path):
    api = FixtureAPI()
    client = GitHubRestClient(tmp_path/"cache",transport=api)
    repos = [f"authored/repo-{number}" for number in range(8)]
    batch = discover_batch(client,repos)
    assert batch["caps"]["metadata_received"] == 50
    assert batch["caps"]["detail_reservations"] == 10
    assert batch["caps"]["qualification_reservations"] == 4
    assert batch["detail_candidate_ids"][:8] == [candidate_identity(repo,1) for repo in repos]
    assert batch["qualification_candidate_ids"] == [candidate_identity(repo,1) for repo in repos[:4]]
    assert [len([c for c in batch["candidates"] if c["repository"]==repo]) for repo in repos] == [7,7,6,6,6,6,6,6]
    for candidate in batch["candidates"]:
        validate_candidate(candidate)
        assert candidate["stage"] in ("DISCOVERED","PROVENANCE_VERIFIED")
    qualified = [c for c in batch["candidates"] if c["provenance"]["qualification_reserved"]]
    assert all(c["buggy_revision"]==api.buggy for c in qualified)
    assert all(c["buggy_revision"]!=c["provenance"]["reported_base_sha"] for c in qualified)
    assert all(c["license"]["spdx_id"]=="MIT" for c in qualified)
    assert all(c["license"]["status"]=="ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW" for c in qualified)
    assert all(c["source_blobs"] and c["identity_support"]["raw_sources_verified"] for c in qualified)
    assert all(c["identity_support"]["independence_status"]=="NOT_ESTABLISHED" for c in qualified)
    assert all("external text must never execute" in c["source_blobs"][0]["text"] for c in qualified)


def test_rerun_uses_verified_304_bytes_and_skips_known_detail_work(tmp_path):
    api = FixtureAPI(count=2,conditional=True)
    client = GitHubRestClient(tmp_path/"cache",transport=api)
    first = discover_batch(client,["authored/one","authored/two"],max_candidates=4,max_details=2,max_qualifications=1)
    known = [c["candidate_id"] for c in first["candidates"]]
    second = discover_batch(client,["authored/one","authored/two"],max_candidates=4,max_details=2,
        max_qualifications=1,known_candidate_ids=known)
    assert second["caps"]["metadata_received"] == 4
    assert second["caps"]["detail_reservations"] == second["caps"]["qualification_reservations"] == 0
    assert len(second["api_ledger"])==4 and all(row["cache_hit"] for row in second["api_ledger"])
    assert [c["candidate_id"] for c in second["candidates"]] == known


@pytest.mark.parametrize("endpoint",["https://example.com/repos/a/b", "http://api.github.com/repos/a/b",
    "https://evil@api.github.com/repos/a/b", "/user", "/repos/a/b/actions/secrets", "/repos/a/b/contents/../secret"])
def test_unapproved_endpoints_fail_before_transport(tmp_path,endpoint):
    calls=[]
    client=GitHubRestClient(tmp_path,transport=lambda *args:calls.append(args))
    with pytest.raises(ValueError):
        client.get(endpoint)
    assert calls==[]


def test_cache_object_tamper_is_rejected_before_another_network_request(tmp_path):
    api=FixtureAPI()
    client=GitHubRestClient(tmp_path,transport=api)
    result=client.get("/repos/authored/one")
    (tmp_path/"objects"/(result["raw_sha256"]+".json")).write_bytes(b"tampered")
    with pytest.raises(GitHubAPIError,match="DIGEST"):
        client.get("/repos/authored/one")
    assert len(api.calls)==1


def test_rate_limit_stops_following_requests_without_sleep_or_credential_output(tmp_path):
    calls=[]
    def transport(endpoint,headers):
        calls.append(endpoint)
        return 429,{"retry-after":"3600","Authorization":"Bearer never-store-me","Set-Cookie":"private-cookie"},raw_json(dict(message="limited"))
    client=GitHubRestClient(tmp_path,transport=transport)
    with pytest.raises(GitHubAPIError,match="RATE_LIMIT"):
        client.get("/repos/authored/one")
    with pytest.raises(GitHubAPIError,match="WAIT_REQUIRED"):
        client.get("/repos/authored/two")
    assert len(calls)==1
    assert b"never-store-me" not in b"".join(p.read_bytes() for p in tmp_path.rglob("*.json"))
    assert "authorization" not in client.ledger[0]["headers"]


def test_error_response_is_retained_without_replacing_success_etag_cache(tmp_path):
    sequence=[(200,{"etag":'"good"'},raw_json(dict(ok=True))),
              (500,{"etag":'"bad"'},raw_json(dict(error=True))),
              (304,{},b"")]
    client=GitHubRestClient(tmp_path,transport=lambda *_:sequence.pop(0))
    client.get("/repos/authored/one")
    with pytest.raises(GitHubAPIError,match="500"):
        client.get("/repos/authored/one")
    result=client.get("/repos/authored/one")
    assert result["data"]==dict(ok=True)
    assert len(list((tmp_path/"objects").glob("*.json")))==2


def test_304_without_cache_and_oversized_response_fail_closed(tmp_path):
    client=GitHubRestClient(tmp_path/"first",transport=lambda *_:(304,{},b""))
    with pytest.raises(GitHubAPIError,match="UNCACHED"):
        client.get("/repos/authored/one")
    client=GitHubRestClient(tmp_path/"second",transport=lambda *_:(200,{},b"x"*(2*1024*1024+1)))
    with pytest.raises(GitHubAPIError,match="SIZE_LIMIT"):
        client.get("/repos/authored/one")


@pytest.mark.parametrize("link",[
    '<https://evil.example/search/issues?page=2>; rel="next"',
    '<https://api.github.com/repos/authored/two?page=2>; rel="next"',
    '<https://api.github.com/search/issues?q=changed&per_page=2&page=2>; rel="next"',
    '<https://api.github.com/search/issues?q=fixed&per_page=2&page=1>; rel="next"'])
def test_pagination_cannot_change_origin_route_query_or_rewind(link):
    with pytest.raises(ValueError):
        next_page(link,"/search/issues?q=fixed&per_page=2&page=1")
    assert next_page('<https://api.github.com/search/issues?q=fixed&per_page=2&page=2>; rel="next"',
        "/search/issues?q=fixed&per_page=2&page=1").endswith("page=2")


def test_private_repository_is_not_searched(tmp_path):
    calls=[]
    def transport(endpoint,headers):
        calls.append(endpoint)
        return 200,{},raw_json(dict(id=1,full_name="authored/private",private=True))
    batch=discover_batch(GitHubRestClient(tmp_path,transport=transport),["authored/private"])
    assert batch["candidates"]==[] and len(calls)==1
    assert batch["holds"]


def test_partial_failure_is_reserved_and_other_repository_remains_observable(tmp_path):
    api=FixtureAPI(count=1)
    def transport(endpoint,headers):
        if endpoint=="/repos/authored/missing":
            return 404,{},raw_json(dict(message="Not found"))
        return api(endpoint,headers)
    batch=discover_batch(GitHubRestClient(tmp_path,transport=transport),["authored/missing","authored/working"],
        max_candidates=2,max_details=1,max_qualifications=0)
    assert len(batch["candidates"])==1
    assert batch["caps"]["repositories_reserved"]==2
    assert any(row["status"]==404 for row in batch["api_ledger"])
    assert batch["caps"]["detail_reservations"]==1


def test_candidate_source_and_metadata_tamper_fail_even_after_outer_rehash(tmp_path):
    batch=discover_batch(GitHubRestClient(tmp_path,transport=FixtureAPI(count=1)),["authored/one"],
        max_candidates=1,max_details=1,max_qualifications=1)
    candidate=deepcopy(batch["candidates"][0])
    candidate["source_blobs"][0]["text"]+="\n# altered"
    candidate["metadata_digest"]=digest({k:v for k,v in candidate.items() if k!="metadata_digest"})
    with pytest.raises(ValueError,match="digest"):
        validate_candidate(candidate)


def test_malformed_search_item_is_hold_with_received_denominator_retained(tmp_path):
    api=FixtureAPI(count=1)
    def transport(endpoint,headers):
        if endpoint.startswith("/search/"):
            return 200,{},raw_json(dict(incomplete_results=False,items=[None]))
        return api(endpoint,headers)
    batch=discover_batch(GitHubRestClient(tmp_path,transport=transport),["authored/one"],max_candidates=1)
    assert batch["caps"]["metadata_received"]==1
    assert batch["candidates"]==[] and batch["holds"]
