"""Authored supply-chain fixture, never a real GitHub or research result.

The HTTP transport returns fictional public-API-shaped data. The only host
callables accepted by the separate fixture authority are the exact previously
reviewed recursive_demo functions. Harvested source text is never imported.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

from . import recursive_demo
from .discovery.harvester_github import GitHubRestClient, candidate_identity, validate_candidate
from .discovery.harvester_learning import _append_update
from .discovery.harvester_registry import HarvestRegistry
from .discovery.harvester_service import run_harvest, save_new
from .discovery.recursive_api import create_generation
from .discovery.recursive_policy import make_development_manifest
from .discovery.recursive_store import GenerationStore
from .discovery.schema import canonical, digest

EVIDENCE_CLASS = "AUTHORED_SYNTHETIC_FIXTURE"
REPOSITORIES = ("authored/gain-fixtures", "authored/loss-fixtures")
FUNCTION_SHA256 = {
    "gain_a": "5368b007ef549745b31f18f589f95461906bd1845f312dfd77a8ab7c8792f767",
    "gain_b": "9dfcacf3e5776f6519efc15dd30eb47bf382c76aca4a725f28521036ebcbc93e",
    "loss_a": "29a69048351123d926bba1818523bc1fd1df565348f0b5a59408ed6664dc61e0",
    "loss_b": "be971f7452862a4c5ebfd49dc75a8cc2e85fe7942561edc6ec27cf283e11c64a",
    "reference": "26c79bde1ab73f5af73b06b0e38596e6e30e409ca9c0b074ceebc3493229d5bf",
    "reset_fixture": "d9b4e0af30179f95d51329a94c2bb21e62ff9f86b158536255ba33d618970245",
}
FUNCTIONS = {
    (REPOSITORIES[0], 1): recursive_demo.gain_a,
    (REPOSITORIES[0], 2): recursive_demo.gain_b,
    (REPOSITORIES[1], 1): recursive_demo.loss_a,
    (REPOSITORIES[1], 2): recursive_demo.loss_b,
}
LICENSE_TEXT = "MIT authored test fixture; fictional project, no external repository source.\n"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _source(fn):
    return inspect.getsource(fn)


def _blob_sha(text):
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _file_response(text, path, *, license_id=None):
    import base64
    raw = text.encode("utf-8")
    value = dict(encoding="base64", content=base64.b64encode(raw).decode("ascii"),
        size=len(raw), sha=_blob_sha(text), path=path)
    if license_id is not None:
        value["license"] = dict(spdx_id=license_id)
    return value


def _revision(repository, number, role):
    return hashlib.sha1(canonical(dict(repository=repository, number=number, role=role)).encode()).hexdigest()


class AuthoredGitHubTransport:
    """No network, subprocess, source execution or external credentials."""
    def __init__(self):
        self.calls = []
        self.source_authorities = {}
        for (repository, number), fn in FUNCTIONS.items():
            self.source_authorities[(repository, number)] = dict(
                buggy=_revision(repository, number, "buggy"), fixed=_revision(repository, number, "fixed"),
                target_source=_source(fn), fixed_source=_source(recursive_demo.reference))

    def __call__(self, endpoint, headers):
        parsed = urlsplit(endpoint)
        query = parse_qs(parsed.query)
        parts = parsed.path.strip("/").split("/")
        if parsed.path == "/search/issues":
            repository = query["q"][0].split()[0].split(":", 1)[1]
            if repository not in REPOSITORIES:
                raise PermissionError("fixture transport accepts only its two authored repositories")
            count = min(int(query["per_page"][0]), len([key for key in FUNCTIONS if key[0] == repository]))
            value = dict(incomplete_results=False, total_count=count, items=[dict(number=number,
                title="Fix authored " + FUNCTIONS[(repository, number)].__name__, pull_request={},
                html_url=f"https://github.com/{repository}/pull/{number}") for number in range(1, count+1)])
        else:
            if len(parts) < 3 or parts[0] != "repos":
                raise PermissionError("unreviewed fixture endpoint")
            repository = "/".join(parts[1:3])
            if repository not in REPOSITORIES:
                raise PermissionError("external repository is outside the fixture authority")
            if len(parts) == 3:
                value = dict(id=100+REPOSITORIES.index(repository), full_name=repository,
                    private=False, license=dict(spdx_id="MIT"))
            elif parts[3] == "pulls":
                number = int(parts[4])
                authority = self.source_authorities[(repository, number)]
                if len(parts) == 5:
                    value = dict(number=number, merged=True, merge_commit_sha=authority["fixed"],
                        body="Fictional authored regression fixture; not evidence of a real project defect.",
                        base=dict(repo=dict(full_name=repository), sha=_revision(repository, number, "reported-base")),
                        head=dict(sha=_revision(repository, number, "reported-head")))
                else:
                    value = [dict(filename="src/target.py", status="modified", additions=1, deletions=1,
                        sha=_blob_sha(authority["fixed_source"]), patch="@@ -1 +1 @@\n-authored buggy\n+authored fixed"),
                        dict(filename="tests/test_target.py", status="added", additions=1, deletions=0,
                            sha=_blob_sha("assert authored_fixture\n"), patch="@@ -0 +1 @@\n+assert authored_fixture")]
            elif parts[3] == "commits":
                authority = next(value for (repo, _), value in self.source_authorities.items()
                    if repo == repository and value["fixed"] == parts[4])
                value = dict(sha=authority["fixed"], parents=[dict(sha=authority["buggy"])])
            elif parts[3] == "license":
                if query["ref"][0] not in {value["fixed"] for (repo, _), value in self.source_authorities.items() if repo == repository}:
                    raise PermissionError("fixture license must bind a frozen fixed revision")
                value = _file_response(LICENSE_TEXT, "LICENSE", license_id="MIT")
            elif parts[3] == "contents":
                if "/".join(parts[4:]) != "src/target.py":
                    raise PermissionError("fixture source path is not reviewed")
                revision = query["ref"][0]
                authority = next(value for (repo, _), value in self.source_authorities.items()
                    if repo == repository and revision in (value["buggy"], value["fixed"]))
                text = authority["target_source"] if revision == authority["buggy"] else authority["fixed_source"]
                value = _file_response(text, "src/target.py")
            else:
                raise PermissionError("unreviewed fixture endpoint")
        raw = canonical(value).encode("utf-8")
        etag = '"' + _hash(raw) + '"'
        cached = headers.get("If-None-Match") == etag
        self.calls.append(dict(endpoint=endpoint, status=304 if cached else 200,
            returned_bytes=0 if cached else len(raw)))
        return (304 if cached else 200), {"etag": etag, "content-type": "application/json"}, b"" if cached else raw


def _fixture_authority(candidate):
    """Exact authored-source whitelist, separate from real-data qualification."""
    candidate = validate_candidate(candidate)
    key = candidate["repository"], candidate["number"]
    fn = FUNCTIONS.get(key)
    if fn is None or fn.__module__ != "tomolab.recursive_demo" or fn.__name__ not in FUNCTION_SHA256:
        raise PermissionError("the fixture authority cannot execute an external callable")
    for function in (fn, recursive_demo.reference, recursive_demo.reset_fixture):
        if (function.__module__ != "tomolab.recursive_demo"
                or FUNCTION_SHA256[function.__name__] != _hash(_source(function).encode("utf-8"))):
            raise PermissionError("authored callable changed; explicit fixture review required")
    repository, number = key
    buggy, fixed = _revision(repository, number, "buggy"), _revision(repository, number, "fixed")
    if (candidate["candidate_id"] != candidate_identity(repository, number)
            or candidate["buggy_revision"] != buggy or candidate["fixed_revision"] != fixed
            or candidate["provenance"]["qualification_reserved"] is not True
            or candidate["license"]["text"] != LICENSE_TEXT or len(candidate["source_blobs"]) != 2):
        raise PermissionError("candidate is outside the exact authored fixture registration")
    blobs = {(blob["path"], blob["revision"]):blob for blob in candidate["source_blobs"]}
    expected = {("src/target.py", buggy):(fn, FUNCTION_SHA256[fn.__name__]),
                ("src/target.py", fixed):(recursive_demo.reference, FUNCTION_SHA256["reference"])}
    if set(blobs) != set(expected):
        raise PermissionError("exact authored buggy/fixed source pair required")
    for identity, (function, expected_sha) in expected.items():
        if blobs[identity]["text"] != _source(function) or blobs[identity]["sha256"] != expected_sha:
            raise PermissionError("harvested source does not match the reviewed authored callable")
    return fn, dict(candidate_id=candidate["candidate_id"], candidate_metadata_digest=candidate["metadata_digest"],
        repository=repository, number=number, source_lineage_id="authored-harvest-"+fn.__name__,
        function=fn.__name__, module=fn.__module__, implementation_sha256=FUNCTION_SHA256[fn.__name__],
        fixed_implementation_sha256=FUNCTION_SHA256["reference"], oracle_sha256=FUNCTION_SHA256["reference"],
        evidence_class=EVIDENCE_CLASS, real_development_eligible=False)


def run_demo(workspace):
    """Run the actual registry/update pipeline with authored data and callables."""
    started = time.perf_counter()
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    transport = AuthoredGitHubTransport()
    client = GitHubRestClient(workspace/"github-cache", transport=transport)
    frozen = dict(schema="tomolab-authored-harvest-contract-v1", evidence_class=EVIDENCE_CLASS,
        transport="IN_PROCESS_AUTHORED_HTTP_FIXTURE_NO_NETWORK", repositories=list(REPOSITORIES),
        functions=deepcopy(FUNCTION_SHA256), contract=recursive_demo.CONTRACT,
        paired_experiment_contract_sha256=recursive_demo.EXPERIMENT,
        expected_generations=["G0", "G1", "G2"], real_development_eligible=False,
        real_target_calls=0, real_oracle_calls=0)
    frozen["sha256"] = digest(frozen)
    save_new(workspace/"authored-harvest-contract.json", frozen)
    first = run_harvest(workspace, repositories=REPOSITORIES, max_candidates=4,
        max_details=4, max_qualifications=4, client=client)
    second = run_harvest(workspace, repositories=REPOSITORIES, max_candidates=4,
        max_details=4, max_qualifications=4, client=client)
    registry = HarvestRegistry(workspace)
    candidates = registry.candidates()
    authority_started = time.perf_counter()
    authorities = {}
    for candidate in candidates.values():
        fn, authority = _fixture_authority(candidate)
        authorities[fn.__name__] = (fn, authority)
    authority_seconds = time.perf_counter()-authority_started
    if set(authorities) != {"gain_a", "gain_b", "loss_a", "loss_b"}:
        raise ValueError("the complete four-case authored supply chain is required")
    if any(value["status"] == "DEVELOPMENT_ELIGIBLE" for value in registry.assessments().values()):
        raise AssertionError("fixture authority must never promote real registry eligibility")
    save_new(workspace/"authored-authority.json", dict(schema="tomolab-authored-harvest-authority-v1",
        contract_digest=frozen["sha256"], bindings=[value[1] for value in authorities.values()],
        authority_wall_seconds=authority_seconds, evidence_class=EVIDENCE_CLASS))
    mold = recursive_demo.fixture_mold()
    save_new(workspace/"mold.json", mold)
    store = workspace/"generations.jsonl"
    create_generation(store, mold, recursive_demo.CONTRACT)
    wave_results = []
    for generation_id, names in (("G1", ("gain_a", "gain_b")), ("G2", ("loss_a", "loss_b"))):
        bindings = [authorities[name][1] for name in names]
        registry.append("M0", dict(phase="START", evidence_class=EVIDENCE_CLASS,
            experiment_contract_sha256=recursive_demo.EXPERIMENT, supply_chain_contract_sha256=frozen["sha256"],
            candidate_bindings=bindings), batch_id="authored-"+generation_id)
        wave_started = time.perf_counter()
        receipts, lineages, linkage = [], [], []
        carrier_cost = dict(target_calls=0, oracle_calls=0)
        for name in names:
            fn, binding = authorities[name]
            paired, lineage, carrier = recursive_demo.collect_fixture(mold, fn,
                binding["source_lineage_id"], run_id="harvest-"+generation_id+"-"+name)
            if (lineage["implementation_sha256"] != binding["implementation_sha256"]
                    or lineage["oracle_sha256"] != binding["oracle_sha256"]):
                raise ValueError("actual callable observation differs from harvested source authority")
            for receipt in paired["receipts"]:
                if (receipt["source_lineage_id"] != binding["source_lineage_id"]
                        or receipt["identity"]["implementation_sha256"] != binding["implementation_sha256"]
                        or receipt["identity"]["oracle_sha256"] != binding["oracle_sha256"]):
                    raise ValueError("paired receipt does not bind its harvested authored source")
                linkage.append(dict(candidate_id=binding["candidate_id"],
                    candidate_metadata_digest=binding["candidate_metadata_digest"],
                    source_lineage_id=binding["source_lineage_id"],
                    implementation_sha256=binding["implementation_sha256"],
                    pair_receipt_sha256=receipt["pair_receipt_sha256"]))
            receipts.extend(paired["receipts"])
            lineages.append(lineage)
            for key in carrier_cost:
                carrier_cost[key] += carrier[key]
        wave_seconds = time.perf_counter()-wave_started
        cost = dict(target_calls=carrier_cost["target_calls"]+sum(r["cost"]["target_calls"] for r in receipts),
            oracle_calls=carrier_cost["oracle_calls"]+sum(r["cost"]["oracle_calls"] for r in receipts),
            reset_calls=sum(r["cost"]["reset_calls"] for r in receipts), observation_wall_seconds=wave_seconds,
            learning_seconds=0.0, validation_seconds=authority_seconds if not wave_results else 0.0, io_seconds=0.0)
        manifest = make_development_manifest(lineages, recursive_demo.EXPERIMENT, evidence_class=EVIDENCE_CLASS)
        record = dict(phase="COMPLETE", evidence_class=EVIDENCE_CLASS,
            experiment_contract_sha256=recursive_demo.EXPERIMENT, supply_chain_contract_sha256=frozen["sha256"],
            candidate_bindings=linkage, paired_receipt_digests=[r["pair_receipt_sha256"] for r in receipts],
            development_cost_ledger=cost, carrier_cost=carrier_cost, real_target_calls=0, real_oracle_calls=0)
        save_new(workspace/(generation_id+"-development.json"), dict(manifest=manifest, receipts=receipts, m0_record=record))
        registry.append("M0", record, batch_id="authored-"+generation_id)
        update = _append_update(registry, receipts, manifest, store,
            generation_id=generation_id, m0_record=record)
        wave_results.append(dict(generation_id=generation_id, candidate_bindings=linkage,
            paired_receipts=len(receipts), development_cost_ledger=cost, update=update))
    resumed = []
    for generation_id in ("G0", "G1", "G2"):
        process = subprocess.run([sys.executable, "-m", "tomolab.recursive_demo", "--resume", str(workspace),
            "--generation", generation_id], capture_output=True, text=True, timeout=90)
        if process.returncode:
            raise RuntimeError("saved harvest generation failed to execute in a new process")
        resumed.append(json.loads((workspace/(generation_id+"-resumed.json")).read_text(encoding="utf-8")))
    actual = [value["input"] for value in resumed]
    if actual != [[-1,-2],[1,1],[-1,-2]] or resumed[1]["full_new_search_changed_common"] < 1:
        raise AssertionError("authored harvest experience did not change next execution")
    if len({value["process_id"] for value in resumed}) != len(resumed):
        raise AssertionError("distinct actual restart processes required")
    summary = dict(schema="tomolab-harvest-functional-summary-v1", status="COMPLETE",
        evidence_class=EVIDENCE_CLASS, harvester_status="HARVESTER_FUNCTIONAL",
        recursive_update="RECURSIVE_UPDATE_FUNCTIONAL", transfer_utility="NOT_ESTABLISHED",
        oos="NOT_ESTABLISHED", generation_performance_improvement="NOT_ESTABLISHED",
        registered_candidates=first["registered_new"], duplicates_skipped=second["duplicates_skipped"],
        rerun_registered_new=second["registered_new"], registry_candidates=len(candidates),
        review_queue_count=second["review_queue_count"], distribution=second["distribution"],
        actual_network_calls=0, authored_transport_requests=len(transport.calls),
        conditional_304_responses=sum(call["status"]==304 for call in transport.calls),
        source_authority_bindings=[value[1] for value in authorities.values()],
        wave_results=wave_results, executed_candidates=actual,
        fresh_search_changed_common=[value["full_new_search_changed_common"] for value in resumed],
        restarted_processes=len(resumed), resumed=resumed,
        authored_development_cost={key:sum(value["development_cost_ledger"][key] for value in wave_results)
            for key in ("target_calls", "oracle_calls", "reset_calls", "observation_wall_seconds")},
        real_eligible=0, real_target_calls=0, real_oracle_calls=0,
        wall_seconds=time.perf_counter()-started, default_adoption="HOLD", allow_release=False)
    save_new(workspace/"summary.json", summary)
    return summary
