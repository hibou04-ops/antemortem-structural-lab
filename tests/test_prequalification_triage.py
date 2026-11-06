"""Authored inert sources test triage boundaries, never upstream execution."""
from copy import deepcopy
import hashlib

import pytest

from tomolab.discovery.prequalification_triage import file_role, triage_record
from tomolab.discovery.schema import digest

BEFORE = "def total(xs: list[int]) -> int:\n    return sum(xs) + 1\n"
AFTER = "def total(xs: list[int]) -> int:\n    return sum(xs)\n"


def blob(text, revision, path="module.py"):
    raw=text.encode()
    return dict(text=text,path=path,revision=revision,sha256=hashlib.sha256(raw).hexdigest(),
                git_blob_sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())


def record(before=BEFORE, after=AFTER, path="module.py"):
    return dict(candidate_id="a"*64,metadata_digest="b"*64,repository="authored/project",buggy_revision="1"*40,fixed_revision="2"*40,
        files=[dict(path=path,status="modified",git_blob_sha=blob(after,"2"*40,path)["git_blob_sha"])],files_complete=True,expected_changed_files=1,
        source_pairs=[dict(path=path,status="modified",before=blob(before,"1"*40,path),after=blob(after,"2"*40,path))],uninspected_runtime_paths=[],reasons=[])


def test_typed_integer_sequence_is_candidate_never_qualified_or_oracle_proved():
    value=record();result=triage_record(value)
    assert result["status"]=="CANDIDATE_SEQUENCE_INT" and result["track"]=="TRACK_SEQ_INT"
    assert result["qualified"] is False and result["oracle_independence"]=="UNKNOWN"
    assert result["function_candidates"][0]["identity"]["implementation_sha256"]==value["source_pairs"][0]["before"]["sha256"]
    assert result["target_calls"]==result["oracle_calls"]==0
    assert result["sha256"]==digest({k:v for k,v in result.items() if k!="sha256"})


def test_text_candidate_uses_separate_track():
    result=triage_record(record("def f(text: str):\n    return text.replace('a','')\n","def f(text: str):\n    return text\n"))
    assert result["status"]=="CANDIDATE_TEXT" and result["track"]=="TRACK_TEXT"


@pytest.mark.parametrize("path,role",[("docs/a.py","DOCUMENTATION"),("src/pkg/tests/helper.py","TEST"),("Lib/test/test_os.py","TEST"),("src/test_helpers.py","PYTHON_RUNTIME"),("src/template.html","UNSUPPORTED_RUNTIME_OR_CONFIG"),("pyproject.toml","UNSUPPORTED_RUNTIME_OR_CONFIG")])
def test_complete_file_role_uses_conservative_path_evidence(path,role):
    assert file_role(path)==role


@pytest.mark.parametrize("path",["src/license_checker.py","src/readme_generator.py"])
def test_document_like_python_filename_is_not_proof_of_documentation_only(path):
    assert file_role(path)=="PYTHON_RUNTIME"


@pytest.mark.parametrize("path",["../module.py","/module.py","src\\module.py"])
def test_unsafe_source_paths_rejected(path):
    with pytest.raises(ValueError):file_role(path)


@pytest.mark.parametrize("paths",[["docs/a.rst"],["tests/test_algorithm.py"],["docs/a.md","src/pkg/tests/helper.py"]])
def test_complete_docs_and_tests_only_lists_are_excluded(paths):
    value=record();value.update(files=[dict(path=p,status="modified") for p in paths],expected_changed_files=len(paths),source_pairs=[])
    result=triage_record(value)
    assert result["status"]=="EXCLUDE_DOC_OR_NON_CODE" and len(result["changed_files"])==len(paths)


def test_incomplete_file_pages_cannot_prove_docs_only():
    value=record();value.update(files=[dict(path="docs/a.md",status="modified")],source_pairs=[],files_complete=False)
    assert triage_record(value)["status"]=="HOLD_INSUFFICIENT_STATIC_EVIDENCE"


def test_runtime_config_or_c_source_is_held_not_called_non_code():
    value=record();value["files"].append(dict(path="src/native.c",status="modified"));value["expected_changed_files"]=2
    assert triage_record(value)["status"]=="HOLD_CONTRACT_OR_IMPURE"


@pytest.mark.parametrize("change",["missing_pair","missing_before","cap","pin"])
def test_missing_runtime_source_or_revision_stays_unknown(change):
    value=record()
    if change=="missing_pair":value["source_pairs"]=[]
    elif change=="missing_before":value["source_pairs"][0]["before"]=None
    elif change=="cap":value["uninspected_runtime_paths"]=["another.py"]
    else:value["buggy_revision"]=None
    assert triage_record(value)["status"]=="HOLD_INSUFFICIENT_STATIC_EVIDENCE"


def test_whitespace_comments_and_docstrings_compare_as_execution_ast():
    before='def f(x):\n    """before"""\n    return x\n'
    after='# authored comment\ndef f(x):\n    """after"""\n    return x  # another comment\n'
    result=triage_record(record(before,after))
    assert result["status"]=="EXCLUDE_DOC_OR_NON_CODE"
    assert result["source_reviews"][0]["doc_comment_stripped_ast_equal"] is True


@pytest.mark.parametrize("prefix",["", "from __future__ import annotations\n"])
def test_annotation_erasure_cannot_hide_eager_or_introspection_semantics(prefix):
    result=triage_record(record(prefix+"def f(x: int):\n    return x\n",prefix+"def f(x: str):\n    return x\n"))
    assert result["status"]=="HOLD_CONTRACT_OR_IMPURE"
    assert result["source_reviews"][0]["annotation_stripped_ast_equal"] is True
    assert "ANNOTATION_ERASURE_EQUAL_BUT_RUNTIME_EFFECT_UNKNOWN" in result["reasons"]


