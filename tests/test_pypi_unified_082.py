"""Publication identity and authored demonstration keep their actual boundaries."""
import importlib.util
from pathlib import Path

import pytest

from tomolab import quickstart_demo


ROOT = Path(__file__).resolve().parents[1]


def test_current_stable_metadata_has_explicit_product_only_authority():
    spec = importlib.util.spec_from_file_location("unified_release", ROOT / "scripts/check-product-release.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert gate.static_checks(ROOT)["version"] == "0.8.2"
    checkpoint = gate.source_checkpoint_checks(ROOT)
    assert checkpoint["version"] == "0.8.2"
    assert checkpoint["frozen_publication_version"] == "0.8.0a1"
    assert checkpoint["publication_authorized"] is False


def test_authored_demo_cannot_claim_a_failure_when_comparison_passes(monkeypatch):
    original = quickstart_demo.observe
    monkeypatch.setattr(quickstart_demo, "observe", lambda target, oracle, point, contract: original(oracle, oracle, point, contract))
    with pytest.raises(RuntimeError, match="failure was not reproduced"):
        quickstart_demo.main()
