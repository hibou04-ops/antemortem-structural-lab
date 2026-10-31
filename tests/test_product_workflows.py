"""Authored product workflows only; no historical corpus or research batch."""
import argparse
from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from tomolab.cli import EXAMPLES, main
from tomolab.discovery.online_engine import run_online
from tomolab.discovery.schema import digest
from tomolab.online_cli import register, validate_json_callable


def identity(point):
    return point


def two_arguments(point, other):
    return point + other


def variadic(*point):
    return point


def keyword_only(*, point):
    return point


async def asynchronous(point):
    return point


def generator(point):
    yield point


def _common(folder, output):
    return [str(folder/'target.py'), '--oracle-file', str(folder/'oracle.py'),
            '--contract', str(folder/'contract.json'), '--allow-local-execution',
            '--usage-ledger', str(output.with_suffix('.usage.jsonl')), '--output', str(output),
            '--budget', '24', '--shrink-budget', '6']


def _replay_args(folder, receipt, output):
    return ['online-replay', str(receipt), '--source', str(folder/'target.py'),
            '--oracle-file', str(folder/'oracle.py'), '--contract', str(folder/'contract.json'),
            '--allow-local-execution', '--output', str(output)]


@pytest.fixture(scope='module')
def product_receipt(tmp_path_factory):
    root = tmp_path_factory.mktemp('authored-product')
    folder = root/'input'; folder.mkdir()
    for name in ('target.py','oracle.py','contract.json'):
        (folder/name).write_bytes((EXAMPLES/'product'/name).read_bytes())
    output = root/'result.json'
    assert main(['online-run', *_common(folder, output)]) == 0
    return folder, output, json.loads(output.read_text(encoding='utf-8'))


def test_public_API_and_CLI_defaults_A():
    assert inspect.signature(run_online).parameters['method'].default == 'A'
    parser = argparse.ArgumentParser(); commands = parser.add_subparsers(dest='command')
    register(commands)
    args = parser.parse_args(['online-run', *_common(Path('inputs'), Path('result.json'))])
    assert args.method == 'A'
    result = run_online(identity, identity, dict(kind='int', low=-2, high=2), budget=6, shrink_budget=0)
    assert result['method'] == 'E9_A'
    assert result['source_replay_calls'] == 0
    assert result['scheduler']['learned_lookups'] == 0


def test_default_run_binds_files_contract_and_reproduces(product_receipt, tmp_path):
    folder, path, receipt = product_receipt
    assert receipt['run']['method'] == 'E9_A'
    assert receipt['method_context']['default_method'] == 'A'
    assert receipt['method_context']['source_replays']['source'] == 'NONE'
    assert receipt['run']['first_confirmed_failure']
    assert receipt['replay_binding']['contract_digest'] == digest(receipt['run']['contract'])
    output = tmp_path/'reproduced.json'
    assert main(_replay_args(folder, path, output)) == 0
    replay = json.loads(output.read_text(encoding='utf-8'))
    assert replay['status'] == 'COMPLETE' and replay['replay_status'] == 'REPRODUCED'
    assert replay['binding_status'] == 'FILE_AND_CONTRACT_BINDINGS_MATCH'
    assert replay['target_calls'] == replay['oracle_calls'] == 3*replay['replayed']
    assert all(row['reproduced'] and all(row['semantic_references_match']) for row in replay['results'])
    assert replay['research_comparison_reexecuted'] is False


@pytest.mark.parametrize('changed', ['target.py','oracle.py','contract.json'])
def test_replay_rejects_file_or_contract_drift_before_import(product_receipt, tmp_path, changed):
    folder, path, _ = product_receipt
    copied = tmp_path/'input'; copied.mkdir()
    for name in ('target.py','oracle.py','contract.json'):
        (copied/name).write_bytes((folder/name).read_bytes())
    if changed.endswith('.py'):
        with (copied/changed).open('a', encoding='utf-8') as stream:
            stream.write('\nraise AssertionError("drifted module must not import")\n')
    else:
        (copied/changed).write_text('{"kind":"int","low":-7,"high":8}', encoding='utf-8')
    output = tmp_path/'replay.json'
    with pytest.raises(SystemExit) as error:
        main(_replay_args(copied, path, output))
    assert error.value.code == 2 and not output.exists()


def test_legacy_replay_needs_explicit_unverified_binding_opt_in(product_receipt, tmp_path, capsys):
    folder, _, receipt = product_receipt
    legacy = deepcopy(receipt); legacy.pop('replay_binding')
    path = tmp_path/'legacy.json'; path.write_text(json.dumps(legacy), encoding='utf-8')
    output = tmp_path/'legacy-replay.json'
    with pytest.raises(SystemExit) as error:
        main(_replay_args(folder, path, output))
    assert error.value.code == 2 and not output.exists()
    assert main([*_replay_args(folder, path, output), '--allow-unbound-legacy']) == 0
    replay = json.loads(output.read_text(encoding='utf-8'))
    assert replay['binding_status'] == 'LEGACY_SOURCE_ORACLE_IDENTITY_UNVERIFIED'
    assert '구형 영수증' in capsys.readouterr().err


