"""Reviewed local CORR commands; source scope and final readiness stay separate."""
import json
from pathlib import Path

COMMANDS = ("corroboration-inspect", "corroboration-plan", "corroboration-approve",
            "corroboration-run", "corroboration-demo")
IMPLEMENTATIONS = ("python-statistics-correlation", "scipy-stats-pearsonr")


def register(commands):
    for name in COMMANDS:
        parser = commands.add_parser(name, help="검토된 로컬 CORR 개발 검사; FINAL_TARGET·발행 승인 아님")
        parser.add_argument("--output", type=Path, required=True)
        if name in ("corroboration-inspect", "corroboration-approve", "corroboration-demo"):
            parser.add_argument("--implementation", choices=IMPLEMENTATIONS, default=IMPLEMENTATIONS[0])
        if name in ("corroboration-plan", "corroboration-demo"):
            parser.add_argument("--method", choices=("A","B","C","D"), default="B")
            parser.add_argument("--seed", type=int, default=7)
            parser.add_argument("--size", type=int, default=4)
            parser.add_argument("--max-examples", type=int, default=128)
            parser.add_argument("--known-inputs", type=Path)
            parser.add_argument("--replays", type=Path)
        if name == "corroboration-plan":
            parser.add_argument("--prepared-dir", type=Path)
            parser.add_argument("--source-approval-state", type=Path)
            parser.add_argument("--expected-digest")
        if name in ("corroboration-approve", "corroboration-run"):
            parser.add_argument("--plan", type=Path, required=True)
            parser.add_argument("--approval-state", type=Path, required=True)
            parser.add_argument("--usage-ledger", type=Path, required=True)
            parser.add_argument("--authority-id", required=True)
        if name == "corroboration-approve":
            parser.add_argument("--guide-digest", required=True)
            parser.add_argument("--review-digest", required=True)
        if name in ("corroboration-approve", "corroboration-demo"):
            parser.add_argument("--budget", type=int, default=16)
            parser.add_argument("--shrink-budget", type=int, default=0)
        if name == "corroboration-run":
            parser.add_argument("--permit", type=Path, required=True)
        if name in ("corroboration-run", "corroboration-demo"):
            parser.add_argument("--allow-local-execution", action="store_true")
        if name == "corroboration-demo":
            parser.add_argument("--workspace", type=Path, required=True,
                help="새 로컬 기능 검사용 경로; 연구 배치나 미소비 FINAL로 재등록하지 않음")


def _read(path):
    from .discovery.numerical_prepared import _read_small
    return _read_small(path)


def _write(path, value):
    from .discovery.numerical_prepared import _write_new
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    return _write_new(path,value)


