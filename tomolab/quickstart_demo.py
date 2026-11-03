"""Replay an authored defect and its repair using the real offline comparator.

This finite fixture is not a search result or a proof about external programs.
"""
from .discovery.online_observe import observe


def broken(point):
    return point + 1 if point == 0 else point


def reference(point):
    return point


def main():
    contract = {"kind": "int", "low": -8, "high": 8}
    failures = [observe(broken, reference, 0, contract) for _ in range(3)]
    if any(row["feedback"]["status"] != "FAILURE" for row in failures):
        raise RuntimeError("the authored failure was not reproduced three times")
    if len({row["semantic_digest"] for row in failures}) != 1:
        raise RuntimeError("replayed observations differ")
    fixed = observe(reference, reference, 0, contract)
    if fixed["feedback"]["status"] != "PASS":
        raise RuntimeError("the authored repair did not pass its explicit contract")
    failed = failures[0]["private_outcome"]
    actual = failed["actual"]["value"]["value"]
    expected = failed["expected"]["value"]["value"]
    repaired = fixed["private_outcome"]
    print(f"[COUNTEREXAMPLE] point=0 actual={actual} expected={expected} confirmations={len(failures)}")
    print(f"[PASS] fixed point=0 actual={repaired['actual']['value']['value']} expected={repaired['expected']['value']['value']}")
    print(f"[PASS] replay matched all {len(failures)} failure observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