def test_decorator_may_read_changed_docstring():
    result=triage_record(record('@hook\ndef f(x):\n    """a"""\n    return x\n','@hook\ndef f(x):\n    """b"""\n    return x\n'))
    assert result["status"]=="HOLD_CONTRACT_OR_IMPURE"


@pytest.mark.parametrize("access",["getattr(f, '__doc__')","vars(f)['__doc__']","inspect.getdoc(f)","f.__getattribute__('__doc__')"])
def test_dynamic_doc_introspection_is_not_ignored_by_docstring_erasure(access):
    before='def f(x):\n    """a"""\n    return x\nresult='+access+'\n'
    after=before.replace('"""a"""','"""b"""')
    value=triage_record(record(before,after))
    assert value["source_reviews"][0]["doc_comment_stripped_ast_equal"] is True
    assert value["status"]=="HOLD_CONTRACT_OR_IMPURE"


@pytest.mark.parametrize("observer",["result=__doc__", "from inspect import getdoc as describe\nresult=describe(f)", "read_attribute=getattr\nresult=read_attribute(f,'__doc__')"])
def test_module_doc_name_and_explicit_observer_aliases_are_not_false_excluded(observer):
    before='"""module a"""\ndef f(x):\n    """function a"""\n    return x\n'+observer+'\n'
    after=before.replace('module a','module b').replace('function a','function b')
    assert triage_record(record(before,after))["status"]=="HOLD_CONTRACT_OR_IMPURE"


def test_exact_ast_unchanged_is_not_mislabelled_impure_due_to_existing_decorator():
    before='@hook\ndef f(x):\n    return x\n'
    assert triage_record(record(before,before+'# only a comment\n'))["status"]=="EXCLUDE_DOC_OR_NON_CODE"


@pytest.mark.parametrize("before,after",[
    ("def f(xs):\n    return sum(xs)+1\n","def f(xs):\n    return sum(xs)\n"),
    ("async def f(xs: list[int]):\n    return sum(xs)+1\n","async def f(xs: list[int]):\n    return sum(xs)\n"),
    ("def f(xs: list[int]):\n    yield 1\n","def f(xs: list[int]):\n    yield 2\n"),
    ("def f(xs: list[int]):\n    return (x+1 for x in xs)\n","def f(xs: list[int]):\n    return (x for x in xs)\n"),
    ("def f(xs: list[int]):\n    return open('a').read()\n","def f(xs: list[int]):\n    return open('b').read()\n"),
    ("def f(xs: list[int]):\n    global state\n    state=1\n    return xs\n","def f(xs: list[int]):\n    global state\n    state=2\n    return xs\n"),
    ("def f(xs: list[int]):\n    xs.append(1)\n    return xs\n","def f(xs: list[int]):\n    xs.append(2)\n    return xs\n"),
    ("def f(xs: list[int]):\n    xs[0]=1\n    return xs\n","def f(xs: list[int]):\n    xs[0]=2\n    return xs\n"),
    ("@hook\ndef f(xs: list[int]):\n    return sum(xs)+1\n","@hook\ndef f(xs: list[int]):\n    return sum(xs)\n"),
    ("import numpy\n"+BEFORE,"import numpy\n"+AFTER),
    ("register()\n"+BEFORE,"register()\n"+AFTER),
    ("class State: pass\n"+BEFORE,"class State: pass\n"+AFTER),
    ("def f(self):\n    return self.value+1\n","def f(self):\n    return self.value\n"),
    ("def f(xs: list[int], cache=[]):\n    return sum(xs)+1\n","def f(xs: list[int], cache=[]):\n    return sum(xs)\n"),
])
def test_impure_untyped_or_hooked_functions_cannot_become_typed_candidates(before,after):
    result=triage_record(record(before,after))
    assert result["status"]=="HOLD_CONTRACT_OR_IMPURE" and result["function_candidates"]==[]


def test_source_hash_tampering_is_held_without_executing_it():
    value=record();value["source_pairs"][0]["after"]["text"]="raise SystemExit('never execute')"
    assert triage_record(value)["status"]=="HOLD_INSUFFICIENT_STATIC_EVIDENCE"


def test_unsupported_new_grammar_is_hold_not_false_exclusion():
    value=record(BEFORE,"def total(xs: list[int]):\n    return [*x for x in xs]\n")
    assert triage_record(value)["status"]=="HOLD_CONTRACT_OR_IMPURE"


def test_supported_grammar_outside_reviewed_ast_serializer_is_explicit_unknown():
    value=record("def f(xs: list[int]):\n    return ...\n",AFTER)
    assert "STATIC_AST_REPRESENTATION_UNKNOWN" in triage_record(value)["reasons"]


def test_rehashed_caller_candidate_label_is_not_trusted():
    value=record();value.update(files_complete=False,status="CANDIDATE_SEQUENCE_INT",qualified=True,oracle_independence="PASS")
    value["sha256"]=digest(value)
    result=triage_record(value)
    assert result["status"]=="HOLD_INSUFFICIENT_STATIC_EVIDENCE" and result["qualified"] is False


def test_local_fresh_accumulator_mutation_does_not_claim_input_mutation():
    result=triage_record(record("def f(xs: list[int]):\n    result=[]\n    for x in xs: result.append(x+1)\n    return result\n","def f(xs: list[int]):\n    result=[]\n    for x in xs: result.append(x)\n    return result\n"))
    assert result["status"]=="CANDIDATE_SEQUENCE_INT"
