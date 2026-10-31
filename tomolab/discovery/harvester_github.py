"""Bounded, read-only GitHub discovery. Retrieved text is data, never code.

The local cache contains raw public API bytes and is not a publication surface.
No credential is read into Python; the production transport reuses gh auth.
"""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import threading
import time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
import uuid

from .schema import canonical, digest

API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_LICENSE_BYTES = 64 * 1024
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SAFE_HEADERS = {"etag", "last-modified", "link", "retry-after", "x-ratelimit-limit",
    "x-ratelimit-remaining", "x-ratelimit-reset", "x-ratelimit-resource", "content-type"}


class GitHubAPIError(ValueError):
    """A bounded request failed. The ledger, not exception text, holds evidence."""
    def __init__(self, reason, *, status=None):
        super().__init__(reason)
        self.reason, self.status = reason, status


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reason(error):
    return error.reason if isinstance(error, GitHubAPIError) else (type(error).__name__ + ":" + str(error))[:200]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate API JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite API JSON")))


def _repository(value):
    if type(value) is not str or not REPO.fullmatch(value) or len(value) > 200:
        raise ValueError("reviewed owner/repository name required")
    return value.lower()


def _path(value):
    if (type(value) is not str or not value or len(value) > 1024 or "\\" in value
            or any(ord(c) < 32 for c in value) or PurePosixPath(value).is_absolute()
            or ".." in PurePosixPath(value).parts):
        raise ValueError("bounded relative source path required")
    return value


