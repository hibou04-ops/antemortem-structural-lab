"""Run only the explicit first-party OCI boundary control probe."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tomolab.discovery.oci_probe import run_oci_probe


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image",required=True,help="Existing reviewed sha256 image ID; no pull")
    parser.add_argument("--workspace",type=Path,required=True)
    parser.add_argument("--allow-container-execution",action="store_true")
    args=parser.parse_args(argv)
    receipt=run_oci_probe(args.workspace,image=args.image,allow_container_execution=args.allow_container_execution)
    print(json.dumps(dict(status=receipt["status"],receipt_sha256=receipt["receipt_sha256"],
        external_target_calls=receipt["external_target_calls"],external_oracle_calls=receipt["external_oracle_calls"],
        control_entries=receipt["control_entries"],cleanup=receipt["cleanup"]["status"],reasons=receipt["reasons"]),sort_keys=True))
    return 0 if receipt["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
