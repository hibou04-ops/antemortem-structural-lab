"""Deterministic static prequalification. Upstream text is never imported.

Candidate labels are typed static possibilities, never reproduced defects or
qualification authority. Annotation erasure is a comparison diagnostic, not a
proof that eager evaluation, decorators, or introspection cannot affect runtime.
"""
import ast
from copy import deepcopy
import hashlib
from pathlib import PurePosixPath
import re

from .harvester_review import canonical_ast_dump, static_source_review
from .schema import digest

SCHEMA = "tomolab-prequalification-triage-v1"
STATUSES = ("EXCLUDE_DOC_OR_NON_CODE", "HOLD_CONTRACT_OR_IMPURE", "HOLD_INSUFFICIENT_STATIC_EVIDENCE",
            "CANDIDATE_SEQUENCE_INT", "CANDIDATE_TEXT")
SAFE_IMPORTS = {"__future__", "typing", "math", "itertools", "collections", "functools", "operator", "bisect", "heapq", "statistics", "fractions", "decimal"}
SAFE_BUILTINS = {"len", "range", "enumerate", "zip", "reversed", "sorted", "sum", "min", "max", "all", "any", "abs", "int", "float", "str", "bool", "list", "tuple", "dict", "set", "frozenset", "round", "divmod", "isinstance", "ValueError", "TypeError", "IndexError", "ZeroDivisionError", "OverflowError"}
READ_METHODS = {"copy", "count", "index", "find", "rfind", "replace", "lower", "upper", "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "join", "startswith", "endswith", "isdigit", "isalpha", "isalnum", "isspace", "casefold", "capitalize", "swapcase", "title", "removeprefix", "removesuffix"}
MUTATORS = {"append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse", "update", "add", "discard", "setdefault"}


def file_role(path):
    """Conservative path evidence; ambiguous test-like production names stay code."""
    if type(path) is not str or not path or "\\" in path:
        raise ValueError("bounded relative upstream file path required")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or len(path) > 1024:
        raise ValueError("upstream path escapes the source tree")
    parts = [v.lower() for v in p.parts]
    name = p.name.lower()
    if any(v in {"tests", "test"} for v in parts[:-1]) or name == "conftest.py":
        return "TEST"
    if (any(v in {"docs", "doc", "documentation"} for v in parts[:-1]) or "news.d" in parts
            or name.endswith((".md", ".rst", ".adoc"))
            or not name.endswith(".py") and name.startswith(("readme", "changelog", "contributing", "license", "copying", "authors"))):
        return "DOCUMENTATION"
    return "PYTHON_RUNTIME" if name.endswith(".py") else "UNSUPPORTED_RUNTIME_OR_CONFIG"


class _ExecutionTree(ast.NodeTransformer):
    def __init__(self, annotations=False):
        self.annotations = annotations

    def _body(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and type(node.body[0].value.value) is str:
            node.body = node.body[1:]
        return node

    visit_Module = _body
    visit_ClassDef = _body

    def visit_FunctionDef(self, node):
        node = self._body(node)
        if self.annotations:
            node.returns = None
            node.type_comment = None
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_arg(self, node):
        self.generic_visit(node)
        if self.annotations:
            node.annotation = None
            node.type_comment = None
        return node

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        if not self.annotations:
            return node
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=node.value, type_comment=None)


def _tree_hash(tree, *, annotations=False):
    changed = _ExecutionTree(annotations=annotations).visit(deepcopy(tree))
    return hashlib.sha256(canonical_ast_dump(changed).encode()).hexdigest()


def _doc_introspection(tree):
    """Explicit and dynamic doc access defeats doc-erasure equivalence claims."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in {"__doc__", "getattr", "vars", "getdoc"}:
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "inspect":
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "__doc__":
            return True
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "__doc__":
            return True
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"getattr", "vars"}:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"getdoc", "__getattribute__"}:
                return True
    return False


def _immutable(node):
    return isinstance(node, ast.Constant) and type(node.value) in (type(None), bool, int, float, str, bytes) or isinstance(node, ast.Tuple) and all(_immutable(v) for v in node.elts)


def _main_guard(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__" and len(node.test.ops) == len(node.test.comparators) == 1
            and isinstance(node.test.ops[0], ast.Eq) and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__" and not node.orelse)


def _module_flags(tree):
    flags = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list:
                flags.add("MODULE_DECORATOR_EXECUTION_REQUIRES_REVIEW")
            if any(not _immutable(v) for v in node.args.defaults + [v for v in node.args.kw_defaults if v is not None]):
                flags.add("MODULE_DEFAULT_EXPRESSION_OR_MUTABLE_STATE")
            annotations = [a.annotation for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if a.annotation] + ([node.returns] if node.returns else [])
            if any(any(isinstance(v, ast.Call) for v in ast.walk(a)) for a in annotations):
                flags.add("EAGER_ANNOTATION_CALL_REQUIRES_REVIEW")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            roots = ([v.name.split(".")[0] for v in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]])
            if isinstance(node, ast.ImportFrom) and (node.level or any(v.name == "*" for v in node.names)):
                flags.add("RELATIVE_OR_STAR_IMPORT_REQUIRES_REVIEW")
            if any(root not in SAFE_IMPORTS for root in roots):
                flags.add("THIRD_PARTY_OR_UNREVIEWED_MODULE_IMPORT")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str:
            pass
        elif isinstance(node, ast.Assign) and _immutable(node.value) and all(isinstance(v, ast.Name) and not v.id.startswith("__") for v in node.targets):
            pass
        elif _main_guard(node) or isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.ClassDef):
            flags.add("MODULE_CLASS_OR_HOOK_INITIALIZATION")
        else:
            flags.add("MODULE_STATE_OR_EXECUTABLE_INITIALIZATION")
    return sorted(flags)


def _type_track(node):
    positional = node.args.posonlyargs + node.args.args
    required = len(positional) - len(node.args.defaults)
    if required != 1 or not positional or node.args.vararg or node.args.kwarg or any(v is None for v in node.args.kw_defaults):
        return None, "UNARY_INPUT_SIGNATURE_NOT_ESTABLISHED"
    annotation = positional[0].annotation
    text = ast.unparse(annotation).replace(" ", "") if annotation is not None else ""
    if text in {"list[int]", "List[int]", "Sequence[int]", "typing.List[int]", "typing.Sequence[int]"}:
        return "TRACK_SEQ_INT", "DECLARED_INTEGER_SEQUENCE_INPUT_NOT_A_REVIEWED_CONTRACT"
    if text == "str":
        return "TRACK_TEXT", "DECLARED_TEXT_INPUT_NOT_A_REVIEWED_CONTRACT"
    return None, "INPUT_TYPE_UNKNOWN_OR_NOT_SEQUENCE_INT_OR_TEXT"


def _function_flags(node):
    flags = set()
    if isinstance(node, ast.AsyncFunctionDef):
        flags.add("ASYNC_FUNCTION")
    if node.decorator_list:
        flags.add("DECORATED_OR_HOOKED_CALLABLE")
    arguments = {v.arg for v in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
    if arguments & {"self", "cls"}:
        flags.add("CLASS_INSTANCE_OR_CLASS_STATE")
    if getattr(node, "type_params", []):
        flags.add("GENERIC_TYPE_PARAMETER_RUNTIME_REQUIRES_REVIEW")
    if any(not _immutable(v) for v in node.args.defaults + [v for v in node.args.kw_defaults if v is not None]):
        flags.add("MUTABLE_OR_UNREVIEWED_DEFAULT_HOOK")
    body = ast.Module(body=deepcopy(node.body), type_ignores=[])
    nodes = list(ast.walk(body))
    locals_ = arguments | {v.id for v in nodes if isinstance(v, ast.Name) and isinstance(v.ctx, ast.Store)}
    fresh = set()
    assigned = {}
    for v in nodes:
        if isinstance(v, ast.Assign):
            for target in v.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(v.value)
    for name, values in assigned.items():
        if name not in arguments and all(isinstance(v, (ast.List, ast.ListComp, ast.Dict, ast.DictComp, ast.Set, ast.SetComp)) or isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in {"list", "dict", "set"} for v in values):
            fresh.add(name)
    for v in nodes:
        if isinstance(v, (ast.Global, ast.Nonlocal)):
            flags.add("GLOBAL_OR_NONLOCAL_STATE")
        if isinstance(v, (ast.Yield, ast.YieldFrom, ast.Await)) or isinstance(v, ast.Return) and isinstance(v.value, ast.GeneratorExp):
            flags.add("GENERATOR_OR_ASYNC_PROTOCOL")
        if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            flags.add("CLOSURE_CLASS_OR_CALLBACK_PROTOCOL")
        if isinstance(v, ast.Name) and isinstance(v.ctx, ast.Load) and v.id not in locals_ | SAFE_BUILTINS | {node.name}:
            flags.add("GLOBAL_READ_OR_EXTERNAL_HELPER:" + v.id)
        if isinstance(v, (ast.Subscript, ast.Attribute)) and isinstance(v.ctx, (ast.Store, ast.Del)):
            root = v
            while isinstance(root, (ast.Subscript, ast.Attribute)):
                root = root.value
            if not isinstance(root, ast.Name) or root.id not in fresh:
                flags.add("INPUT_ALIAS_OR_EXTERNAL_OBJECT_MUTATION")
        if isinstance(v, ast.Call):
            if isinstance(v.func, ast.Name):
                if v.func.id not in SAFE_BUILTINS | {node.name}:
                    flags.add("IO_DYNAMIC_OR_UNREVIEWED_CALL:" + v.func.id)
            elif isinstance(v.func, ast.Attribute) and isinstance(v.func.value, ast.Name):
                root, method = v.func.value.id, v.func.attr
                if method in MUTATORS and root not in fresh:
                    flags.add("INPUT_ALIAS_OR_EXTERNAL_OBJECT_MUTATION")
                elif root not in locals_ or method not in READ_METHODS | MUTATORS:
                    flags.add("EXTERNAL_METHOD_OR_HOOK:" + root + "." + method)
            else:
                flags.add("DYNAMIC_OR_CALLBACK_CALL")
    return sorted(flags)


def _source(row, *, revision, path):
    if type(row) is not dict or row.get("revision") != revision or row.get("path") != path:
        raise ValueError("source does not bind the exact pre/post revision and path")
    text = row.get("text")
    if type(text) is not str or len(text.encode()) > 256 * 1024:
        raise ValueError("bounded UTF-8 source text required")
    raw = text.encode()
    if hashlib.sha256(raw).hexdigest() != row.get("sha256") or hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != row.get("git_blob_sha"):
        raise ValueError("source bytes or Git blob hash mismatch")
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > 100000:
        raise ValueError("static AST node bound exceeded")
    return tree


def triage_record(record):
    """Data receipt from complete file metadata and hash-bound source pairs.

    No caller-provided PASS, purity, track, or Oracle label is trusted. This
    function neither fetches files nor grants execution/qualification authority.
    """
    if type(record) is not dict or any(type(record.get(k)) is not str for k in ("candidate_id", "metadata_digest", "repository")):
        raise ValueError("exact original candidate identity required")
    if "sha256" in record and record["sha256"] != digest({k:v for k,v in record.items() if k != "sha256"}):
        raise ValueError("static input record content digest mismatch")
    for name in ("candidate_id", "metadata_digest"):
        if re.fullmatch(r"[a-f0-9]{64}", record[name]) is None:
            raise ValueError("original SHA256 identity required")
    files = record.get("files", [])
    if type(files) is not list or len(files) > 200:
        raise ValueError("bounded changed-file metadata required")
    roles = [dict(path=v["path"], status=v["status"], role=file_role(v["path"])) for v in files]
    result = dict(schema=SCHEMA, candidate_id=record["candidate_id"], metadata_digest=record["metadata_digest"],
        status="HOLD_INSUFFICIENT_STATIC_EVIDENCE", track="UNKNOWN", reasons=[], changed_files=roles,
        files_complete=record.get("files_complete") is True, source_reviews=[], function_candidates=[], held_functions=[],
        qualified=False, purity="NOT_PROVED_STATIC_PREQUALIFICATION_ONLY", oracle_independence="UNKNOWN",
        host_source_imported=False, host_source_executed=False, host_source_pytest=False, target_calls=0, oracle_calls=0,
        evidence_scope="DEVELOPMENT_STATIC_TRIAGE_NOT_RUNTIME_BUG_VALIDATION_NOT_OOS")
    def finish(status, reasons):
        result["status"] = status
        result["reasons"] = sorted(set(reasons))
        result["sha256"] = digest(result)
        return result
    if record.get("files_complete") is not True or type(record.get("expected_changed_files")) is not int or record["expected_changed_files"] != len(files) or len({v["path"] for v in roles}) != len(files) or not files:
        return finish("HOLD_INSUFFICIENT_STATIC_EVIDENCE", ["COMPLETE_CHANGED_FILE_LIST_NOT_ESTABLISHED"])
    runtime = [v for v in roles if v["role"] == "PYTHON_RUNTIME"]
    if all(v["role"] in {"DOCUMENTATION", "TEST"} for v in roles):
        return finish("EXCLUDE_DOC_OR_NON_CODE", ["COMPLETE_FILE_LIST_CONTAINS_ONLY_DOCUMENTATION_OR_TESTS"])
    if any(v["role"] == "UNSUPPORTED_RUNTIME_OR_CONFIG" for v in roles):
        return finish("HOLD_CONTRACT_OR_IMPURE", ["NON_PYTHON_RUNTIME_OR_CONFIGURATION_CHANGE"])
    pairs = record.get("source_pairs", [])
    if type(pairs) is not list or len(pairs) > 4:
        raise ValueError("at most four prospectively bounded source pairs required")
    if record.get("uninspected_runtime_paths") or {v["path"] for v in pairs} != {v["path"] for v in runtime} or len(pairs) != len(runtime):
        return finish("HOLD_INSUFFICIENT_STATIC_EVIDENCE", ["MISSING_OR_CAPPED_RUNTIME_SOURCE_PATHS"])
    if any(v.get("before") is None or v.get("after") is None for v in pairs):
        return finish("HOLD_INSUFFICIENT_STATIC_EVIDENCE", ["MISSING_PRE_OR_POST_SOURCE_OR_ADDED_REMOVED_FILE"])
    if any(v.get("previous_path") not in (None, v["path"]) for v in pairs):
        return finish("HOLD_CONTRACT_OR_IMPURE", ["RENAMED_MODULE_RUNTIME_IDENTITY_REQUIRES_REVIEW"])
    if any(type(record.get(name)) is not str or re.fullmatch(r"[a-f0-9]{40}", record[name]) is None for name in ("buggy_revision", "fixed_revision")):
        return finish("HOLD_INSUFFICIENT_STATIC_EVIDENCE", ["EXACT_PRE_POST_REVISION_PINS_MISSING"])
    parsed = []
    for pair in pairs:
        try:
            a = _source(pair["before"], revision=record.get("buggy_revision"), path=pair.get("previous_path") or pair["path"])
            b = _source(pair["after"], revision=record.get("fixed_revision"), path=pair["path"])
        except (SyntaxError, RecursionError):
            return finish("HOLD_CONTRACT_OR_IMPURE", ["PYTHON_GRAMMAR_OR_AST_SUPPORT_UNKNOWN"])
        except ValueError as error:
            return finish("HOLD_INSUFFICIENT_STATIC_EVIDENCE", ["SOURCE_IDENTITY_OR_BOUND_FAILED:" + str(error)])
        try:
            full_a, full_b = digest(canonical_ast_dump(a)), digest(canonical_ast_dump(b))
            exec_a, exec_b = _tree_hash(a), _tree_hash(b)
            stripped_a, stripped_b = _tree_hash(a, annotations=True), _tree_hash(b, annotations=True)
        except (ValueError, RecursionError, MemoryError):
            return finish("HOLD_CONTRACT_OR_IMPURE", ["STATIC_AST_REPRESENTATION_UNKNOWN"])
        result["source_reviews"].append(dict(path=pair["path"], before_sha256=pair["before"]["sha256"], after_sha256=pair["after"]["sha256"],
            before_revision=record["buggy_revision"], after_revision=record["fixed_revision"],
            parsed_ast_equal=full_a == full_b, execution_ast_before_sha256=exec_a, execution_ast_after_sha256=exec_b,
            doc_comment_stripped_ast_equal=exec_a == exec_b, annotation_stripped_ast_before_sha256=stripped_a,
            annotation_stripped_ast_after_sha256=stripped_b, annotation_stripped_ast_equal=stripped_a == stripped_b,
            annotation_runtime_equivalence="UNKNOWN" if exec_a != exec_b and stripped_a == stripped_b else "NOT_INFERRED_FROM_ERASURE"))
        parsed.append((pair, a, b, full_a == full_b, exec_a == exec_b, stripped_a == stripped_b))
    if all(v[4] for v in parsed):
        doc_runtime_risk = any(not same and (_doc_introspection(a) or _doc_introspection(b)) for _,a,b,same,_,_ in parsed)
        if doc_runtime_risk:
            return finish("HOLD_CONTRACT_OR_IMPURE", ["DOCSTRING_DECORATOR_OR_INTROSPECTION_RUNTIME_EFFECT_UNKNOWN"])
        return finish("EXCLUDE_DOC_OR_NON_CODE", ["EXECUTION_AST_IDENTICAL_IGNORING_DOCSTRINGS_AND_COMMENTS"])
    if all(v[5] for v in parsed):
        return finish("HOLD_CONTRACT_OR_IMPURE", ["ANNOTATION_ERASURE_EQUAL_BUT_RUNTIME_EFFECT_UNKNOWN"])
    general = []
    for pair, a, b, _, same, _ in parsed:
        if same:
            continue
        module_flags = sorted(set(_module_flags(a) + _module_flags(b)))
        before = {v.name:v for v in a.body if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef))}
        after = {v.name:v for v in b.body if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef))}
        changed = [name for name in sorted(before.keys() & after.keys()) if _tree_hash(ast.Module(body=[before[name]], type_ignores=[])) != _tree_hash(ast.Module(body=[after[name]], type_ignores=[]))]
        if not changed:
            general.append("CHANGED_CLASS_MODULE_STATE_OR_NO_MATCHED_FREE_FUNCTION")
        for name in changed:
            node, fixed = before[name], after[name]
            track, type_reason = _type_track(node)
            fixed_track, _ = _type_track(fixed)
            flags = sorted(set(module_flags + _function_flags(node) + _function_flags(fixed)))
            if fixed_track != track:
                flags.append("PRE_POST_INPUT_TYPE_CONTRACT_DIFFERS")
            if track is None:
                flags.append(type_reason)
            info = dict(path=pair["path"], function=name, input_signature=ast.unparse(node.args), track=track or "UNKNOWN",
                input_type="sequence_int" if track == "TRACK_SEQ_INT" else "text" if track == "TRACK_TEXT" else "UNKNOWN",
                purity="STATIC_POSSIBILITY_ONLY" if not flags else "NOT_ESTABLISHED", oracle_independence="UNKNOWN",
                oracle_possibility_basis="Simple synchronous bounded typed function shape is a review starting point; no independent Oracle has been authored or approved." if not flags else "UNKNOWN",
                reasons=flags, declared_type_evidence=type_reason)
            if not flags:
                segment = ast.get_source_segment(pair["before"]["text"], node)
                fingerprints = static_source_review(segment)["functions"]
                if len(fingerprints) != 1:
                    info["reasons"].append("FUNCTION_FINGERPRINT_UNKNOWN")
                    result["held_functions"].append(info)
                    continue
                original = dict(project=record["repository"], path=pair["path"], function=name)
                info["identity"] = dict(canonical_function_identity=digest(dict(original, revision=record["buggy_revision"])),
                    cross_revision_function_key=digest(original), normalized_ast_clone_sha256=fingerprints[0]["normalized_ast_clone_sha256"], implementation_sha256=pair["before"]["sha256"])
                result["function_candidates"].append(info)
            else:
                result["held_functions"].append(info)
    tracks = {v["track"] for v in result["function_candidates"]}
    if "TRACK_SEQ_INT" in tracks:
        result["track"] = "TRACK_SEQ_INT"
        return finish("CANDIDATE_SEQUENCE_INT", ["STATIC_TYPED_FUNCTION_CANDIDATE_ONLY_ORACLE_AND_REPRODUCTION_REQUIRED"])
    if "TRACK_TEXT" in tracks:
        result["track"] = "TRACK_TEXT"
        return finish("CANDIDATE_TEXT", ["STATIC_TYPED_FUNCTION_CANDIDATE_ONLY_ORACLE_AND_REPRODUCTION_REQUIRED"])
    reasons = general + [reason for v in result["held_functions"] for reason in v["reasons"]]
    return finish("HOLD_CONTRACT_OR_IMPURE", reasons or ["PURE_UNARY_TYPED_CONTRACT_NOT_ESTABLISHED"])
