"""Verify the public E6 code commitment before any release side effect."""
import hashlib
import json
from pathlib import Path, PurePosixPath

SCHEMA = "tomolab-e6-code-freeze-v1"


def verify(root, manifest):
    root = Path(root).resolve()
    if set(manifest)!={"schema","version","product_files","product"} or manifest["schema"]!=SCHEMA or manifest["version"]!="0.6.0a1":
        raise ValueError("unsupported E6 code commitment")
    product = manifest["product"]
    if not isinstance(product,dict) or not product or manifest["product_files"]!=len(product):
        raise ValueError("invalid product file commitment")
    for name,expected in product.items():
        relative = PurePosixPath(name)
        path = (root/name).resolve()
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
            raise ValueError("committed product path must stay inside the checkout")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError("E6 evaluated product bytes drifted: "+name)
    return {"status":"PASS","product_files":len(product),"version":manifest["version"]}


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/"docs/E6_CODE_FREEZE.json").read_text(encoding="utf-8"))
    print(json.dumps(verify(root,manifest),indent=2))


if __name__=="__main__":
    main()