def _endpoint(value):
    """Only reviewed official GET endpoints; never follow a README URL."""
    if type(value) is not str or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("bounded GitHub REST endpoint required")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("GitHub API origin required")
    elif not value.startswith("/"):
        raise ValueError("absolute API path required")
    if parsed.fragment or parsed.username or parsed.password:
        raise ValueError("credentials and fragments are forbidden in endpoint URLs")
    path = parsed.path
    if "%2e" in path.lower() or ".." in path.split("/") or "\\" in path:
        raise ValueError("unsafe API path")
    patterns = (r"/search/issues", r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls/[1-9][0-9]*(?:/files)?",
        r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commits/[a-f0-9]{40}",
        r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/license",
        r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/contents/.+")
    if not any(re.fullmatch(pattern, path) for pattern in patterns):
        raise ValueError("endpoint is outside reviewed discovery GET scope")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if len(pairs) != len({key for key, _ in pairs}):
        raise ValueError("duplicate query parameters")
    allowed = {"q", "sort", "order", "per_page", "page"} if path == "/search/issues" else {"ref", "per_page", "page"}
    if any(key not in allowed for key, _ in pairs):
        raise ValueError("unreviewed endpoint query parameter")
    for key, value in pairs:
        if key in ("page", "per_page") and (not value.isdigit() or not 1 <= int(value) <= 100):
            raise ValueError("bounded page parameter required")
        if key == "ref" and not SHA1.fullmatch(value):
            raise ValueError("immutable commit ref required")
    return path + ("?" + parsed.query if parsed.query else "")


def next_page(link, endpoint):
    """Return only the official same-route rel=next URL, with no origin change."""
    if not link:
        return None
    if type(link) is not str or len(link) > 8192 or any(ord(c) < 32 for c in link):
        raise ValueError("bounded Link header required")
    matches = []
    for component in link.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"\s*', component)
        if match is None:
            raise ValueError("malformed pagination Link header")
        matches.append(match.groups())
    values = [url for url, rel in matches if rel == "next"]
    if len(values) > 1:
        raise ValueError("ambiguous next page")
    if not values:
        return None
    following = _endpoint(values[0])
    before, after = urlsplit(_endpoint(endpoint)), urlsplit(following)
    if before.path != after.path:
        raise ValueError("pagination cannot change the approved endpoint route")
    before_query = dict(parse_qsl(before.query))
    after_query = dict(parse_qsl(after.query))
    if {k:v for k,v in before_query.items() if k != "page"} != {k:v for k,v in after_query.items() if k != "page"}:
        raise ValueError("pagination cannot change search, ref or page size")
    if int(after_query.get("page", "1")) <= int(before_query.get("page", "1")):
        raise ValueError("pagination must advance")
    return following


def _gh_transport(endpoint, headers):
    args = ["gh", "api", "--include", "--method", "GET", endpoint]
    for name, value in headers.items():
        args.extend(["-H", name + ": " + value])
    try:
        result = subprocess.run(args, capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitHubAPIError("GITHUB_TRANSPORT_" + type(error).__name__) from None
    raw = result.stdout
    match = re.match(rb"HTTP/[^\s]+\s+([0-9]{3})[^\r\n]*\r?\n", raw)
    if match is None:
        # gh stderr can contain local paths or auth diagnostics; do not print it.
        raise GitHubAPIError("GITHUB_TRANSPORT_NO_HTTP_RESPONSE")
    split = re.search(rb"\r?\n\r?\n", raw)
    if split is None:
        raise GitHubAPIError("GITHUB_TRANSPORT_TRUNCATED_HEADERS")
    response_headers = {}
    for line in raw[match.end():split.start()].splitlines():
        if b":" in line:
            key, value = line.split(b":", 1)
            response_headers[key.decode("ascii", errors="strict").lower()] = value.decode("latin-1").strip()
    return int(match.group(1)), response_headers, raw[split.end():]


class GitHubRestClient:
    """One serial request queue with content-addressed raw bytes and ETag cache."""
    def __init__(self, cache_root, *, transport=None):
        self.cache_root = Path(cache_root)
        if self.cache_root.is_symlink():
            raise ValueError("cache root must not be a symbolic link")
        self.objects = self.cache_root / "objects"
        self.index = self.cache_root / "index"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.index.mkdir(parents=True, exist_ok=True)
        self.transport = transport or _gh_transport
        self.ledger = []
        self._lock = threading.Lock()
        self._blocked_until = 0.0

    def _cached(self, endpoint):
        key = digest(dict(endpoint=endpoint, api_version=API_VERSION, media_type="application/vnd.github+json"))
        path = self.index / (key + ".json")
        if not path.exists():
            return key, None
        if path.is_symlink() or path.stat().st_size > 32 * 1024:
            raise GitHubAPIError("CACHE_INDEX_NOT_BOUNDED_REGULAR_FILE")
        index_bytes = path.read_bytes()
        row = _json(index_bytes)
        fields = {"schema", "request_key", "endpoint", "api_version", "raw_sha256", "headers", "stored_at", "sha256"}
        if (type(row) is not dict or set(row) != fields or row["schema"] != "tomolab-github-cache-v1"
                or row["request_key"] != key or row["endpoint"] != endpoint or row["api_version"] != API_VERSION
                or not SHA256.fullmatch(str(row["raw_sha256"]))
                or row["sha256"] != digest({k:v for k,v in row.items() if k != "sha256"})
                or index_bytes != (canonical(row) + "\n").encode("utf-8")
                or type(row["headers"]) is not dict or set(row["headers"]) - SAFE_HEADERS):
            raise GitHubAPIError("CACHE_INDEX_IDENTITY_MISMATCH")
        blob = self.objects / (row["raw_sha256"] + ".json")
        if not blob.is_file() or blob.is_symlink() or blob.stat().st_size > MAX_RESPONSE_BYTES:
            raise GitHubAPIError("CACHE_OBJECT_MISSING_OR_OVERSIZED")
        raw = blob.read_bytes()
        if _sha(raw) != row["raw_sha256"]:
            raise GitHubAPIError("CACHE_OBJECT_DIGEST_MISMATCH")
        row["raw"] = raw
        return key, row

    def _save(self, key, endpoint, headers, raw, *, update_index=True):
        raw_sha = _sha(raw)
        blob = self.objects / (raw_sha + ".json")
        try:
            with blob.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            if blob.is_symlink() or blob.read_bytes() != raw:
                raise GitHubAPIError("CACHE_OBJECT_CONFLICT") from None
        if not update_index:
            return raw_sha
        row = dict(schema="tomolab-github-cache-v1", request_key=key, endpoint=endpoint,
            api_version=API_VERSION, raw_sha256=raw_sha, headers=headers, stored_at=_now())
        row["sha256"] = digest(row)
        temporary = self.index / (key + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical(row) + "\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, self.index / (key + ".json"))
        return raw_sha

    def get(self, endpoint):
        endpoint = _endpoint(endpoint)
        with self._lock:
            started = time.perf_counter()
            if time.time() < self._blocked_until:
                raise GitHubAPIError("HOLD_RATE_LIMIT_WAIT_REQUIRED")
            key, cached = self._cached(endpoint)
            request_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
            if cached is not None and "etag" in cached["headers"]:
                etag = cached["headers"]["etag"]
                if type(etag) is not str or len(etag) > 1024 or any(ord(c) < 32 for c in etag):
                    raise GitHubAPIError("CACHE_ETAG_INVALID")
                request_headers["If-None-Match"] = etag
            entry = dict(endpoint=endpoint, requested_at=_now(), status=None, cache_hit=False,
                raw_sha256=None, response_bytes=0, wall_seconds=0.0, headers={}, error=None)
            self.ledger.append(entry)
            try:
                status, incoming, raw = self.transport(endpoint, request_headers)
                if type(status) is not int or type(incoming) is not dict or type(raw) is not bytes:
                    raise GitHubAPIError("INVALID_HTTP_TRANSPORT_SHAPE")
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise GitHubAPIError("HOLD_RESPONSE_SIZE_LIMIT", status=status)
                headers = {}
                for name, value in incoming.items():
                    if type(name) is not str or type(value) is not str or len(value) > 8192 or any(ord(c) < 32 for c in value):
                        raise GitHubAPIError("INVALID_HTTP_HEADER", status=status)
                    name = name.lower()
                    if name in SAFE_HEADERS:
                        headers[name] = value
                entry.update(status=status, response_bytes=len(raw), headers=headers)
                if status == 304:
                    if cached is None or raw:
                        raise GitHubAPIError("UNCACHED_OR_NONEMPTY_304", status=status)
                    raw = cached["raw"]
                    raw_sha = cached["raw_sha256"]
                    headers = {**cached["headers"], **headers}
                    entry["cache_hit"] = True
                else:
                    raw_sha = self._save(key, endpoint, headers, raw, update_index=False)
                entry["raw_sha256"] = raw_sha
                if status in (403, 429):
                    delay = headers.get("retry-after", "")
                    reset = headers.get("x-ratelimit-reset", "")
                    if delay.isdigit():
                        self._blocked_until = time.time() + int(delay)
                    elif headers.get("x-ratelimit-remaining") == "0" and reset.isdigit():
                        self._blocked_until = max(time.time() + 1, int(reset))
                    else:
                        self._blocked_until = time.time() + 60
                    raise GitHubAPIError("HOLD_RATE_LIMIT_OR_FORBIDDEN", status=status)
                if status not in (200, 304):
                    raise GitHubAPIError("GITHUB_HTTP_" + str(status), status=status)
                data = _json(raw)
                if status == 200:
                    self._save(key, endpoint, headers, raw, update_index=True)
                if headers.get("x-ratelimit-remaining") == "0":
                    reset = headers.get("x-ratelimit-reset", "")
                    self._blocked_until = int(reset) if reset.isdigit() else time.time() + 60
                return dict(data=data, status=status, headers=headers, raw_sha256=raw_sha,
                    endpoint=endpoint, cache_hit=entry["cache_hit"])
            except (GitHubAPIError, ValueError, UnicodeError, RecursionError) as error:
                entry["error"] = error.reason if isinstance(error, GitHubAPIError) else type(error).__name__
                if isinstance(error, RecursionError):
                    raise GitHubAPIError("HOLD_JSON_NESTING_LIMIT") from None
                raise
            finally:
                entry["wall_seconds"] = time.perf_counter() - started


def candidate_identity(repository, number):
    repository = _repository(repository)
    if type(number) is not int or number < 1 or number > 10**9:
        raise ValueError("positive PR number required")
    return digest(dict(repository=repository, pull_number=number))


def _object(response):
    return dict(endpoint=response["endpoint"], raw_sha256=response["raw_sha256"], status=response["status"])


def validate_candidate(candidate):
    """Strict data integrity only; this confers no contract/Oracle authority."""
    fields = {"candidate_id", "repository", "source_url", "number", "title", "discovered_at", "stage",
        "issues", "buggy_revision", "fixed_revision", "provenance", "license", "changed_files",
        "test_evidence", "source_blobs", "identity_support", "unknown_reasons", "metadata_digest"}
    if type(candidate) is not dict or set(candidate) != fields or len(canonical(candidate).encode()) > 3 * 1024 * 1024:
        raise ValueError("bounded exact candidate fields required")
    c = candidate
    repo = _repository(c["repository"])
    if (repo != c["repository"] or c["candidate_id"] != candidate_identity(repo, c["number"])
            or c["source_url"].lower() != f"https://github.com/{repo}/pull/{c['number']}"
            or type(c["title"]) is not str or len(c["title"]) > 1024
            or type(c["discovered_at"]) is not str or len(c["discovered_at"]) > 64
            or c["stage"] not in ("DISCOVERED", "PROVENANCE_VERIFIED")):
        raise ValueError("candidate identity or stage mismatch")
    for name in ("buggy_revision", "fixed_revision"):
        if c[name] is not None and (type(c[name]) is not str or not SHA1.fullmatch(c[name])):
            raise ValueError("immutable revision identity required")
    if type(c["issues"]) is not list or len(c["issues"]) > 20 or any(type(url) is not str or not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*", url) for url in c["issues"]):
        raise ValueError("bounded public issue provenance required")
    p = c["provenance"]
    if type(p) is not dict or set(p) != {"public_repository", "repository_id", "merged", "merge_commit_sha",
            "proposed_buggy_first_parent", "proposed_buggy_parent_sha", "reported_base_sha", "reported_head_sha",
            "detail_reserved", "qualification_reserved", "api_objects"}:
        raise ValueError("exact provenance fields required")
    if any(type(p[name]) is not bool for name in ("public_repository", "merged", "proposed_buggy_first_parent",
            "detail_reserved", "qualification_reserved")) or p["public_repository"] is not True or type(p["repository_id"]) is not int:
        raise ValueError("public repository and explicit reservation flags required")
    for name in ("merge_commit_sha", "proposed_buggy_parent_sha", "reported_base_sha", "reported_head_sha"):
        if p[name] is not None and (type(p[name]) is not str or not SHA1.fullmatch(p[name])):
            raise ValueError("provenance revision must be an immutable commit")
    if c["stage"] == "PROVENANCE_VERIFIED" and not (p["merged"] is True and p["detail_reserved"] is True
            and p["proposed_buggy_first_parent"] is True and p["proposed_buggy_parent_sha"] == c["buggy_revision"]
            and p["merge_commit_sha"] == c["fixed_revision"]):
        raise ValueError("verified provenance does not bind the actual commit parent")
    if type(p["api_objects"]) is not list or len(p["api_objects"]) > 20:
        raise ValueError("bounded original API object references required")
    for row in p["api_objects"]:
        if type(row) is not dict or set(row) != {"endpoint", "raw_sha256", "status"} or row["status"] not in (200,304):
            raise ValueError("API object reference mismatch")
        _endpoint(row["endpoint"])
        if type(row["raw_sha256"]) is not str or not SHA256.fullmatch(row["raw_sha256"]):
            raise ValueError("API object digest required")
    license = c["license"]
    if type(license) is not dict or set(license) != {"spdx_id", "status", "path", "revision", "git_blob_sha", "sha256", "text"}:
        raise ValueError("exact license fields required")
    if license["spdx_id"] is not None and (type(license["spdx_id"]) is not str or len(license["spdx_id"]) > 100):
        raise ValueError("bounded SPDX metadata required")
    if license["status"] not in ("NOT_REVIEWED", "ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW"):
        raise ValueError("license metadata does not confer legal review")
    if license["status"] == "ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW":
        _path(license["path"])
        _validate_source_blob({key:license[key] for key in ("path", "revision", "git_blob_sha", "sha256", "text")}, maximum=MAX_LICENSE_BYTES)
        if license["revision"] != c["fixed_revision"]:
            raise ValueError("license must bind the fixed revision")
    elif any(license[name] is not None for name in ("path", "revision", "git_blob_sha", "sha256", "text")):
        raise ValueError("unverified license cannot carry verified byte claims")
    if type(c["changed_files"]) is not list or len(c["changed_files"]) > 50:
        raise ValueError("bounded changed file metadata required")
    for row in c["changed_files"]:
        if type(row) is not dict or set(row) != {"path", "previous_path", "status", "sha", "additions", "deletions", "patch_present", "patch_sha256"}:
            raise ValueError("exact changed file fields required")
        _path(row["path"])
        if row["previous_path"] is not None:
            _path(row["previous_path"])
        if (row["status"] not in ("added", "removed", "modified", "renamed", "copied", "changed", "unchanged")
                or type(row["sha"]) is not str or not SHA1.fullmatch(row["sha"])
                or any(type(row[name]) is not int or row[name] < 0 for name in ("additions", "deletions"))
                or type(row["patch_present"]) is not bool):
            raise ValueError("changed file metadata types differ")
        if row["patch_present"] != (type(row["patch_sha256"]) is str and SHA256.fullmatch(row["patch_sha256"]) is not None):
            raise ValueError("patch availability and digest disagree")
    test = c["test_evidence"]
    if type(test) is not dict or set(test) != {"paths", "patches"} or type(test["paths"]) is not list or len(test["paths"]) > 50 or type(test["patches"]) is not list or len(test["patches"]) > 4:
        raise ValueError("bounded test evidence required")
    for path in test["paths"]:
        _path(path)
    for patch in test["patches"]:
        if type(patch) is not dict or set(patch) != {"path", "sha256", "text"} or patch["path"] not in test["paths"] or type(patch["text"]) is not str or len(patch["text"].encode()) > MAX_SOURCE_BYTES or patch["sha256"] != _sha(patch["text"].encode()):
            raise ValueError("original test patch digest mismatch")
    if type(c["source_blobs"]) is not list or len(c["source_blobs"]) > 4:
        raise ValueError("bounded original source blobs required")
    for source in c["source_blobs"]:
        _validate_source_blob(source, maximum=MAX_SOURCE_BYTES)
        if source["revision"] not in (c["buggy_revision"], c["fixed_revision"]):
            raise ValueError("source revision is outside the proposed pair")
    support = c["identity_support"]
    if type(support) is not dict or set(support) != {"source_files_inspected", "python_source_available", "raw_sources_verified", "consumption_status", "independence_status"}:
        raise ValueError("exact identity review state required")
    if (type(support["source_files_inspected"]) is not int or not 0 <= support["source_files_inspected"] <= 2
            or type(support["python_source_available"]) is not bool or type(support["raw_sources_verified"]) is not bool
            or support["consumption_status"] != "NOT_REVIEWED" or support["independence_status"] != "NOT_ESTABLISHED"):
        raise ValueError("discovery cannot self-certify consumption or independence")
    reasons = c["unknown_reasons"]
    if type(reasons) is not list or len(reasons) > 100 or any(type(reason) is not str or not 1 <= len(reason) <= 250 for reason in reasons):
        raise ValueError("bounded unknown reasons required")
    if c["metadata_digest"] != digest({key:value for key,value in c.items() if key != "metadata_digest"}):
        raise ValueError("candidate metadata digest mismatch")
    return deepcopy(c)


def _validate_source_blob(source, *, maximum):
    if type(source) is not dict or set(source) != {"path", "revision", "git_blob_sha", "sha256", "text"}:
        raise ValueError("exact immutable source blob fields required")
    _path(source["path"])
    if (type(source["revision"]) is not str or not SHA1.fullmatch(source["revision"])
            or type(source["text"]) is not str or len(source["text"].encode()) > maximum):
        raise ValueError("bounded source revision and UTF8 text required")
    raw = source["text"].encode("utf-8")
    if (source["sha256"] != _sha(raw) or source["git_blob_sha"] != hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()):
        raise ValueError("source original bytes and digest differ")


def _new_candidate(repository, item, repo, search_response):
    if type(item) is not dict:
        raise ValueError("PR search metadata object required")
    number = item.get("number")
    candidate_id = candidate_identity(repository, number)
    url = item.get("html_url")
    expected = "https://github.com/" + repository + "/pull/" + str(number)
    if type(url) is not str or url.lower() != expected:
        raise ValueError("search candidate repository identity mismatch")
    title = item.get("title")
    if type(title) is not str or len(title) > 1024 or "pull_request" not in item:
        raise ValueError("bounded PR metadata required")
    repo_license = repo.get("license")
    if repo_license is not None and type(repo_license) is not dict:
        raise ValueError("repository license metadata object required")
    row = dict(candidate_id=candidate_id, repository=repository, source_url=url,
        number=number, title=title, discovered_at=_now(), stage="DISCOVERED", issues=[],
        buggy_revision=None, fixed_revision=None,
        provenance=dict(public_repository=True, repository_id=repo["id"], merged=False,
            merge_commit_sha=None, proposed_buggy_first_parent=False, proposed_buggy_parent_sha=None, reported_base_sha=None,
            reported_head_sha=None, detail_reserved=False, qualification_reserved=False,
            api_objects=[_object(search_response)]),
        license=dict(spdx_id=(repo_license or {}).get("spdx_id"), status="NOT_REVIEWED",
            path=None, revision=None, git_blob_sha=None, sha256=None, text=None),
        changed_files=[], test_evidence=dict(paths=[], patches=[]), source_blobs=[],
        identity_support=dict(source_files_inspected=0, python_source_available=False,
            raw_sources_verified=False, consumption_status="NOT_REVIEWED", independence_status="NOT_ESTABLISHED"),
        unknown_reasons=["CONTRACT_ORACLE_RESET_AND_INDEPENDENCE_NOT_REVIEWED"])
    return row


def _blob(data, *, maximum):
    if (type(data) is not dict or data.get("encoding") != "base64" or type(data.get("content")) is not str
            or not SHA1.fullmatch(str(data.get("sha"))) or type(data.get("size")) is not int
            or not 0 <= data["size"] <= maximum):
        raise ValueError("bounded file bytes and Git blob identity required")
    raw = base64.b64decode("".join(data["content"].split()), validate=True)
    if len(raw) != data["size"] or len(raw) > maximum:
        raise ValueError("source file byte count mismatch")
    git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if git_sha != data["sha"]:
        raise ValueError("Git blob SHA1 does not match original source bytes")
    return raw, raw.decode("utf-8"), git_sha


def _details(client, row, *, qualification):
    repo, number = row["repository"], row["number"]
    row["provenance"].update(detail_reserved=True, qualification_reserved=qualification)
    def request(path):
        response = client.get(path)
        row["provenance"]["api_objects"].append(_object(response))
        return response
    detail = request(f"/repos/{repo}/pulls/{number}")["data"]
    if (type(detail) is not dict or detail.get("number") != number or type(detail.get("base")) is not dict
            or type(detail["base"].get("repo")) is not dict
            or type(detail["base"]["repo"].get("full_name")) is not str
            or detail["base"]["repo"]["full_name"].lower() != repo or type(detail.get("head")) is not dict):
        raise ValueError("PR detail identity mismatch")
    merged, fixed = detail.get("merged"), detail.get("merge_commit_sha")
    fixed = fixed if type(fixed) is str and SHA1.fullmatch(fixed) else None
    base_sha, head_sha = detail["base"].get("sha"), detail["head"].get("sha")
    base_sha = base_sha if type(base_sha) is str and SHA1.fullmatch(base_sha) else None
    head_sha = head_sha if type(head_sha) is str and SHA1.fullmatch(head_sha) else None
    row["provenance"].update(merged=merged is True, merge_commit_sha=fixed,
        reported_base_sha=base_sha, reported_head_sha=head_sha)
    body = detail.get("body") or ""
    if type(body) is not str or len(body.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("bounded PR text required")
    row["issues"] = sorted(set(re.findall(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+", body)))[:20]
    if merged is not True or type(fixed) is not str or not SHA1.fullmatch(fixed):
        row["unknown_reasons"].append("PR_MERGE_NOT_VERIFIED")
        return
    commit = request(f"/repos/{repo}/commits/{fixed}")["data"]
    if type(commit) is not dict:
        raise ValueError("fix commit metadata object required")
    parents = commit.get("parents")
    if (commit.get("sha") != fixed or type(parents) is not list or not parents
            or type(parents[0]) is not dict or not SHA1.fullmatch(str(parents[0].get("sha")))):
        row["unknown_reasons"].append("FIX_COMMIT_PARENT_NOT_VERIFIED")
        return
    row["fixed_revision"], row["buggy_revision"] = fixed, parents[0]["sha"]
    row["provenance"]["proposed_buggy_first_parent"] = True
    row["provenance"]["proposed_buggy_parent_sha"] = parents[0]["sha"]
    files_endpoint = f"/repos/{repo}/pulls/{number}/files?per_page=50&page=1"
    files_response = request(files_endpoint)
    files = files_response["data"]
    if type(files) is not list or len(files) > 50:
        raise ValueError("bounded PR file list required")
    if next_page(files_response["headers"].get("link"), files_endpoint) is not None:
        row["unknown_reasons"].append("CHANGED_FILE_PAGE_TRUNCATED_AT_50")
    for item in files:
        if type(item) is not dict:
            raise ValueError("file metadata object required")
        path = _path(item.get("filename"))
        previous = _path(item["previous_filename"]) if item.get("previous_filename") else None
        patch = item.get("patch")
        if patch is not None and (type(patch) is not str or len(patch.encode("utf-8")) > MAX_SOURCE_BYTES):
            row["unknown_reasons"].append("PATCH_MISSING_OR_OVERSIZED")
            patch = None
        if patch is None:
            row["unknown_reasons"].append("PATCH_MISSING_OR_OVERSIZED")
        if (item.get("status") not in ("added", "removed", "modified", "renamed", "copied", "changed", "unchanged")
                or not SHA1.fullmatch(str(item.get("sha")))
                or any(type(item.get(key)) is not int or item[key] < 0 for key in ("additions", "deletions"))):
            raise ValueError("changed file metadata types differ")
        row["changed_files"].append(dict(path=path, previous_path=previous, status=item.get("status"),
            sha=item.get("sha"), additions=item.get("additions"), deletions=item.get("deletions"),
            patch_present=patch is not None, patch_sha256=_sha(patch.encode()) if patch is not None else None))
        if ("test" in PurePosixPath(path).parts or PurePosixPath(path).name.startswith("test_")
                or "/tests/" in "/" + path):
            row["test_evidence"]["paths"].append(path)
            if patch is not None and len(row["test_evidence"]["patches"]) < 4:
                row["test_evidence"]["patches"].append(dict(path=path, sha256=_sha(patch.encode()), text=patch))
    row["stage"] = "PROVENANCE_VERIFIED"
    if not row["test_evidence"]["paths"]:
        row["unknown_reasons"].append("REGRESSION_TEST_EVIDENCE_NOT_IDENTIFIED")
    if not qualification:
        row["unknown_reasons"].append("QUALIFICATION_BUDGET_NOT_RESERVED")
        return
    try:
        license_response = request(f"/repos/{repo}/license?ref={fixed}")
        raw, text, blob_sha = _blob(license_response["data"], maximum=MAX_LICENSE_BYTES)
        license_data = license_response["data"]
        fixed_license = license_data.get("license")
        fixed_spdx = fixed_license.get("spdx_id") if type(fixed_license) is dict else None
        fixed_spdx = fixed_spdx if type(fixed_spdx) is str and len(fixed_spdx) <= 100 else None
        license_path = _path(license_data.get("path"))
        row["license"].update(status="ORIGINAL_BYTES_VERIFIED_NOT_LEGAL_REVIEW", path=license_path,
            revision=fixed, git_blob_sha=blob_sha, sha256=_sha(raw), text=text, spdx_id=fixed_spdx)
    except (GitHubAPIError, ValueError, UnicodeError):
        row["unknown_reasons"].append("FIXED_REVISION_LICENSE_NOT_VERIFIED")
    python_files = sorted([item for item in row["changed_files"]
        if item["path"].endswith(".py") and item["path"] not in row["test_evidence"]["paths"]], key=lambda item:item["path"])[:2]
    for item in python_files:
        for role, revision, path in (("buggy", row["buggy_revision"], item["previous_path"] or item["path"]),
                                      ("fixed", fixed, item["path"])):
            try:
                response = request(f"/repos/{repo}/contents/{quote(path, safe='/')}?ref={revision}")
                raw, text, blob_sha = _blob(response["data"], maximum=MAX_SOURCE_BYTES)
                if role == "fixed" and item["sha"] != blob_sha:
                    raise ValueError("fixed PR file and source blob identity differ")
                row["source_blobs"].append(dict(path=path, revision=revision, git_blob_sha=blob_sha,
                    sha256=_sha(raw), text=text))
            except (GitHubAPIError, ValueError, UnicodeError):
                row["unknown_reasons"].append("SOURCE_BLOB_" + role.upper() + "_NOT_VERIFIED")
    row["identity_support"].update(source_files_inspected=len(python_files), python_source_available=bool(row["source_blobs"]),
        raw_sources_verified=bool(python_files) and len(row["source_blobs"]) == 2 * len(python_files))
    if not row["source_blobs"]:
        row["unknown_reasons"].append("SUPPORTED_PYTHON_SOURCE_NOT_IDENTIFIED")


def discover_batch(client, repositories, *, max_candidates=50, max_details=10,
                   max_qualifications=4, known_candidate_ids=()):
    """Discover once, then reserve details round-robin before any detail result.

    Limits are engineering caps, not evidence of statistical power. No target,
    Oracle, dependency installer or external source is executed by this module.
    """
    if not isinstance(client, GitHubRestClient):
        raise TypeError("reviewed GitHub REST client required")
    if (type(repositories) not in (list, tuple) or not 1 <= len(repositories) <= 8
            or any(type(value) is not int for value in (max_candidates, max_details, max_qualifications))
            or not 0 <= max_candidates <= 50 or not 0 <= max_details <= 10 or not 0 <= max_qualifications <= 4):
        raise ValueError("discovery caps are 50 metadata, 10 details, 4 qualifications and 8 repositories")
    repositories = [_repository(repo) for repo in repositories]
    if len(set(repositories)) != len(repositories):
        raise ValueError("duplicate repository in frozen discovery scope")
    known = set(known_candidate_ids)
    if any(type(value) is not str or not SHA256.fullmatch(value) for value in known):
        raise ValueError("known candidate IDs must be SHA256 identities")
    ledger_start = len(client.ledger)
    candidates, groups, holds = [], [], []
    received, duplicate_rows = 0, 0
    quota_violation = False
    observed = set()
    for index, repository in enumerate(repositories):
        quota = max_candidates // len(repositories) + int(index < max_candidates % len(repositories))
        group = []
        groups.append(group)
        if quota == 0:
            continue
        try:
            repo_response = client.get("/repos/" + repository)
            repo = repo_response["data"]
            if (type(repo) is not dict or repo.get("private") is not False
                    or str(repo.get("full_name", "")).lower() != repository or type(repo.get("id")) is not int):
                raise ValueError("PUBLIC_REPOSITORY_IDENTITY_NOT_VERIFIED")
            query = f"repo:{repository} is:pr is:merged fix in:title"
            endpoint = "/search/issues?" + urlencode(dict(q=query, sort="created", order="desc", per_page=quota, page=1))
            response = client.get(endpoint)
            data = response["data"]
            if type(data) is not dict or type(data.get("items")) is not list:
                raise ValueError("SEARCH_METADATA_SHAPE_INVALID")
            received += len(data["items"])
            if len(data["items"]) > quota:
                quota_violation = True
                raise ValueError("SEARCH_EXCEEDS_RESERVED_METADATA_QUOTA")
            if data.get("incomplete_results") is not False:
                holds.append(dict(repository=repository, reason="SEARCH_INCOMPLETE_OR_UNDECLARED"))
            if next_page(response["headers"].get("link"), endpoint) is not None:
                holds.append(dict(repository=repository, reason="SEARCH_STOPPED_AT_FROZEN_REPOSITORY_QUOTA"))
            for item in data["items"]:
                row = _new_candidate(repository, item, repo, response)
                if row["candidate_id"] in observed:
                    duplicate_rows += 1
                    continue
                observed.add(row["candidate_id"])
                if row["candidate_id"] in known:
                    row["unknown_reasons"].append("ALREADY_REGISTERED_DETAIL_NOT_REPEATED")
                else:
                    group.append(row)
                candidates.append(row)
        except (GitHubAPIError, ValueError, UnicodeError) as error:
            holds.append(dict(repository=repository, reason=_reason(error)))
            if quota_violation:
                break
    # Freeze detail and qualification reservations using metadata only.
    ordered = []
    for position in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if position < len(group):
                ordered.append(group[position])
    detailed = ordered[:max_details]
    qualification_ids = [row["candidate_id"] for row in detailed[:max_qualifications]]
    qualifications = set(qualification_ids)
    for row in detailed:
        row["provenance"].update(detail_reserved=True,
            qualification_reserved=row["candidate_id"] in qualifications)
        try:
            _details(client, row, qualification=row["candidate_id"] in qualifications)
        except (GitHubAPIError, ValueError, UnicodeError) as error:
            row["unknown_reasons"].append(_reason(error))
            holds.append(dict(candidate_id=row["candidate_id"], repository=row["repository"],
                reason="DETAIL_INCOMPLETE_RETAIN_PARTIAL_PROVENANCE"))
    for row in candidates:
        row["unknown_reasons"] = sorted(set(row["unknown_reasons"]))
        row["metadata_digest"] = digest(row)
    return dict(schema="tomolab-harvester-discovery-batch-v1", candidates=deepcopy(candidates),
        api_ledger=deepcopy(client.ledger[ledger_start:]), holds=holds,
        qualification_candidate_ids=qualification_ids,
        detail_candidate_ids=[row["candidate_id"] for row in detailed],
        caps=dict(max_candidates=max_candidates, max_details=max_details,
            max_qualifications=max_qualifications, max_repositories=8,
            metadata_received=received, unique_candidates=len(candidates), duplicate_metadata_rows=duplicate_rows,
            detail_reservations=len(detailed), qualification_reservations=len(qualifications),
            repositories_reserved=len(repositories), network_requests=len(client.ledger)-ledger_start),
        query_contract=dict(version="bounded-public-merged-pr-fix-v1", repository_order=repositories,
            search="is:pr is:merged fix in:title", order="created_desc",
            selection="FROZEN_REPOSITORY_QUOTAS_THEN_METADATA_ONLY_ROUND_ROBIN",
            success_meaning="CANDIDATE_DISCOVERY_NOT_DEFECT_OR_ORACLE_VALIDATION"))