def dispatch(args, parser, examples):
    from .discovery.corroboration_adapters import (implementation_identity,
        implementation_location, adapter_identity, oracle_identity)
    from .discovery.corroboration_service import plan_candidates, run_corroboration_plan
    from .discovery.corroboration_permit import (build_permit_context, CorroborationExecutionPermit)
    from .discovery.evaluation_usage import UsageLedger
    from .discovery.numerical_guidance import numerical_input_digest, public_input_contract
    from .discovery.numerical_prepared import load_prepared_guide, read_approval_state
    from .discovery.schema import digest
    if args.output.exists() or Path(str(args.output)+".io.json").exists():
        raise FileExistsError("CORR output receipts must be new")
    if args.command == "corroboration-inspect":
        return dict(schema="tomolab-corroboration-inspection-v1",status="COMPLETE",execution="NOT_EXECUTED",
            implementation=implementation_identity(args.implementation),local_only_location=implementation_location(args.implementation),
            adapter=adapter_identity(),oracle=oracle_identity(),target_calls=0,oracle_calls=0,allow_release=False)
    if args.command == "corroboration-approve":
        plan = _read(args.plan)
        context = build_permit_context(plan,implementation_identity(args.implementation),
            common_input_contract=public_input_contract(),
            resource_budget=dict(pair_budget=args.budget,shrink_budget=args.shrink_budget),
            authority_id=args.authority_id,guide_digest=args.guide_digest,review_digest=args.review_digest)
        if args.approval_state.resolve() in (args.output.resolve(),args.plan.resolve()):
            raise ValueError("external trusted host approval state must have a separate path")
        permit = CorroborationExecutionPermit.from_host_approval(context,context)
        _write(args.approval_state,context)
        return dict(schema="tomolab-corroboration-host-approval-v1",status="COMPLETE",context=permit.context,
            permit_digest=permit.permit_digest,authority="EXPLICIT_TRUSTED_HOST_COMMAND_NOT_A_SELF_AUTHENTICATING_HASH",
            target_calls=0,oracle_calls=0,allow_release=False)
    if args.command in ("corroboration-plan","corroboration-demo"):
        known = _read(args.known_inputs) if args.known_inputs else []
        replay = _read(args.replays) if args.replays else []
        if not isinstance(known,list) or not isinstance(replay,list):
            raise ValueError("bounded input-only known and replay lists required")
        if args.method == "C" and not replay:
            parser.error("METHOD_C에는 --replays로 같은 승인 Source 반례가 필요합니다")
        compiled, expected = None, None
        if args.method == "D":
            if args.command == "corroboration-demo":
                folder = examples/"numerical"
                expected = (folder/"source-guide.sha256").read_text(encoding="ascii").strip()
                compiled = dict(artifact=_read(folder/"source-guide.json"),approval_receipt=_read(folder/"source-approval.json"))
            else:
                if not all((args.prepared_dir,args.source_approval_state,args.expected_digest)):
                    parser.error("D에는 --prepared-dir, --source-approval-state, --expected-digest가 필요합니다")
                loaded = load_prepared_guide(args.prepared_dir,expected_digest=args.expected_digest,
                    expected_current_context=read_approval_state(args.source_approval_state))
                compiled, expected = loaded["compiled"],args.expected_digest
        elif args.command == "corroboration-plan" and any((args.prepared_dir,args.source_approval_state,args.expected_digest)):
            parser.error("A/B/C는 D 가이드·승인을 읽지 않습니다")
        plan = plan_candidates(method=args.method,seed=args.seed,size=args.size,max_examples=args.max_examples,
            compiled=compiled,expected_digest=expected,
            replay_inputs=replay if args.method == "C" else (),
            excluded_digests=[item if isinstance(item,str) else numerical_input_digest(item) for item in known])
        if args.command == "corroboration-plan":
            return plan
    if args.command in ("corroboration-run","corroboration-demo"):
        if not args.allow_local_execution:
            parser.error("CORR 로컬 실행에는 --allow-local-execution이 필요합니다")
        if args.command == "corroboration-demo":
            args.workspace.mkdir(parents=True,exist_ok=False)
            # Public functional example, explicitly consumed as CORR. This
            # command never measures the private registered research batch.
            authority = digest(dict(scope="AUTHORED_CORR_FUNCTIONAL_NOT_RESEARCH",workspace=str(args.workspace.resolve())))
            ledger = UsageLedger(args.workspace/"usage.jsonl",authority_id=authority)
            pin = (examples/"numerical/source-guide.sha256").read_text(encoding="ascii").strip()
            context = build_permit_context(plan,implementation_identity(args.implementation),
                common_input_contract=public_input_contract(),
                resource_budget=dict(pair_budget=args.budget,shrink_budget=args.shrink_budget),
                authority_id=authority,guide_digest=pin,
                review_digest=digest(dict(review="EXPLICIT_PUBLIC_FUNCTIONAL_LIBRARY_CONTRACT_NOT_QUALIFIED_EVIDENCE")))
            permit = CorroborationExecutionPermit.from_host_approval(context,context)
            _write(args.workspace/"plan.json",plan)
            _write(args.workspace/"host-approval.json",context)
        else:
            plan = _read(args.plan)
            approved = _read(args.permit)
            context = read_approval_state(args.approval_state)
            permit = CorroborationExecutionPermit.from_host_approval(approved["context"],context)
            if approved["permit_digest"] != permit.permit_digest:
                raise PermissionError("CORR permit file differs from its approved digest")
            ledger = UsageLedger(args.usage_ledger,authority_id=args.authority_id)
        permit.validate(context,plan=plan)
        start = ledger.claim_corroboration([permit],[context],output=args.output)
        run = run_corroboration_plan(plan,permit,expected_approval_context=context,usage_ledger=ledger,claim_id=start["claim_id"])
        ledger.complete(start["claim_id"],dict(scope="INDEPENDENT_DEVELOPMENT_ONLY",status=run["status"],receipt_sha256=run["receipt_sha256"]))
        return dict(schema="tomolab-corroboration-cli-execution-v1",status=run["status"],run=run,
            usage_scope="COOPERATIVE_FIXED_LOCAL_AUTHORITY_NOT_GLOBAL_CONSUMPTION_REGISTRY",
            final_target_eligible=False,allow_release=False)
    raise ValueError("unsupported CORR command")
