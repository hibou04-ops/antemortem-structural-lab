"""Trusted host-side authored demo; never mounted into a Generator workspace.

Separate forms and references test the evidence pipeline. They are deliberately
curated and do not establish independent-project discovery performance.
"""
import hashlib
import time

from .schema import digest


def example_spec(names=("start", "stop"), *, folder=None):
    return {"schema": "tomolab-discovery-spec-v1", "task_id": "public-e7-range-demo",
            "inputs": [{"name": name, "role": role, "type": {"kind": "int", "min": -4, "max": 4}}
                       for name, role in zip(names, ("lower", "upper"))],
            "contract": {"id": "directed-width-v1", "operation": "nonnegative-directed-width",
                         "preconditions": [], "invariants": ["reference"], "state_model": "stateless",
                         "graph_signature": "UNKNOWN" if folder is None else example_ir(folder,names)["graph_signature"]}}


def example_origin(folder, name, oracle, lineage):
    return {"project": "authored-e7-functional-fixtures", "lineage": lineage,
            "revision": "public-fixture-v1", "oracle_id": lineage+"-reference",
            "semantics": "nonnegative-directed-width", "independence_id": "reviewed-"+lineage,
            "implementation_sha256": hashlib.sha256((folder/name).read_bytes()).hexdigest(),
            "oracle_sha256": hashlib.sha256((folder/oracle).read_bytes()).hexdigest()}


def example_ir(folder, names=("start", "stop")):
    # Explicitly public reference-model IR. It is never represented as the
    # implementation graph of a private/final target.
    from .analysis import analyze_source
    source = (folder/"public_model.py").read_text(encoding="utf-8")
    source = source.replace("start", names[0]).replace("stop", names[1])
    ir = analyze_source(source, function="reference", roles=dict(zip(names, ("lower", "upper"))))
    def portable(node):
        if isinstance(node, dict):
            return {key: portable(value) for key, value in node.items()
                    if not (key == "type_params" and value == [])}
        return [portable(value) for value in node] if isinstance(node, list) else node
    # Python 3.12 adds empty AST.type_params. The approved nongeneric model has
    # identical semantics on supported Python versions; omit that empty field.
    ir["graph"] = portable(ir["graph"])
    ir["graph_signature"] = digest(ir["graph"])
    from .predicates import validate_public_ir
    return validate_public_ir(ir)


def build_example_archive(folder, *, contradicted=False):
    from .knowledge import KnowledgeArchive, make_observation
    from ..mold.service import _load
    started = time.perf_counter()
    source_spec = example_spec(folder=folder)
    fn, _ = _load(folder/"source.py", "implementation")
    ref, _ = _load(folder/"source_oracle.py", "reference")
    source = example_origin(folder, "source.py", "source_oracle.py", "absolute-width-source")
    evidence = []
    pairs = [(2,1),(1,-1),(3,-2),(-1,-2),(1,2),(-1,1),(-2,-1),(0,0)]
    for index, (start, stop) in enumerate(pairs):
        point = {"start": start, "stop": stop}
        failed = fn(**point) != ref(**point)
        evidence.append({"kind": "FAILURE" if failed else "REFUTATION", "evidence_id": f"source-{index}",
                         "inputs": point, "invariant": "reference", "category": "mismatch", "signature": "directed-width"})
    archive = KnowledgeArchive.from_failure_log(source_spec, evidence, source, public_ir=example_ir(folder))
    spec = example_spec(("lo", "hi"), folder=folder)
    fn, _ = _load(folder/"corroboration.py", "implementation")
    ref, _ = _load(folder/"corroboration_oracle.py", "reference")
    origin = example_origin(folder, "corroboration.py", "corroboration_oracle.py", "conditional-width-validation")
    for index, (lo, hi) in enumerate([(3,1),(2,0),(0,-1),(-1,-3),(-3,-1),(0,2),(1,3),(-2,-2)]):
        point = {"lo": lo, "hi": hi}
        failed = fn(**point) != ref(**point)
        event = {"kind": "FAILURE" if failed else "REFUTATION", "evidence_id": f"independent-{index}",
                 "inputs": point, "invariant": "reference", "category": "mismatch", "signature": "directed-width"}
        archive.observe(make_observation(spec, event, origin, public_ir=example_ir(folder,("lo","hi"))), trusted_observation=True)
    calls = 32
    if contradicted:
        # An actual independently evaluated clean implementation refutes broad
        # recurrence across all implementations with the same operation contract.
        clean, _ = _load(folder/"clean.py", "implementation")
        oracle, _ = _load(folder/"target_oracle.py", "reference")
        clean_spec = example_spec(("left", "right"), folder=folder)
        origin = example_origin(folder, "clean.py", "target_oracle.py", "clean-counterevidence")
        for index, pair in enumerate([(3,1),(-1,-3),(2,0),(1,3)]):
            point = dict(zip(("left", "right"), pair))
            failed = clean(**point) != oracle(**point)
            event = {"kind": "FAILURE" if failed else "REFUTATION", "evidence_id": f"clean-{index}",
                     "inputs": point, "invariant": "reference", "category": "mismatch", "signature": "directed-width"}
            archive.observe(make_observation(clean_spec, event, origin, public_ir=example_ir(folder,("left","right"))), trusted_observation=True)
        calls += 8
    frozen = archive.freeze()
    return frozen, {"wall_seconds": time.perf_counter()-started, "actual_model_plus_target_calls": calls,
                    "provenance": "AUTHORED_PUBLIC_FUNCTIONAL_FIXTURE_NOT_REAL_PROJECT_EVALUATION",
                    "source_and_counterevidence_split": "DEVELOPMENT_ONLY",
                    "final_feedback_to_generator": 0, "archive_sha256": digest(frozen)}
