"""Static historical registration and local independent Oracles; no upstream execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

from benchmarks import historical


def test_catalog_registers_real_projects_roles_and_disjoint_original_functions():
    before=set(sys.modules)
    cases=historical.cases(load=False)
    assert len(cases)==14
    assert {role:sum(case.role==role for case in cases) for role in ('SOURCE','TARGET','CONTROL')}=={
        'SOURCE':2,'TARGET':6,'CONTROL':6}
    assert len({case.entry['project'] for case in cases})==3
    assert all(case.target is None and case.upstream is None and case.oracle is None for case in cases)
    assert not any(name.startswith('_reviewed_historical_') for name in set(sys.modules)-before)
    source={case.lineage for case in cases if case.role=='SOURCE'}
    target={case.lineage for case in cases if case.role=='TARGET'}
    assert not source & target
    assert len(target)==6
    for case in cases:
        metadata=case.metadata()
        assert metadata['implementation_lineage']==case.lineage
        assert metadata['input_kind']==case.contract['kind']
        assert metadata['fixed_is_independent_implementation'] is False
        assert metadata['adapter_mri_scope']==('UNSUPPORTED_CLASS_EXPLICIT_BLACK_BOX'
            if case.entry['adapter']=='bucket' else 'REVIEWED_ORIGINAL_AST_ROOT_LINES_ARGUMENT_MAPPING_UNKNOWN')


def test_fixed_controls_remain_same_function_controls_not_independent_implementations():
    cases={case.id:case for case in historical.cases()}
    for case in list(cases.values()):
        if case.role!='TARGET':
            continue
        control=cases[case.id+'-fixed-control']
        left,right=case.metadata(),control.metadata()
        assert left['control_group']==right['control_group']
        assert left['identity']['cross_revision_function_key']==right['identity']['cross_revision_function_key']
        assert left['identity']['implementation_sha256']!=right['identity']['implementation_sha256']
        assert right['usage_role']=='CLEAN_CONTROL'


def test_reproduction_inputs_remain_evaluator_only():
    for case in historical.cases():
        assert 'reproduction_input' in case.entry
        assert 'reproduction_input' not in case.metadata()
        assert 'fix_evidence' not in case.metadata()
        assert 'source_statements' not in case.metadata()


def test_external_load_and_direct_call_fail_before_execution_when_gate_denies(monkeypatch):
    import tomolab.historical as boundary
    def denied():
        raise PermissionError('test gate denies external execution')
    monkeypatch.setattr(boundary,'require_reviewed_container',denied)
    with pytest.raises(PermissionError,match='gate denies'):
        historical.cases(load=True)
    with pytest.raises(PermissionError,match='gate denies'):
        historical.load_case('toolz-interpose')
    with pytest.raises(PermissionError,match='gate denies'):
        historical.cases()[0].direct([])


@pytest.fixture
def copied_catalog(tmp_path):
    root=tmp_path/'catalog'
    shutil.copytree(historical.DEFAULT_CATALOG,root)
    return root


def test_capsule_and_full_license_tampering_are_rejected(copied_catalog):
    manifest=historical.read_manifest(copied_catalog)
    path=copied_catalog/manifest['cases'][0]['buggy']['capsule']
    path.write_bytes(path.read_bytes()+b'\n# changed\n')
    with pytest.raises(ValueError,match='capsule bytes changed'):
        historical.read_manifest(copied_catalog)
    record=manifest['cases'][0]['buggy']
    path.write_bytes((historical.DEFAULT_CATALOG/record['capsule']).read_bytes())
    license_file=copied_catalog/manifest['cases'][0]['license_file']
    license_file.write_bytes(b'not the original license')
    with pytest.raises(ValueError,match='original license changed'):
        historical.read_manifest(copied_catalog)


def test_rehashing_modified_capsule_alone_cannot_change_original_function(copied_catalog):
    manifest=historical.read_manifest(copied_catalog)
    record=manifest['cases'][0]['buggy']
    path=copied_catalog/record['capsule']
    raw=path.read_bytes().replace(b'next(inposed)',b'next(inposed, None)')
    path.write_bytes(raw)
    record['capsule_sha256']=hashlib.sha256(raw).hexdigest()
    (copied_catalog/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(ValueError,match='source statement changed'):
        historical.read_manifest(copied_catalog)


def test_metadata_cannot_disguise_original_typed_input(copied_catalog):
    manifest=historical.read_manifest(copied_catalog)
    manifest['cases'][0]['contract']={'kind':'int','low':-4,'high':4}
    (copied_catalog/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(ValueError,match='original public input kind'):
        historical.read_manifest(copied_catalog)


@pytest.mark.parametrize('adapter,point,expected',[
    ('interpose',[],[]),('interpose',[1,0,-1],[1,0,0,0,-1]),
    ('bucket',[1,2],[]),('bucket',[],[]),
    ('windowed',[],[]),('windowed',[2],[(2,None)]),('windowed',[1,2,3],[(1,2),(2,3)]),
    ('accumulate',[],[]),('accumulate',[1,-1,4],[1,0,4]),
    ('split',[],[[]]),('split',[1,2],[[1,2]]),
    ('punct','a\\b] a!',['a','b','a']),
    ('lines','a\u2028b\r\n',['a','b','']),('lines','a 28b',['a 28b']),('lines','',[]),
    ('bytes',1023.6,'1K'),('bytes',-1023.6,'-1K'),('bytes',1023.4,'1023B'),('bytes',-0.0,'-0B'),
])
def test_independent_public_contract_oracles(adapter,point,expected):
    # These are our reference implementations, not downloaded upstream functions.
    assert historical.ORACLES[adapter](point)==expected
