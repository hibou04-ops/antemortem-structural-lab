"""R1 claim meaning and reviewed Source development commands.

Gate A Source validation never authorizes independent transfer. Public demos
use only bundled authored functions. Host execution is not an OS sandbox.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

COMMANDS = ("semantic-learn","semantic-inspect","semantic-plan","semantic-validate","semantic-run","semantic-demo")


def register(commands):
    from .discovery.claim_semantics import CLAIM_KINDS
    learn=commands.add_parser("semantic-learn",help="전체 수용 개발 증거를 종류별 의미로 학습; 기존 반증은 보존")
    learn.add_argument("--bundle",type=Path,required=True)
    learn.add_argument("--implementation-hash",required=True)
    learn.add_argument("--spec-hash",required=True)
    learn.add_argument("--parent-snapshot",type=Path)
    learn.add_argument("--semantic-policy",type=Path)
    learn.add_argument("--claim-kind",action="append",choices=CLAIM_KINDS)
    learn.add_argument("--generation-id",default="E8-R1-SOURCE")
    inspect=commands.add_parser("semantic-inspect",help="종류별 TP/FP/FN/TN/UNKNOWN와 반증 ID 확인; 실행 없음")
    inspect.add_argument("--archive",type=Path,required=True)
    plan=commands.add_parser("semantic-plan",help="공개 입력만으로 제한된 계획 생성; Source와 독립 전이는 별도 게이트")
    plan.add_argument("--archive",type=Path,required=True)
    plan.add_argument("--spec",type=Path,required=True)
    plan.add_argument("--provenance",type=Path,required=True)
    plan.add_argument("--purpose",choices=("INDEPENDENT_TRANSFER","SOURCE_DEVELOPMENT"),default="INDEPENDENT_TRANSFER")
    plan.add_argument("--allow-unvalidated-empirical",action="store_true",help="Source 개발 시험만 허용; 경험적 규칙 채택 아님")
    _planning_options(plan)
    validation=commands.add_parser("semantic-validate",help="동결된 Source 표현을 새 개발 배치로 검증; C나 최종 평가 아님")
    validation.add_argument("--archive",type=Path,required=True)
    validation.add_argument("--bundle",type=Path,required=True)
    validation.add_argument("--implementation-hash",required=True)
    validation.add_argument("--spec-hash",required=True)
    validation.add_argument("--generation-id",required=True)
    validation.add_argument("--approve-development-evidence",action="store_true")
    run=commands.add_parser("semantic-run",help="검토한 Source와 독립 Oracle 실행; Gate A 전용, host OS 격리 없음")
    run.add_argument("path",type=Path)
    run.add_argument("--oracle-file",type=Path,required=True)
    run.add_argument("--spec",type=Path,required=True)
    run.add_argument("--provenance",type=Path,required=True)
    run.add_argument("--oracle-validation",type=Path,required=True)
    run.add_argument("--comparison-policy",type=Path)
    run.add_argument("--archive",type=Path)
    run.add_argument("--counterexamples",type=Path)
    run.add_argument("--function",default="implementation")
    run.add_argument("--oracle",default="reference")
    run.add_argument("--input-guard-file",type=Path)
    run.add_argument("--input-guard-function",default="input_accepts")
    run.add_argument("--method",choices=("A","B","C","D"),default="C")
    run.add_argument("--time-budget",type=float,default=15.0)
    run.add_argument("--allow-unvalidated-empirical",action="store_true")
    run.add_argument("--allow-local-execution",action="store_true")
    _planning_options(run)
    demo=commands.add_parser("semantic-demo",help="작성한 부분 실패 예제의 학습→계획→Oracle 실행; 연구 성과 아님")
    demo.add_argument("--budget",type=int,default=12,help="한쪽당 실제 호출 상한, 재현 포함; 작성 예제는 3..32")
    for parser in (learn,inspect,plan,validation,run,demo):parser.add_argument("--output")


def _planning_options(parser):
    parser.add_argument("--budget",type=int,default=64,help="계획 길이 또는 한쪽당 실제 호출 상한(재현 포함)")
    parser.add_argument("--guidance-budget",type=int)
    parser.add_argument("--pool-size",type=int,default=128)
    parser.add_argument("--seed",type=int,default=313)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _unwrapped(value):
    return value["archive"] if isinstance(value,dict) and value.get("schema") in ("tomolab-semantic-demo-v1","tomolab-semantic-validation-v1") else value


def _archive(path):
    from .discovery.knowledge import KnowledgeArchive
    result=KnowledgeArchive.from_snapshot(_unwrapped(_read(path)))
    if result.semantic_policy is None:raise ValueError("명시적인 R1 의미 archive가 필요합니다")
    return result


def _bundle(path):
    from .e8_cli import _evidence
    value=_read(path)
    if isinstance(value,dict) and value.get("schema")=="tomolab-semantic-demo-v1":value=value["evidence_bundle"]
    return _evidence(value)


def _settings(args):
    from .discovery.schema import integer
    integer(args.budget,1,4096);integer(args.seed,0,2**32-1);integer(args.pool_size,1,4096)
    guidance=min(16,args.budget//2) if args.guidance_budget is None else args.guidance_budget
    integer(guidance,0,args.budget//2)
    return dict(budget=args.budget,guidance_budget=guidance,pool_size=args.pool_size,seed=args.seed)


def inspect_archive(archive):
    from .discovery.claim_semantics import CLAIM_KINDS
    from .discovery.schema import canonical,digest
    claims=archive.claims();counts={}
    for kind in CLAIM_KINDS:
        selected=[c for c in claims if c["claim_kind"]==kind]
        counts[kind]={"claims":len(selected),"source_statuses":dict(Counter(c["source_claim_status"] for c in selected)),
            "cell_totals":{cell:sum(c["source_statistics"][cell] for c in selected) for cell in ("TP","FP","FN","TN","UNKNOWN")},
            "without_positive_support":sum(not c["positive_support"] for c in selected),
            "trivial":sum(c["trivial"] for c in selected),"coordinate_only":sum(c["coordinate_only"] for c in selected)}
    return dict(schema="tomolab-semantic-inspection-v1",semantic_version="e8-r1-claims-v1",
        source_archive_sha256=archive.snapshot()["receipt"]["sha256"],unique_expressions=len({digest(c["typed_relation"]) for c in claims}),
        semantic_claim_count=len(claims),by_kind=counts,claims=[{k:c[k] for k in (
            "claim_id","claim_kind","semantic_version","typed_relation","derived_from","source_claim_status",
            "source_validation_status","corroboration_status","target_applicability","transfer_validation_status",
            "source_statistics","source_validation_statistics","corroboration_statistics","confusion_evidence",
            "counterevidence","unknown_evidence","positive_support","trivial","coordinate_only","utility_status")} for c in claims],
        cell_count_scope="OVERLAPPING_RULE_OBSERVATIONS_NOT_INDEPENDENT_SAMPLE_COUNT",target_calls=0,oracle_calls=0,
        external_transfer="NOT_EXECUTED_READINESS_BLOCKED",scope="HOST_DEVELOPMENT_DATA_ONLY_NOT_RESEARCH_PROMOTION")


def dispatch(args, parser, examples):
    from .discovery.schema import identifier
    if args.output and Path(args.output).exists():
        raise ValueError("기존 산출물을 보존합니다; 새로운 output 경로를 사용하세요")
    if args.output:
        destination=Path(args.output).resolve()
        for field in ("archive","bundle","parent_snapshot","semantic_policy","spec","provenance","oracle_validation","comparison_policy","path","oracle_file","input_guard_file","counterexamples"):
            source=getattr(args,field,None)
            if source is not None and Path(source).resolve()==destination:
                raise ValueError("입력·기존 archive를 output으로 덮어쓸 수 없습니다")
    if args.command=="semantic-learn":
        from .e8_cli import _selected
        from .discovery.claim_semantics import normalize_policy,normalize_claim_kinds
        evidence=_bundle(args.bundle);records=_selected(evidence,args.implementation_hash,args.spec_hash)
        policy=normalize_policy(_read(args.semantic_policy) if args.semantic_policy else None)
        kinds=normalize_claim_kinds(args.claim_kind)
        parent=_unwrapped(_read(args.parent_snapshot)) if args.parent_snapshot else None
        archive=evidence.build_knowledge_archive([r["record_id"] for r in records],semantic_policy=policy,claim_kinds=kinds,derived_from=parent)
        archive.freeze();archive=archive.fork(identifier(args.generation_id));return archive.freeze()
    if args.command=="semantic-inspect":return inspect_archive(_archive(args.archive))
    if args.command=="semantic-plan":
        from .discovery.knowledge_engine import plan_knowledge
        archive=_archive(args.archive)
        return plan_knowledge(archive.snapshot(),_read(args.spec),target_provenance=_read(args.provenance),
            purpose=args.purpose,allow_unvalidated_empirical=args.allow_unvalidated_empirical,**_settings(args))
    if args.command=="semantic-validate":
        if not args.approve_development_evidence:parser.error("--approve-development-evidence 검토 승인이 필요합니다")
        from .e8_cli import _selected
        parent=_archive(args.archive)
        if not parent.frozen:raise ValueError("추가 배치 전에 Source archive를 동결해야 합니다")
        evidence=_bundle(args.bundle);records=_selected(evidence,args.implementation_hash,args.spec_hash)
        child=parent.fork(identifier(args.generation_id))
        child.record_source_validation([evidence.observation(r["record_id"]) for r in records],
            frozen_before_sha256=parent.snapshot()["receipt"]["sha256"],trusted_observation=True,
            batch_receipt_sha256=evidence.snapshot()["receipt_sha256"])
        result=child.freeze()
        return dict(schema="tomolab-semantic-validation-v1",archive=result,source_validation="RECORDED_ON_SAME_SOURCE_ONLY",
            raw_bundle_records=evidence.summary()["record_count"],accepted_model_observations=len(records),
            additional_target_calls=0,additional_oracle_calls=0,external_transfer="NOT_EXECUTED_READINESS_BLOCKED")
    if args.command=="semantic-run":return _run(args,parser)
    if args.command=="semantic-demo":return _demo(examples,args.budget)
    raise ValueError("알 수 없는 R1 명령")


def _comparison(value):
    from .discovery.schema import keys
    keys(value,("kind","absolute_tolerance","relative_tolerance","undefined","exceptions"))
    if value["kind"]!="FINITE_JSON" or value["undefined"]!="EXECUTION_ERROR" or value["exceptions"]!="EXECUTION_ERROR":
        raise ValueError("검토한 유한 JSON 비교·오류 계약이 필요합니다")
    for key in ("absolute_tolerance","relative_tolerance"):
        number=value[key]
        if type(number) not in (int,float) or not math.isfinite(number) or number<0:raise ValueError("유한 비음수 허용오차가 필요합니다")
    return deepcopy(value)


def _reviewed_files(args):
    """Everything here is data/hash validation, before any module import."""
    from .discovery.schema import digest,keys,validate_spec
    from .discovery.knowledge import validate_provenance
    from .discovery.development_evidence import _hash
    for name,default in (("function","implementation"),("oracle","reference"),("input_guard_function","input_accepts")):
        if not isinstance(getattr(args,name,default),str) or not getattr(args,name,default).isidentifier():
            raise ValueError("검토된 Python 함수 이름이 필요합니다")
    spec=validate_spec(_read(args.spec));origin=validate_provenance(_read(args.provenance));review=_read(args.oracle_validation)
    keys(review,("schema","status","receipt_id","implementation_hash","oracle_hash","public_spec_hash","comparison_policy","receipt_sha256","authority"),
        ("limitations","input_guard_sha256"))
    if review["schema"]!="tomolab-e8r1-oracle-validation-v1" or review["status"]!="VALIDATED" or not review["receipt_id"]:
        raise ValueError("실행 전에 검토된 Oracle 영수증이 필요합니다")
    if review["receipt_sha256"]!=digest({k:v for k,v in review.items() if k!="receipt_sha256"}):raise ValueError("Oracle 검토 영수증의 결속이 다릅니다")
    if (review["implementation_hash"],review["oracle_hash"],review["public_spec_hash"])!=(origin.get("implementation_sha256"),origin.get("oracle_sha256"),digest(spec)):
        raise ValueError("Source·Oracle·공개 계약의 결속이 다릅니다")
    policy=_comparison(_read(args.comparison_policy) if args.comparison_policy else review["comparison_policy"])
    if policy!=review["comparison_policy"]:raise ValueError("원래 검토한 비교 정책을 바꿀 수 없습니다")
    target=args.path.resolve(strict=True);oracle=args.oracle_file.resolve(strict=True)
    if target==oracle:raise ValueError("별도 검토 Oracle 파일이 필요합니다")
    if (_sha(target),_sha(oracle))!=(_hash(origin.get("implementation_sha256")),_hash(origin.get("oracle_sha256"))):
        raise ValueError("실행 전 파일 해시가 provenance와 일치해야 합니다")
    guard=None
    if args.input_guard_file is not None:
        guard=args.input_guard_file.resolve(strict=True)
        if _sha(guard)!=_hash(review.get("input_guard_sha256")):raise ValueError("입력 guard 파일이 Oracle 계약과 일치하지 않습니다")
    elif spec["contract"]["preconditions"]:
        raise ValueError("Source 전제조건이 있으면 검토·고정된 입력 guard가 필요합니다")
    if len(spec["contract"]["invariants"])!=1:raise ValueError("하나의 검토된 Source 비교 invariant가 필요합니다")
    return spec,origin,review,policy,target,oracle,guard


def _run(args,parser):
    if not args.allow_local_execution:parser.error("--allow-local-execution이 필요합니다; 검토한 host 실행이며 OS 격리가 없습니다")
    from .discovery.schema import canonical,integer,validate_inputs
    settings=_settings(args);integer(settings["budget"],3,4096)
    if type(args.time_budget) not in (int,float) or not math.isfinite(args.time_budget) or not 0<args.time_budget<=15:
        raise ValueError("협력적 실행 시간은 0초 초과15초 이하입니다")
    spec,origin,review,policy,target,oracle,guard=_reviewed_files(args)
    source=_archive(args.archive) if args.archive else None
    if source is not None and (canonical(source.source)!=canonical(origin) or canonical(source.spec)!=canonical(spec)):
        raise ValueError("Source archive와 실행 구현·Oracle·계약이 다릅니다")
    if args.method=="C" and source is None:raise ValueError("C 방법에는 검토한 R1 Source archive가 필요합니다")
    if args.allow_unvalidated_empirical and args.method!="C":raise ValueError("미채택 경험적 규칙 시험은 C의 Source 개발 경로만 허용합니다")
    counterexamples=_read(args.counterexamples) if args.counterexamples else []
    if not isinstance(counterexamples,list) or len(counterexamples)>512:raise ValueError("제한된 검토 Source 반례 목록이 필요합니다")
    counterexamples=[validate_inputs(point,spec) for point in counterexamples]
    known=[]
    if source is not None:
        known=[e["inputs"] for e in source._source_evidence]
        if args.method=="D" and not args.counterexamples:
            counterexamples=[e["inputs"] for e in source._source_evidence if e["kind"]=="FAILURE"]
    from .mold.service import _load
    from .discovery.knowledge_service import run_source_development
    fn,target_hash=_load(target,args.function);ref,oracle_hash=_load(oracle,args.oracle)
    input_accepts=None
    if guard is not None:
        input_accepts,guard_hash=_load(guard,args.input_guard_function)
        if guard_hash!=review["input_guard_sha256"]:raise ValueError("guard가 import 중 변경됐습니다")
    if (target_hash,oracle_hash)!=(origin["implementation_sha256"],origin["oracle_sha256"]):raise ValueError("import 중 파일이 변경됐습니다")
    result=run_source_development(fn,ref,spec,source_provenance=origin,comparison_policy=policy,
        method=args.method,archive=source.snapshot() if source else None,approved_counterexamples=counterexamples,
        known_development_inputs=known,time_budget=args.time_budget,trusted_execution=True,input_accepts=input_accepts,
        allow_unvalidated_empirical=args.allow_unvalidated_empirical,**settings)
    if (_sha(target),_sha(oracle))!=(target_hash,oracle_hash) or guard is not None and _sha(guard)!=review["input_guard_sha256"]:
        raise ValueError("Source 실행 중 고정 파일이 변경됐습니다")
    result["oracle_validation_receipt_sha256"]=review["receipt_sha256"]
    return result


def _demo(examples,budget):
    """Four fixed authored inputs, each actually replayed three times."""
    from argparse import Namespace
    from .discovery.schema import canonical,digest,integer
    from .discovery.development_evidence import DevelopmentEvidenceArchive
    from .discovery.knowledge_engine import plan_knowledge
    from .discovery.knowledge_service import run_source_development
    from .discovery.claim_semantics import DEFAULT_POLICY,EXACT,SUFFICIENT
    integer(budget,3,32)
    folder=Path(examples)/"partial"
    args=Namespace(path=folder/"target.py",oracle_file=folder/"oracle.py",spec=folder/"spec.json",
        provenance=folder/"provenance.json",oracle_validation=folder/"oracle-validation.json",
        comparison_policy=None,input_guard_file=None)
    spec,origin,review,policy,target,oracle,_=_reviewed_files(args)
    from .mold.service import _load
    fn,target_hash=_load(target,"implementation");ref,oracle_hash=_load(oracle,"reference")
    if (target_hash,oracle_hash)!=(origin["implementation_sha256"],origin["oracle_sha256"]):raise ValueError("공개 예제 코드가 변경됐습니다")
    points=[{"x":0,"y":0},{"x":1,"y":1},{"x":-1,"y":0},{"x":0,"y":1}]
    evidence=DevelopmentEvidenceArchive("E8R1-AUTHORED-DEMO")
    for index,point in enumerate(points):
        pairs=[{"actual":fn(**point),"oracle":ref(**point)} for _ in range(3)]
        if len({canonical(value) for value in pairs})!=1:raise ValueError("공개 예제 재현이 불안정합니다")
        raw=dict(inputs=point,pairs=pairs);raw_sha=digest(raw)
        bindings=dict(implementation_hash=target_hash,oracle_identity=origin["oracle_id"],oracle_hash=oracle_hash,
            public_spec_hash=digest(spec),input_hash=digest(point),original_receipt_sha256=raw_sha)
        failed=pairs[0]["actual"]!=pairs[0]["oracle"]
        record=dict(record_id="authored-partial-"+str(index),generation_id="E8R1-AUTHORED-DEMO",split="DEVELOPMENT",
            producer_tool="ReviewedAuthoredReplay",producer_version="e8-r1-claims-v1",project=origin["project"],revision=origin["revision"],
            function_identity="authored-partial-function",implementation_hash=target_hash,oracle_identity=origin["oracle_id"],oracle_hash=oracle_hash,
            public_spec_hash=digest(spec),spec=spec,oracle_validation_receipt=dict(status="VALIDATED",receipt_id=review["receipt_id"],
                oracle_hash=oracle_hash,public_spec_hash=digest(spec),receipt_sha256=review["receipt_sha256"],bindings=bindings,
                authority="AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH",comparison_policy=policy),
            domain_validity=dict(status="VALID",receipt_sha256=digest(["domain",bindings]),bindings=bindings),input_or_trace=point,
            observed_failure_or_refutation=dict(status="FAILURE" if failed else "REFUTATION",invariant="reference",category="mismatch",
                actual_result=pairs[0]["actual"],oracle_result=pairs[0]["oracle"]),failure_signature="authored-partial-v1",
            replay_status=dict(status="REPRODUCED",deterministic=True,matching_observations=3,receipt_sha256=digest(["replay",raw]),bindings=bindings),
            execution_receipt=dict(status="COMPLETED",execution_kind="NEW_EXECUTION",target_calls=3,oracle_calls=3,original_receipt_sha256=raw_sha,bindings=bindings),
            provenance=dict(origin=origin,evidence_origin="AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH",parent_generation_id=None,
                source_file_sha256=target_hash,source_record_sha256=raw_sha))
        evidence.ingest(record,trusted_host=True)
    archive=evidence.build_knowledge_archive(semantic_policy=DEFAULT_POLICY);frozen=archive.freeze()
    equal={"term":{"kind":"equal","roles":["left","right"]},"operator":"eq","value":1}
    matching={c["claim_kind"]:c for c in archive.claims() if c["typed_relation"]==equal}
    if not matching[EXACT]["source_statistics"]["FN"] or matching[SUFFICIENT]["source_claim_status"]!="OBSERVED_WITHIN_SOURCE":
        raise ValueError("작성 예제의 완전 분류와 부분 충분조건 구분이 재현되지 않았습니다")
    common=dict(target_provenance=origin,purpose="SOURCE_DEVELOPMENT",budget=8,guidance_budget=4,pool_size=32,seed=313)
    empty=plan_knowledge(None,spec,**common);guided=plan_knowledge(frozen,spec,**common)
    changed=[c["inputs"] for c in empty["candidates"]]!=[c["inputs"] for c in guided["candidates"]]
    run=run_source_development(fn,ref,spec,source_provenance=origin,comparison_policy=policy,archive=frozen,
        budget=budget,guidance_budget=min(4,budget//2),pool_size=32,seed=313,known_development_inputs=points,trusted_execution=True)
    if (_sha(target),_sha(oracle))!=(target_hash,oracle_hash):raise ValueError("공개 실행 중 코드가 변경됐습니다")
    return dict(schema="tomolab-semantic-demo-v1",scope="AUTHORED_FUNCTIONAL_FIXTURE_NOT_RESEARCH",archive=frozen,evidence_bundle=evidence.snapshot(),
        exact_and_sufficient={kind:matching[kind] for kind in (EXACT,SUFFICIENT)},selection_changed=changed,
        empty_plan=empty,source_plan=guided,run=run,training_target_calls=12,training_oracle_calls=12,
        target_calls=12+run["target_calls"],oracle_calls=12+run["oracle_calls"],
        actual_primitive_calls=24+run["actual_primitive_calls"],empirical_utility="NOT_ESTABLISHED",
        independent_corroboration="NOT_ESTABLISHED",external_transfer="NOT_EXECUTED_READINESS_BLOCKED")
