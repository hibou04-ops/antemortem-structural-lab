"""Host gate and loader metadata tests: no evaluator source or callback runs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tomolab.discovery.schema import digest
from test_e8_readiness import identity

ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def host():
    return load(ROOT/"scripts/evaluate-e8.py","e8_host_cli_test")


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding="utf-8")
    return path


def test_actual_host_cli_no_ready_never_reads_evaluator_mapping_or_imports(tmp_path):
    result=subprocess.run([sys.executable,"-X","utf8",str(ROOT/"scripts/evaluate-e8.py"),
        "--final-authorized","--allow-local-execution","--evaluators",str(tmp_path/"must-not-read.json")],
        cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert result.returncode==3,result.stderr
    data=json.loads(result.stdout)
    assert data["status"]=="NOT_EXECUTED_READINESS_BLOCKED"
    assert data["target_calls"]==data["oracle_calls"]==data["final_attempts"]==0
    assert data["reason"]=="readiness 조건이 충족되지 않았습니다"


def test_host_gate_preserves_existing_report_without_execution(tmp_path):
    output=tmp_path/"existing.json"; output.write_text("preserved")
    result=subprocess.run([sys.executable,"-X","utf8",str(ROOT/"scripts/evaluate-e8.py"),"--output",str(output)],
        cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert result.returncode==3,result.stderr
    assert json.loads(result.stdout)["report_output_status"]=="EXISTING_FILE_PRESERVED"
    assert output.read_text()=="preserved"


def test_authority_requires_environment_and_rejects_output_alias_root(host,tmp_path,monkeypatch):
    monkeypatch.delenv(host.AUTHORITY_ENV,raising=False)
    assert host._authority(tmp_path/"argument-only")[0] is None
    configured=tmp_path/"canonical-authority"
    monkeypatch.setenv(host.AUTHORITY_ENV,str(configured))
    ledger,authority,error=host._authority(configured)
    assert error is None and ledger.path==configured.resolve()/"FINAL_USAGE.jsonl" and authority==ledger.authority_id
    assert not configured.exists()
    assert host._authority(tmp_path/"output-alias")[0] is None
    monkeypatch.setenv(host.AUTHORITY_ENV,str(ROOT/"bad-public-authority"))
    assert host._authority(None)[0] is None


def test_registry_is_contract_pinned_and_always_injected(host,tmp_path,monkeypatch):
    registry,contract=host._registry()
    lineage=dict(status="REVIEWED",development=[],consumed_targets=[],review_receipt_sha256="a"*64)
    args=host.parser().parse_args(["--bundle",str(save(tmp_path/"bundle.json",{"lineage_review":lineage}))])
    context=host._context(args,registry)
    assert context["lineage_review"]["consumed_targets"]
    assert {digest(r) for r in registry["identities"]}<={digest(r) for r in context["lineage_review"]["consumed_targets"]}
    changed=deepcopy(registry); changed["identities"]=[]
    monkeypatch.setattr(host,"REGISTRY",save(tmp_path/"changed-registry.json",changed))
    with pytest.raises(ValueError,match="pinned E8 contract"):
        host._registry()


@pytest.mark.parametrize("field",list(identity(1)))
def test_registry_blocks_individual_identity_subset_aliases(host,field):
    registry,_=host._registry(); fresh=identity(7)
    fresh[field]=registry["identities"][0][field]
    target=dict(identity=fresh,provenance={"project":"approved-project"},scope="REVIEWED_REAL_PROJECT")
    with pytest.raises(ValueError,match="individually consumed"):
        host._target_exclusions({"targets":[target]},registry)


def test_lab_project_cannot_be_real_research_target(host):
    registry,_=host._registry()
    target=dict(identity=identity(7),provenance={"project":"antemortem-structural-lab"},scope="REVIEWED_REAL_PROJECT")
    with pytest.raises(ValueError,match="lab project"):
        host._target_exclusions({"targets":[target]},registry)


@pytest.mark.parametrize("flags",[[],["--final-authorized"],["--allow-local-execution"]])
def test_both_execution_flags_required_even_after_a_stub_readiness_pass(host,tmp_path,monkeypatch,flags):
    class Ready:
        def __init__(self,**kwargs): pass
        def authorize_final_comparison(self): return {"status":"PASS","blockers":[]}
    monkeypatch.setattr(host,"EvaluationReadiness",Ready)
    monkeypatch.setenv(host.AUTHORITY_ENV,str(tmp_path/"test-authority"))
    def forbidden(*args,**kwargs): raise AssertionError("execution metadata was reached before both flags")
    monkeypatch.setattr(host,"_verify_execution_contract",forbidden)
    result,code=host.execute(host.parser().parse_args(flags))
    assert code==3 and result["target_calls"]==result["oracle_calls"]==0
    assert "READINESS_BLOCKED_HOST_AUTHORIZATION" in result["blockers"]


def mapping_data(host,tmp_path,number=1):
    targets=[]; entries=[]
    for index in range(number):
        target=tmp_path/f"target-{index}.py"; oracle=tmp_path/f"oracle-{index}.py"
        # Importing either would fail. Loader tests use metadata-only stubs.
        target.write_text("raise RuntimeError('DO_NOT_IMPORT_AUTHORED_TEST_SOURCE')\n")
        oracle.write_text("raise RuntimeError('DO_NOT_IMPORT_AUTHORED_TEST_ORACLE')\n")
        t_hash,o_hash=host._sha(target),host._sha(oracle)
        tid="target-"+str(index)
        targets.append(dict(target_id=tid,provenance=dict(implementation_sha256=t_hash,oracle_sha256=o_hash)))
        entries.append(dict(target_id=tid,target=dict(path=target.name,function="implementation",file_sha256=t_hash),
                            oracle=dict(path=oracle.name,function="reference",file_sha256=o_hash)))
    value=dict(schema="tomolab-e8-evaluator-mapping-v1",entries=entries)
    value["receipt_sha256"]=digest(value)
    path=save(tmp_path/"mapping.json",value)
    return path,value,targets


def test_loader_checks_all_file_pins_before_any_import_request(host,tmp_path):
    path,value,targets=mapping_data(host,tmp_path,2)
    value["entries"][1]["oracle"]["file_sha256"]="0"*64
    value["receipt_sha256"]=digest({k:v for k,v in value.items() if k!="receipt_sha256"}); save(path,value)
    calls=[]
    with pytest.raises(ValueError,match="file differs"):
        host._load_evaluators(path,host._sha(path),targets,loader=lambda *a:calls.append(a))
    assert calls==[]


def test_mapping_function_alias_cannot_change_under_frozen_mapping_hash(host,tmp_path):
    path,value,targets=mapping_data(host,tmp_path)
    pinned=host._sha(path)
    value["entries"][0]["target"]["function"]="renamed"
    value["receipt_sha256"]=digest({k:v for k,v in value.items() if k!="receipt_sha256"}); save(path,value)
    with pytest.raises(ValueError,match="frozen protocol"):
        host._load_evaluators(path,pinned,targets,loader=lambda *a:(_ for _ in ()).throw(AssertionError("import reached")))


def test_loader_routes_pinned_callables_without_invoking_them(host,tmp_path):
    path,_,targets=mapping_data(host,tmp_path)
    import_requests=[]; callback_requests=[]
    def loader(source,function):
        import_requests.append((source,function))
        def callback(**point): callback_requests.append(point); raise AssertionError("callback invoked")
        return callback,host._sha(source)
    values=host._load_evaluators(path,host._sha(path),targets,loader=loader)
    assert set(values)=={"target-0"} and len(import_requests)==2 and callback_requests==[]


def test_loader_detects_file_drift_after_stub_imports_without_callback_execution(host,tmp_path):
    path,_,targets=mapping_data(host,tmp_path)
    count=[]
    def loader(source,function):
        count.append(1); expected=host._sha(source)
        if len(count)==2:
            (tmp_path/"target-0.py").write_text("changed but never executed")
        return lambda **point:(_ for _ in ()).throw(AssertionError("callback invoked")),expected
    with pytest.raises(ValueError,match="changed while modules"):
        host._load_evaluators(path,host._sha(path),targets,loader=loader)


def test_host_and_ci_freeze_file_sets_are_exactly_equal(host):
    checker=load(ROOT/"scripts/check-e8-freeze.py","e8_freeze_file_set_test")
    assert host.required_frozen_files(ROOT)==checker.expected_files(ROOT)


def test_host_current_code_freeze_verifies_complete_set_and_detects_drift(host,tmp_path,monkeypatch):
    product_root=tmp_path/"data-only-product"
    product_root.mkdir(); (product_root/"tomolab").mkdir()
    for name in host.required_frozen_files(product_root):
        path=product_root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text("fixture")
    (product_root/"pyproject.toml").write_text('[project]\nversion="0.8.0a1"\n')
    product={name:host._sha(product_root/name) for name in host.required_frozen_files(product_root)}
    freeze=save(product_root/"docs/E8_CODE_FREEZE.json",dict(schema="tomolab-e8-code-freeze-v1",version="0.8.0a1",
        scope="IMPLEMENTATION_BYTES_NOT_RESEARCH_VERDICT",product_files=len(product),product=product))
    protocol=dict(product_hashes={name:host._sha(product_root/name) for name in
        ("scripts/evaluate-e8.py","docs/E8_CONSUMED_IDENTITIES.json","docs/E8_EVALUATION_CONTRACT.json","docs/E8_CODE_FREEZE.json")},
        evaluator_mapping_sha256="a"*64)
    context=dict(fixed_protocol=protocol,targets=[])
    registry=dict(identities=[identity(1)],excluded_research_target_projects=["antemortem-structural-lab"])
    monkeypatch.setattr(host,"ROOT",product_root); monkeypatch.setattr(host,"FREEZE",freeze)
    host._verify_execution_contract(context,registry,{})
    (product_root/"scripts/check-wheel.py").write_text("changed")
    with pytest.raises(ValueError,match="frozen code changed"):
        host._verify_execution_contract(context,registry,{})
