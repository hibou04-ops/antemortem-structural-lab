"""Plan or explicitly run the one exposed public palindrome regression."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tomolab.discovery.real_qualification import run_public_qualification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--image", required=True, help="Reviewed local image identity sha256:<64 lowercase hex>")
    parser.add_argument("--allow-external-execution", action="store_true", help="Accept the fixed bounded review and authorize exactly one public regression run after the separate OCI control gate")
    args = parser.parse_args()
    result = run_public_qualification(args.workspace, image=args.image, allow_external_execution=args.allow_external_execution)
    print(json.dumps(result["summary"], sort_keys=True, ensure_ascii=True))
    return 0 if result["summary"]["status"] == "REPRODUCED" or not args.allow_external_execution else 2


if __name__ == "__main__":
    raise SystemExit(main())
