"""Explicit, bounded sequence-only OCI qualification entrypoint."""
import argparse
import json
from pathlib import Path

from tomolab.discovery.sequence_qualification import run_sequence_qualification


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",required=True)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--image",required=True)
    parser.add_argument("--source-cache",help="Frozen content-addressed source data; no network fallback")
    parser.add_argument("--allow-external-execution",action="store_true")
    parser.add_argument("--allow-reviewed-development",action="store_true")
    args=parser.parse_args()
    raw=Path(args.manifest).read_bytes()
    if len(raw)>512*1024:raise ValueError("bounded reviewed manifest required")
    manifest=json.loads(raw)
    result=run_sequence_qualification(args.workspace,manifest=manifest,image=args.image,
        allow_external_execution=args.allow_external_execution,trusted_review=args.allow_reviewed_development,source_cache=args.source_cache)
    print(json.dumps(result["summary"],ensure_ascii=True,sort_keys=True))
    return 0 if not args.allow_external_execution or result["summary"]["status"]=="REPRODUCED" else 1


if __name__=="__main__":raise SystemExit(main())
