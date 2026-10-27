"""Actual E7 CLI and parent-side information-boundary integration."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT/"examples/knowledge"


def run(*args):
    result = subprocess.run([sys.executable,"-X","utf8","-m","tomolab",*args],cwd=ROOT,
                            capture_output=True,text=True,encoding="utf-8",timeout=45)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def test_actual_log_to_durable_archive_frozen_plan_and_renamed_execution(tmp_path):
    archive = tmp_path/"archive.json"
    store = tmp_path/"archive.jsonl"
    args = ("knowledge-learn","--spec",str(EXAMPLES/"source-spec.json"),
        "--failure-log",str(EXAMPLES/"source-failures.json"),"--provenance",str(EXAMPLES/"source-provenance.json"),
        "--public-ir",str(EXAMPLES/"source-ir.json"),"--observations",str(EXAMPLES/"observations.json"),
        "--approve-development-evidence","--store",str(store),"--record-id","functional-1","--output",str(archive))
    run(*args)
    original = store.read_bytes()
    run(*args)
    assert store.read_bytes() == original
    plan = run("knowledge-plan","--archive",str(archive),"--spec",str(EXAMPLES/"target-spec.json"),
        "--target-provenance",str(EXAMPLES/"target-provenance.json"),"--public-ir",str(EXAMPLES/"target-ir.json"),
        "--budget","8","--guidance-budget","4","--pool-size","16")
    assert plan["snapshot"]["frozen"] and plan["final_feedback_allowed"] is False
    assert plan["oracle_calls"] == plan["target_calls"] == 0
    assert plan["gate"]["status"] == "QUALIFIED_FOR_PROBING"
    assert sum(p["source"] == "NATIVE_HYPOTHESIS" for p in plan["candidates"]) >= 4
    from tomolab.mold.service import _load
    fn,_ = _load(EXAMPLES/"target.py","implementation")
    ref,_ = _load(EXAMPLES/"target_oracle.py","reference")
    assert any(fn(**p["inputs"]) != ref(**p["inputs"]) for p in plan["candidates"])
    updated = tmp_path/"updated.json"
    run("knowledge-update","--archive",str(archive),"--observations",str(EXAMPLES/"counterevidence.json"),
        "--generation-id","new-development","--approve-development-evidence","--store",str(store),
        "--record-id","functional-2","--output",str(updated))
    assert store.read_bytes().startswith(original)
    before = json.loads(archive.read_text(encoding="utf-8"))
    after = json.loads(updated.read_text(encoding="utf-8"))
    assert before["frozen"] and after["frozen"]
    assert after["journal"][:len(before["journal"])] == before["journal"]
    assert not any(c["status"] == "SUPPORTED_WITHIN_SCOPE" for c in after["claims"])


def test_actual_qualified_learning_and_refutation_fallback():
    result = run("knowledge-demo","--budget","16","--guidance-budget","4","--pool-size","16","--shrink-budget","16")
    assert result["status"] == "COUNTEREXAMPLE_FOUND" and result["snapshot"]["frozen"]
    assert result["counterexample"]["replay"] == "MATCHED_TWICE"
    assert result["metrics"]["guided_prefix_calls"] > 0
    cold = run("knowledge-demo","--case","contradicted","--budget","12","--pool-size","8","--shrink-budget","8")
    assert cold["metrics"]["guided_prefix_calls"] == 0 and cold["backend"] == "native-direct"
    assert any(c["status"] == "CONTRADICTED" for c in cold["knowledge_archive"]["claims"])
    clean = run("knowledge-demo","--case","clean","--budget","12","--guidance-budget","4","--pool-size","8","--shrink-budget","0")
    assert clean["status"] == "NOT_REFUTED_WITHIN_BUDGET"
    assert clean["snapshot"]["metrics"]["refuted_claims"] > 0


class WriteSpy:
    called = False
    def write(self, value):
        self.called = True
        raise AssertionError("invalid evidence reached transport")


def parent():
    from tomolab.discovery.knowledge_boundary import KnowledgeBoundary
    boundary = object.__new__(KnowledgeBoundary)
    boundary._request_lock = threading.Lock()
    boundary._spec = json.loads((EXAMPLES/"target-spec.json").read_text(encoding="utf-8"))
    boundary._temporal_contract = None
    boundary._target_provenance = json.loads((EXAMPLES/"target-provenance.json").read_text(encoding="utf-8"))
    boundary._frozen = False
    spy = WriteSpy()
    boundary.process = SimpleNamespace(stdin=spy)
    return boundary, spy


def test_forbidden_raw_and_final_information_rejected_before_transport():
    boundary, spy = parent()
    with pytest.raises(ValueError):
        boundary.request("init",spec=boundary._spec,oracle_source="PRIVATE_RAW")
    for key in ("actual_state","expected_state","model_score","final_answers"):
        with pytest.raises(ValueError):
            boundary.request("observe",evidence={key:"forbidden"})
    event = json.loads((EXAMPLES/"observations.json").read_text(encoding="utf-8"))[0]
    from tomolab.discovery.schema import digest
    event["split"] = "final"
    event["receipt_sha256"] = digest({k:v for k,v in event.items() if k != "receipt_sha256"})
    with pytest.raises(ValueError,match="final"):
        boundary.request("observe",evidence=event)
    assert not spy.called


def test_frozen_parent_blocks_even_empty_feedback_before_pipe():
    boundary, spy = parent()
    boundary._frozen = True
    with pytest.raises(ValueError,match="frozen"):
        boundary.request("observe",evidence={})
    assert not spy.called


def test_untrusted_cli_files_not_imported_on_invalid_configuration(tmp_path):
    marker = tmp_path/"executed"
    target = tmp_path/"target.py"
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef implementation(left,right): return 0\n",encoding="utf-8")
    result = subprocess.run([sys.executable,"-X","utf8","-m","tomolab","knowledge-run",str(target),
        "--oracle-file",str(EXAMPLES/"target_oracle.py"),"--spec",str(EXAMPLES/"target-spec.json"),
        "--target-provenance",str(EXAMPLES/"target-provenance.json"),"--allow-local-execution"],
        cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
    assert result.returncode != 0 and not marker.exists()
    assert "provenance differs" in result.stderr


def test_allowlist_excludes_host_execution_and_storage():
    from tomolab.discovery.knowledge_boundary import GENERATOR_FILES
    assert {"knowledge.py","knowledge_engine.py","knowledge_worker.py"} <= set(GENERATOR_FILES)
    assert not {"knowledge_store.py","knowledge_service.py","knowledge_examples.py","native_stateful.py","analysis.py"} & set(GENERATOR_FILES)


def test_packaged_public_model_ir_matches_current_python_contract():
    from tomolab.discovery.knowledge_examples import example_ir, example_spec
    spec = example_spec(("left","right"),folder=EXAMPLES)
    bundled = json.loads((EXAMPLES/"target-spec.json").read_text(encoding="utf-8"))
    assert spec == bundled
    assert example_ir(EXAMPLES,("left","right"))["graph_signature"] == bundled["contract"]["graph_signature"]


def test_mutable_caller_cannot_bypass_archive_validation(monkeypatch):
    from tomolab.discovery.knowledge import KnowledgeArchive
    from tomolab.discovery.knowledge_protocol import validate_request
    from tomolab.discovery.knowledge_examples import build_example_archive
    valid,_ = build_example_archive(EXAMPLES)
    import copy
    message = {"action":"init","spec":valid["spec"],"archive":copy.deepcopy(valid)}
    message["archive"]["raw_private_output"] = "PUBLIC_AUDIT_MARKER"
    original = KnowledgeArchive.from_snapshot
    def race(cls, captured):
        message["archive"].clear();message["archive"].update(copy.deepcopy(valid))
        return original(captured)
    monkeypatch.setattr(KnowledgeArchive,"from_snapshot",classmethod(race))
    with pytest.raises(ValueError):
        validate_request(message)
