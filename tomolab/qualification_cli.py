"""Explicit development probes and read-only scope audit; no default research run."""
import json
from pathlib import Path

COMMANDS={"structural-probe","transfer-audit"}

def register(commands):
    probe=commands.add_parser("structural-probe",help="Run four exposed authored relational development fixtures")
    probe.add_argument("--workspace",type=Path,required=True)
    probe.add_argument("--seed",type=int,default=47)
    probe.add_argument("--budget",type=int,default=24)
    probe.add_argument("--allow-local-execution",action="store_true")
    audit=commands.add_parser("transfer-audit",help="Audit declared evidence scope without running a target or changing a generation")
    audit.add_argument("--manifest",type=Path,required=True)
    audit.add_argument("--output",type=Path)
    audit.add_argument("--allow-reviewed-evidence",action="store_true")

def dispatch(args):
    if args.command=="structural-probe":
        from .structural_probe import run_probe
        return run_probe(args.workspace,allow_local_execution=args.allow_local_execution,seed=args.seed,budget=args.budget)
    from .discovery.transfer_audit import audit_transfer_scope
    from .discovery.harvester_service import save_new
    path=args.manifest
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024*1024:
        raise ValueError("bounded regular data-only audit manifest required")
    manifest=json.loads(path.read_bytes())
    allowed={"claim_scope","source_cases","evaluation_cases","paired_receipts","generation_store","generation_id","qualification_evidence"}
    if type(manifest) is not dict or set(manifest)-allowed or not {"claim_scope","source_cases","evaluation_cases"}<=manifest.keys():
        raise ValueError("strict evidence-scope manifest required")
    result=audit_transfer_scope(**manifest,trusted_review=args.allow_reviewed_evidence)
    if args.output is not None:save_new(args.output,result)
    return result
