"""E8 final host CLI: live readiness precedes any evaluator source import.

Trusted-host receipts are attestations, not proof of ownership, Oracle truth,
semantic independence, or hostile-host isolation. The environment selects one
cooperative authority; an output path never selects a new usage ledger.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomolab.discovery.evaluation_readiness import EvaluationReadiness
from tomolab.discovery.evaluation_usage import UsageLedger, identity_tokens
from tomolab.discovery.schema import canonical, digest, keys

AUTHORITY_ENV = "TOMOLAB_E8_AUTHORITY_DIRECTORY"
REGISTRY = ROOT/"docs/E8_CONSUMED_IDENTITIES.json"
CONTRACT = ROOT/"docs/E8_EVALUATION_CONTRACT.json"
FREEZE = ROOT/"docs/E8_CODE_FREEZE.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("pinned SHA-256 required")
    return value


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _blocked(reason, *, readiness=None, blockers=()):
    result = {"schema":"tomolab-e8-host-gate-v1", "status":"NOT_EXECUTED_READINESS_BLOCKED",
        "reason":reason, "blockers":list(blockers), "target_calls":0, "oracle_calls":0,
        "final_attempts":0, "final_execution_started":False,
        "authority_scope":"TRUSTED_HOST_ATTESTATION_AND_COOPERATIVE_WRITERS_NOT_GLOBAL_OR_HOSTILE_HOST_PROTECTION"}
    if readiness is not None:
        result["readiness"] = readiness
        result["blockers"] = sorted(set(result["blockers"]+readiness.get("blockers", [])))
    return result


def _registry():
    registry, contract = _read(REGISTRY), _read(CONTRACT)
    keys(registry, ("schema", "source_revision", "identities", "excluded_research_target_projects", "authority", "old_E1_E7_final_inputs_answers_plans_accessed"))
    if (registry["schema"] != "tomolab-e8-consumed-identities-v1"
            or registry["old_E1_E7_final_inputs_answers_plans_accessed"] is not False
            or registry["source_revision"] != contract.get("baseline_commit")
            or _sha(REGISTRY) != contract.get("consumed_identity_registry_sha256")):
        raise ValueError("consumed identity registry differs from the pinned E8 contract")
    identities = registry["identities"]
    if not isinstance(identities,list) or not identities or len(identities)>4096:
        raise ValueError("nonempty bounded individual consumed registry required")
    for identity in identities:
        identity_tokens(identity)
    excluded = registry["excluded_research_target_projects"]
    if not isinstance(excluded,list) or "antemortem-structural-lab" not in excluded:
        raise ValueError("lab research-target exclusion is missing")
    return registry, contract


def _authority(directory):
    configured = os.environ.get(AUTHORITY_ENV)
    if not configured:
        return None, None, "고정 host authority 환경 설정이 없습니다"
    root = Path(configured).expanduser().resolve()
    if directory is not None and Path(directory).expanduser().resolve() != root:
        return None, None, "authority-directory가 고정 환경 정본과 다릅니다"
    if root == ROOT or root.is_relative_to(ROOT):
        return None, None, "사용 이력 정본은 공개 저장소 밖에 두어야 합니다"
    ledger = UsageLedger(root/"FINAL_USAGE.jsonl")
    return ledger, ledger.authority_id, None


def _context(args, registry):
    values = _read(args.bundle) if args.bundle else {}
    keys(values, (), ("evidence_bundle", "knowledge_snapshot", "lineage_review", "targets", "fixed_protocol"))
    values = deepcopy(values)
    for flag, name in (("evidence","evidence_bundle"),("knowledge","knowledge_snapshot"),
                       ("lineage","lineage_review"),("targets","targets"),("protocol","fixed_protocol")):
        path = getattr(args,flag)
        if path is not None:
            values[name] = _read(path)
    lineage = values.get("lineage_review")
    if lineage is None:
        lineage = {"status":"MISSING", "development":[], "consumed_targets":[], "review_receipt_sha256":"0"*64}
    if not isinstance(lineage,dict) or not isinstance(lineage.get("consumed_targets"),list):
        raise ValueError("lineage review must retain a consumed_targets array")
    identities = {canonical(row):deepcopy(row) for row in lineage["consumed_targets"]}
    identities.update({canonical(row):deepcopy(row) for row in registry["identities"]})
    lineage["consumed_targets"] = [identities[k] for k in sorted(identities)]
    values["lineage_review"] = lineage
    return values


def _target_exclusions(context, registry):
    forbidden = set().union(*(identity_tokens(i) for i in registry["identities"]))
    for target in context.get("targets") or []:
        if identity_tokens(target["identity"]) & forbidden:
            raise ValueError("Target overlaps an individually consumed final identity")
        project = target["provenance"]["project"].lower().removesuffix(".git").rsplit("/",1)[-1]
        if target["scope"] == "REVIEWED_REAL_PROJECT" and project in registry["excluded_research_target_projects"]:
            raise ValueError("lab project is excluded from real research Targets")


def required_frozen_files(root):
    root = Path(root)
    return {p.relative_to(root).as_posix() for p in (root/"tomolab").rglob("*.py")} | {
        "pyproject.toml", "scripts/evaluate-e8.py", "docs/E8_EVALUATION_CONTRACT.json", "docs/E8_CONSUMED_IDENTITIES.json",
        "scripts/check-e8-release-eligibility.py", "scripts/publish-e8.py", ".github/workflows/tests.yml",
        "scripts/check-wheel.py", "scripts/check-e8-freeze.py", "scripts/check-public-scope.py", "scripts/check-historical-e7-freeze.py"}


def _verify_execution_contract(context, registry, contract):
    """Verify all frozen code before mapping files or evaluator modules load."""
    protocol = context["fixed_protocol"]
    expected = protocol["product_hashes"]
    required = {"scripts/evaluate-e8.py", "docs/E8_CONSUMED_IDENTITIES.json", "docs/E8_EVALUATION_CONTRACT.json", "docs/E8_CODE_FREEZE.json"}
    if not isinstance(expected,dict) or not required <= set(expected):
        raise ValueError("host script, registry, contract, and E8 code freeze must be pinned in protocol")
    for name in required:
        if _sha(ROOT/name) != _hash(expected[name]):
            raise ValueError("frozen host input changed: "+name)
    frozen = _read(FREEZE)
    keys(frozen, ("schema", "version", "scope", "product_files", "product"))
    import tomllib
    if (frozen["schema"] != "tomolab-e8-code-freeze-v1"
            or frozen["scope"] != "IMPLEMENTATION_BYTES_NOT_RESEARCH_VERDICT"
            or frozen["version"] != tomllib.loads((ROOT/"pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]):
        raise ValueError("unsupported E8 code freeze")
    product = frozen["product"]
    mandatory = required_frozen_files(ROOT)
    if not isinstance(product,dict) or set(product) != mandatory or frozen["product_files"] != len(product):
        raise ValueError("E8 freeze omits required current product files")
    for name, expected_hash in product.items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or _sha(path) != _hash(expected_hash):
            raise ValueError("E8 frozen code changed: "+name)
    _target_exclusions(context,registry)
    real = any(t["scope"] == "REVIEWED_REAL_PROJECT" for t in context["targets"])
    if real and (contract.get("status") != "FINAL_PREREGISTERED" or not contract.get("final_authorization")
                 or contract.get("final_target_count") != len(context["targets"]) or not protocol.get("decision_rules")):
        raise ValueError("real final comparison is not preregistered in the E8 contract")
    _hash(protocol.get("evaluator_mapping_sha256"))


def _load_evaluators(path, expected_hash, targets, *, loader=None):
    """Validate every pin first; then import reviewed host modules and recheck."""
    path = Path(path).resolve(strict=True)
    if _sha(path) != _hash(expected_hash):
        raise ValueError("evaluator mapping differs from the frozen protocol")
    value = _read(path)
    keys(value, ("schema", "entries", "receipt_sha256"))
    if value["schema"] != "tomolab-e8-evaluator-mapping-v1" or value["receipt_sha256"] != digest({k:v for k,v in value.items() if k!="receipt_sha256"}):
        raise ValueError("evaluator mapping receipt mismatch")
    if not isinstance(value["entries"],list) or len(value["entries"]) != len(targets):
        raise ValueError("exact evaluator metadata batch required")
    tasks = {t["target_id"]:t for t in targets}; pinned = []; seen = set()
    for entry in value["entries"]:
        keys(entry, ("target_id", "target", "oracle"))
        tid = entry["target_id"]
        if tid not in tasks or tid in seen:
            raise ValueError("evaluator metadata has an extra or duplicate Target")
        seen.add(tid); resolved = {}
        for kind, identity in (("target","implementation_sha256"),("oracle","oracle_sha256")):
            item = entry[kind]
            keys(item, ("path", "function", "file_sha256"))
            if not isinstance(item["path"],str) or not item["path"] or not isinstance(item["function"],str) or not item["function"].isidentifier():
                raise ValueError("local reviewed file path and callable identifier required")
            source = (path.parent/item["path"]).resolve(strict=True)
            if not source.is_file() or _sha(source) != _hash(item["file_sha256"]) or item["file_sha256"] != tasks[tid]["provenance"][identity]:
                raise ValueError("evaluator file differs from reviewed Target/Oracle identity")
            resolved[kind] = dict(path=source, function=item["function"], file_sha256=item["file_sha256"])
        if resolved["target"]["path"] == resolved["oracle"]["path"]:
            raise ValueError("separate target and Oracle modules required")
        pinned.append((tid,resolved))
    if loader is None:
        from tomolab.mold.service import _load
        loader = _load
    evaluators = {}
    for tid, sources in pinned:
        callbacks = {}
        for kind, identity in (("target","implementation_sha256"),("oracle","oracle_sha256")):
            item = sources[kind]
            fn, observed = loader(item["path"],item["function"])
            if not callable(fn) or observed != item["file_sha256"]:
                raise ValueError("evaluator changed during import")
            callbacks[kind] = fn; callbacks[identity] = observed
        evaluators[tid] = callbacks
    for _, sources in pinned:
        for item in sources.values():
            if _sha(item["path"]) != item["file_sha256"]:
                raise ValueError("evaluator changed while modules were imported")
    if _sha(path) != expected_hash:
        raise ValueError("evaluator mapping changed while modules were imported")
    return evaluators


def execute(args):
    host_started = time.perf_counter()
    registry, contract = _registry()
    context = _context(args,registry)
    ledger, authority_id, authority_error = _authority(args.authority_directory)
    readiness = EvaluationReadiness(**context,usage_ledger=ledger,authority=authority_id)
    authorization = readiness.authorize_final_comparison()
    if authorization["status"] != "PASS":
        return _blocked("readiness 조건이 충족되지 않았습니다",readiness=authorization),3
    if not args.final_authorized or not args.allow_local_execution:
        return _blocked("--final-authorized와 --allow-local-execution이 모두 필요합니다",readiness=authorization,
                        blockers=["READINESS_BLOCKED_HOST_AUTHORIZATION"]),3
    if authority_error:
        return _blocked(authority_error,readiness=authorization,blockers=["READINESS_BLOCKED_USAGE_AUTHORITY"]),3
    _verify_execution_contract(context,registry,contract)
    if args.evaluators is None or args.output is None:
        return _blocked("동결된 evaluator mapping과 비공개 output 경로가 필요합니다",readiness=authorization,
                        blockers=["READINESS_BLOCKED_COMPARISON_CONTRACT"]),3
    from tomolab.discovery.qualified_comparison import prepare_comparison, compare_frozen
    prepared = prepare_comparison(readiness)
    if prepared["status"] != "PREPARED":
        return prepared,3
    evaluators = _load_evaluators(args.evaluators,context["fixed_protocol"]["evaluator_mapping_sha256"],context["targets"])
    # Modules may have import-time effects. Recheck current product, registry,
    # authority, and readiness before the runner performs its atomic START.
    current_registry, current_contract = _registry()
    if current_registry != registry or current_contract != contract:
        raise ValueError("registry or final contract changed during evaluator import")
    _verify_execution_contract(context,current_registry,current_contract)
    live = readiness.authorize_final_comparison()
    if canonical(live) != canonical(authorization):
        return _blocked("evaluator import 이후 readiness가 변경되었습니다",readiness=live),3
    result = compare_frozen(readiness,evaluators,output=args.output,trusted_execution=True,expected_authorization=authorization,
                            host_preflight_wall_seconds=time.perf_counter()-host_started)
    return result, 0 if result.get("comparison_status") == "COMPLETE" else 3


def parser():
    value = argparse.ArgumentParser(description="E8 고정 비교: readiness 이전에는 Target/Oracle import 없음")
    value.add_argument("--bundle",type=Path,help="host-only constructor JSON; 실행 권한·함수 제외")
    for field in ("evidence","knowledge","lineage","targets","protocol","evaluators"):
        value.add_argument("--"+field,type=Path)
    value.add_argument("--authority-directory",type=Path,help=AUTHORITY_ENV+" 환경 정본과 같은 경로만 허용")
    value.add_argument("--final-authorized",action="store_true")
    value.add_argument("--allow-local-execution",action="store_true",help="검토한 host 실행 승인; OS 격리 아님")
    value.add_argument("--output",type=Path,help="비공개 결과 경로; 기존 결과를 덮어쓰지 않음")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = execute(args)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,ImportError) as error:
        result, code = _blocked("host gate 검증 실패: "+str(error),blockers=["READINESS_BLOCKED_HOST_CONTRACT"]),3
    # Final raw inputs/outcomes stay only in the runner's private output file.
    public = {k:v for k,v in result.items() if k not in ("rows","frozen_plans","authorization","error")}
    if result.get("error"):
        public["error"] = {k:v for k,v in result["error"].items() if k != "raw"}
    if args.output is not None and not result.get("final_attempts"):
        try:
            destination = args.output.resolve(); destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                public["report_output_status"] = "EXISTING_FILE_PRESERVED"
            else:
                with destination.open("x",encoding="utf-8",newline="\n") as stream:
                    json.dump(result,stream,ensure_ascii=False,allow_nan=False,indent=2); stream.write("\n")
        except OSError as error:
            public["report_output_status"] = "NOT_WRITTEN:"+type(error).__name__
    print(json.dumps(public,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
