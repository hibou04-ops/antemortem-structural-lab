"""Explicit bounded metadata collection. External execution is a separate gate."""
import json
from pathlib import Path

COMMANDS = {"harvest-run", "harvest-demo", "harvest-review", "harvest-learn", "harvest-m0"}


def register(commands):
    run = commands.add_parser("harvest-run",help="Collect bounded public GitHub candidates and write a review queue")
    run.add_argument("--workspace",type=Path,required=True)
    run.add_argument("--repositories",nargs="+")
    run.add_argument("--max-candidates",type=int,default=50)
    run.add_argument("--max-details",type=int,default=10)
    run.add_argument("--max-qualifications",type=int,default=4)
    run.add_argument("--output",type=Path)
    demo = commands.add_parser("harvest-demo",help="Authored pipeline and recursive-generation fixture; no external code")
    demo.add_argument("--workspace",type=Path,required=True)
    demo.add_argument("--allow-local-execution",action="store_true")
    demo.add_argument("--output",type=Path)
    review = commands.add_parser("harvest-review",help="Apply an explicit, identity-bound host review to a registered candidate")
    review.add_argument("--workspace",type=Path,required=True)
    review.add_argument("--candidate-id",required=True)
    review.add_argument("--review",type=Path,required=True)
    review.add_argument("--execution-receipt",type=Path)
    review.add_argument("--allow-reviewed-development",action="store_true")
    review.add_argument("--output",type=Path)
    learn = commands.add_parser("harvest-learn",help="Consume qualified paired development receipts into the existing generation store")
    learn.add_argument("--workspace",type=Path,required=True)
    learn.add_argument("--candidate-ids",nargs="+",required=True)
    learn.add_argument("--manifest",type=Path,required=True)
    learn.add_argument("--receipts",type=Path,required=True)
    learn.add_argument("--generation-store",type=Path,required=True)
    learn.add_argument("--generation-id",required=True)
    learn.add_argument("--allow-reviewed-development",action="store_true")
    learn.add_argument("--output",type=Path)
    m0 = commands.add_parser("harvest-m0",help="Run only frozen reviewed development cases through the inspected OCI boundary")
    m0.add_argument("--workspace",type=Path,required=True)
    m0.add_argument("--execution-contract",type=Path,required=True)
    m0.add_argument("--allow-external-execution",action="store_true")
    m0.add_argument("--output",type=Path)


def dispatch(args):
    if args.command == "harvest-run":
        from .discovery.harvester_service import run_harvest
        result = run_harvest(args.workspace,repositories=args.repositories,max_candidates=args.max_candidates,
            max_details=args.max_details,max_qualifications=args.max_qualifications)
    elif args.command == "harvest-demo":
        if not args.allow_local_execution:
            raise PermissionError("authored fixture requires --allow-local-execution")
        from .harvester_demo import run_demo
        result = run_demo(args.workspace)
    else:
        from .discovery.harvester_learning import review_candidate, learn_from_harvest, run_harvest_m0
        def load(path):
            return json.loads(path.read_text(encoding="utf-8"))
        if args.command == "harvest-review":
            result = review_candidate(args.workspace,args.candidate_id,load(args.review),
                execution_receipt=load(args.execution_receipt) if args.execution_receipt else None,
                allow_reviewed_development=args.allow_reviewed_development)
        elif args.command == "harvest-learn":
            result = learn_from_harvest(args.workspace,args.candidate_ids,load(args.receipts),load(args.manifest),
                args.generation_store,generation_id=args.generation_id,
                allow_reviewed_development=args.allow_reviewed_development)
        else:
            result = run_harvest_m0(args.workspace,load(args.execution_contract),
                allow_external_execution=args.allow_external_execution)
    if args.output is not None:
        from .discovery.harvester_service import save_new
        save_new(args.output,result)
    return result