def test_corrupt_run_receipt_and_historical_receipt_do_not_replay(product_receipt, tmp_path):
    folder, _, receipt = product_receipt
    for name, change in [('corrupt',{'run':dict(receipt['run'], seed=12345)}),
                         ('historical',{'historical_case':{'id':'not-for-local-replay'}})]:
        payload = dict(receipt, **change)
        path = tmp_path/(name+'.json'); path.write_text(json.dumps(payload), encoding='utf-8')
        output = tmp_path/(name+'-out.json')
        with pytest.raises(SystemExit) as error:
            main(_replay_args(folder, path, output))
        assert error.value.code == 2 and not output.exists()


def test_semantic_reproduction_uses_original_output_reference(product_receipt, tmp_path):
    folder, _, receipt = product_receipt
    payload = deepcopy(receipt)
    # This models a validly serialized older host receipt from another observed
    # behavior, not a replacement numerical/exception comparison contract.
    for row in payload['run']['private_outcomes']:
        row['semantic_digest'] = '0'*64
    payload['run']['receipt_sha256'] = digest({k:v for k,v in payload['run'].items()if k!='receipt_sha256'})
    path = tmp_path/'different-observation.json'; path.write_text(json.dumps(payload), encoding='utf-8')
    output = tmp_path/'not-reproduced.json'
    assert main(_replay_args(folder, path, output)) == 3
    replay = json.loads(output.read_text(encoding='utf-8'))
    assert replay['replay_status'] == 'NOT_REPRODUCED'
    assert all(not row['reproduced'] for row in replay['results'])


@pytest.mark.parametrize('method', ['A','B'])
def test_default_or_explicit_B_demo_does_not_prepare_Source(tmp_path, method):
    workspace = tmp_path/'workspace'; output = tmp_path/'result.json'
    args = ['online-demo','--workspace',str(workspace),'--usage-ledger',str(tmp_path/'usage.jsonl'),
            '--allow-local-execution','--output',str(output),'--budget','24','--shrink-budget','6']
    if method == 'B':args += ['--method','B']
    assert main(args) == 0
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['run']['method'] == 'E9_'+method
    assert result['source_learning'] == dict(enabled=False,target_calls=0,oracle_calls=0,rules=0,reason='SOURCE_LEARNING_NOT_REQUESTED')
    assert not (workspace/'source.json').exists() and not (workspace/'mold.json').exists()


def test_C_requires_replay_opt_in_and_records_input_only_provenance(product_receipt, tmp_path):
    folder, _, _ = product_receipt
    replays = tmp_path/'replays.json'; replays.write_text('[0, 99]', encoding='utf-8')
    output = tmp_path/'C.json'
    assert main(['online-run', *_common(folder, output), '--method','C','--replays',str(replays)]) == 0
    result = json.loads(output.read_text(encoding='utf-8'))
    provenance = result['method_context']['source_replays']
    assert provenance['source'] == 'EXPLICIT_INPUT_FILE' and provenance['explicitly_selected']
    assert provenance['input_count'] == 2 and provenance['domain_rejected'] == 1
    assert provenance['actual_replay_calls'] > 0 and provenance['labels_transferred'] is False
    assert len(provenance['file_sha256']) == 64
    denied = tmp_path/'A-denied.json'
    with pytest.raises(SystemExit) as error:
        main(['online-run', *_common(folder, denied), '--replays',str(replays)])
    assert error.value.code == 2 and not denied.exists()


def test_explicit_D_keeps_existing_flags_and_reports_experimental_warning(product_receipt, tmp_path, capsys):
    from tomolab.discovery.online_learning import learn_mold, save_mold
    folder, _, receipt = product_receipt
    mold = learn_mold(receipt['run']['observations']); path = tmp_path/'mold.json'; save_mold(path,mold)
    output = tmp_path/'D.json'
    assert main(['online-run', *_common(folder,output), '--method','D','--mold',str(path),
                 '--expected-digest',mold['artifact_digest']]) == 0
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['method_context']['experimental'] and result['method_context']['warning']
    assert '실험적 Source 가이드' in capsys.readouterr().err


@pytest.mark.parametrize('fn', [two_arguments,variadic,keyword_only,asynchronous,generator])
def test_unsupported_signature_fails_with_adapter_guidance(fn):
    with pytest.raises(ValueError, match='single JSON argument|one positional JSON argument'):
        validate_json_callable(fn,'Target')


def test_missing_qa_fails_before_target_import_or_artifact_creation(monkeypatch,tmp_path):
    import importlib.util
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util,'find_spec',lambda name,*a,**k:None if name=='hypothesis' else original(name,*a,**k))
    output = tmp_path/'missing.json'; workspace = tmp_path/'workspace'; ledger = tmp_path/'usage.jsonl'
    with pytest.raises(SystemExit) as error:
        main(['online-demo','--workspace',str(workspace),'--usage-ledger',str(ledger),
              '--allow-local-execution','--output',str(output)])
    assert error.value.code == 2
    assert not any(path.exists() for path in (output,workspace,ledger))


def test_version_is_available_without_an_execution_command(capsys):
    with pytest.raises(SystemExit) as error:
        main(['--version'])
    assert error.value.code == 0 and capsys.readouterr().out.startswith('tomolab ')
