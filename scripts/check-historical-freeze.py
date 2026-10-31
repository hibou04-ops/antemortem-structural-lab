"""Verify an existing commitment at its original Git revision, without rebasing hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def verify(root, revision, manifest_path, allowed_test_changes=()):
    def original(path):
        return subprocess.check_output(["git", "show", revision+":"+path], cwd=root)
    raw = original(manifest_path)
    if (root/manifest_path).read_bytes() != raw:
        raise ValueError("historical commitment was rewritten")
    manifest = json.loads(raw)
    product = manifest.get("product", manifest.get("code_files"))
    if not isinstance(product, dict) or manifest.get("product_files", len(product)) != len(product):
        raise ValueError("historical inventory length differs")
    for name, expected in product.items():
        if hashlib.sha256(original(name)).hexdigest() != expected:
            raise ValueError("historical blob differs: "+name)
    tests = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision, "tests"], cwd=root).decode().splitlines()
    for name in tests:
        if name not in allowed_test_changes and (root/name).read_bytes() != original(name):
            raise ValueError("historical regression contract changed: "+name)
    return dict(status="PASS", revision=revision, manifest=manifest_path,
                historical_files=len(product), regression_files_preserved=len(tests)-len(allowed_test_changes),
                explicitly_replaced_current_tests=list(allowed_test_changes),
                current_code_compared_as_historical=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--allow-current-test-change", action="append", default=[])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--current', action='store_true', help='verify a separate current registration without executing research')
    parser.add_argument('--if-present', action='store_true')
    args = parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if args.current:
        path=root/args.manifest
        if not path.is_file() and args.if_present:
            receipt=dict(status='NOT_YET_REGISTERED',manifest=args.manifest,target_calls=0,oracle_calls=0)
        else:
            import sys
            sys.path.insert(0,str(root))
            from tomolab.discovery.schema import digest
            record=json.loads(path.read_text(encoding='utf-8'))
            payload={key:value for key,value in record.items() if key!='registration_digest'}
            if digest(payload)!=record.get('registration_digest'):
                raise ValueError('current registration commitment differs')
            files=record['code_files']
            if not 1<=len(files)<=256:raise ValueError('bounded frozen inventory required')
            for name,expected in files.items():
                source=(root/name).resolve(strict=True)
                if not source.is_relative_to(root) or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
                    raise ValueError('current registered code changed: '+name)
            receipt=dict(status='PASS',manifest=args.manifest,historical_files=len(files),target_calls=0,oracle_calls=0)
    else:
        if not args.revision:parser.error('--revision is required for historical verification')
        receipt = verify(root, args.revision, args.manifest, args.allow_current_test_change)
    if args.output:
        args.output.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))
