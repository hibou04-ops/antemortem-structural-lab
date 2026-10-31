"""Authored online-search fixtures and one shared comparison runner.

These are developer-known, injected functional problems.  Separate algorithms
are useful integration coverage, not independent real-project bug discoveries.
Only Source executions enter learning; evaluator labels never enter policies.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import time

from tomolab.discovery.schema import digest, canonical
from tomolab.discovery.online_schema import input_identity


def _source_numeric(values):
    if not values:
        return []
    width = max(values) - min(values)
    return [(value - min(values)) / width for value in values]


def _numeric_range(values):
    if not values:
        return []
    bottom, top = sorted(values)[0], sorted(values)[-1]
    return list(map(lambda value: (value-bottom)/(top-bottom), values))


def _numeric_peak(values):
    if not values:
        return []
    peak = max(abs(value) for value in values)
    return [value / peak for value in values]


def _range_contract(values):
    if not values:
        return []
    bottom, top = min(values), max(values)
    if bottom == top:
        return [0.0 for _ in values]
    return [(value-bottom)/(top-bottom) for value in values]


def _peak_contract(values):
    peak = max((abs(value) for value in values), default=0.0)
    if peak == 0:
        return [0.0 for _ in values]
    return [value/peak for value in values]


def _numeric_control(values):
    if not values or len(set(values)) == 1:
        return [0.0]*len(values)
    start, stop = min(values), max(values)
    return [(item-start)/(stop-start) for item in values]


def _source_container(values):
    return sum(values[:-1])


def _container_fold(values):
    total = 0
    for index in range(max(0, len(values)-1)):
        total += values[index]
    return total


def _container_max(values):
    result = None
    for value in values[:-1]:
        if result is None or value > result:
            result = value
    return result


def _sum_contract(values):
    return sum(values)


def _max_contract(values):
    return max(values, default=None)


def _container_control(values):
    total = 0
    for value in values:
        total += value
    return total


def _source_text(value):
    return value.replace("aa", "a")


def _text_groups(value):
    result = ""
    for char in value:
        if not result or char != result[-1]:
            result += char
    return result


def _text_newlines(value):
    return value.replace("\n\n", "\n")


def _identity_contract(value):
    return value


def _text_control(value):
    # Explicit lossless UTF-8 roundtrip, for this finite input alphabet.
    return value.encode("utf-8").decode("utf-8")


def _source_state(actions):
    values, snapshots = [], []
    for action in actions:
        if action["op"] == "push":
            values.append(action["value"])
        elif action["op"] == "pop" and len(values) > 1:
            values.pop(0)
        snapshots.append(list(values))
    return snapshots


def _state_deque(actions):
    entries, snapshots = deque(), []
    for action in actions:
        if action["op"] == "push":
            entries.append(action["value"])
        elif action["op"] == "pop" and len(entries) != 1 and entries:
            entries.popleft()
        snapshots.append(list(entries))
    return snapshots


def _state_cursor(actions):
    entries, cursor, snapshots = {}, 0, []
    next_key = 0
    for action in actions:
        if action["op"] == "push":
            entries[next_key] = action["value"]
            next_key += 1
        elif action["op"] == "pop" and len(entries) > 1:
            del entries[cursor]
            cursor += 1
        snapshots.append([entries[key] for key in sorted(entries)])
    return snapshots


def _queue_contract(actions):
    # Immutable tuple model; every invocation starts empty.
    state, snapshots = (), []
    for action in actions:
        if action["op"] == "push":
            state += (action["value"],)
        elif action["op"] == "pop":
            state = state[1:]
        snapshots.append(list(state))
    return snapshots


def _state_control(actions):
    state, snapshots = deque(), []
    for action in actions:
        if action["op"] == "push":
            state.append(action["value"])
        elif action["op"] == "pop" and state:
            state.popleft()
        snapshots.append(list(state))
    return snapshots


def _source_graph(graph):
    vertices = {node for edge in graph["edges"] for node in edge}
    groups = [{node} for node in vertices]
    for left, right in graph["edges"]:
        a = next(group for group in groups if left in group)
        b = next(group for group in groups if right in group)
        if a is not b:
            a.update(b)
            groups.remove(b)
    return len(groups)


def _graph_dfs(graph):
    adjacency = {}
    for left, right in graph["edges"]:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    seen, count = set(), 0
    for start in adjacency:
        if start in seen:
            continue
        count += 1
        stack = [start]
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(adjacency[current] - seen)
    return count


def _graph_union(graph):
    active = {node for edge in graph["edges"] for node in edge}
    roots = dict.fromkeys(active)
    for node in active:
        roots[node] = node
    for left, right in graph["edges"]:
        while roots[left] != left:
            left = roots[left]
        while roots[right] != right:
            right = roots[right]
        roots[left] = right
    for node in active:
        while roots[node] != roots[roots[node]]:
            roots[node] = roots[roots[node]]
    return len({roots[node] for node in active})


def _component_contract(graph):
    reachable = [[left == right for right in range(graph["n"])]
                 for left in range(graph["n"])]
    for left, right in graph["edges"]:
        reachable[left][right] = reachable[right][left] = True
    for middle in range(graph["n"]):
        for left in range(graph["n"]):
            for right in range(graph["n"]):
                reachable[left][right] |= reachable[left][middle] and reachable[middle][right]
    return sum(not any(reachable[node][prior] for prior in range(node))
               for node in range(graph["n"]))


def _graph_control(graph):
    groups = [{node} for node in range(graph["n"])]
    for left, right in graph["edges"]:
        first = next(group for group in groups if left in group)
        second = next(group for group in groups if right in group)
        if first is not second:
            first.update(second)
            groups.remove(second)
    return len(groups)


@dataclass(frozen=True)
class Case:
    id: str
    axis: str
    mechanism: str
    role: str
    contract: dict
    target: object
    oracle: object
    lineage: str
    origin: str = "AUTHORED_INJECTED_FUNCTIONAL"

    def metadata(self):
        from tomolab.discovery.analysis import analyze_source
        target_source = inspect.getsource(self.target)
        implementation = hashlib.sha256(target_source.encode()).hexdigest()
        identity = dict(
            canonical_function_identity=digest({"case": self.id, "source": implementation}),
            cross_revision_function_key=digest({"authored_lineage": self.lineage}),
            normalized_ast_clone_sha256=analyze_source(target_source, self.target.__name__)["graph_signature"],
            implementation_sha256=implementation,
        )
        return dict(id=self.id, axis=self.axis, mechanism=self.mechanism, role=self.role,
                    contract=deepcopy(self.contract), origin=self.origin, lineage=self.lineage,
                    identity=identity, oracle_sha256=hashlib.sha256(
                        inspect.getsource(self.oracle).encode()).hexdigest(),
                    project_independence="NOT_ESTABLISHED", developer_known=True)


def cases():
    """Five Source fixtures, ten target algorithms and five clean controls."""
    families = [
        ("numerical", "ZERO_SCALE", dict(kind="sequence_float", low=-4, high=4,
                                          min_size=0, max_size=8),
         (_source_numeric, _range_contract),
         ((_numeric_range, _range_contract), (_numeric_peak, _peak_contract)),
         (_numeric_control, _range_contract)),
        ("container", "TERMINAL_ELEMENT_OMISSION", dict(kind="sequence_int", low=-4,
                                                          high=4, min_size=0, max_size=8),
         (_source_container, _sum_contract),
         ((_container_fold, _sum_contract), (_container_max, _max_contract)),
         (_container_control, _sum_contract)),
        ("serialization", "LOSSY_DUPLICATE_NORMALIZATION", dict(kind="text",
                  min_size=0, max_size=8, alphabet="ab01\n"),
         (_source_text, _identity_contract),
         ((_text_groups, _identity_contract), (_text_newlines, _identity_contract)),
         (_text_control, _identity_contract)),
        ("state", "LAST_ITEM_POP_OMISSION", dict(kind="state_trace", low=-4, high=4,
                  min_size=0, max_size=8, actions=["push", "pop", "peek"]),
         (_source_state, _queue_contract),
         ((_state_deque, _queue_contract), (_state_cursor, _queue_contract)),
         (_state_control, _queue_contract)),
        ("graph", "ISOLATED_VERTEX_OMISSION", dict(kind="graph", max_nodes=6,
                                                   min_size=0, max_size=12),
         (_source_graph, _component_contract),
         ((_graph_dfs, _component_contract), (_graph_union, _component_contract)),
         (_graph_control, _component_contract)),
    ]
    result = []
    for axis, mechanism, contract, source, targets, control in families:
        for role, index, pair in [("SOURCE", 0, source),
                *(("TARGET", i+1, pair) for i, pair in enumerate(targets)),
                ("CONTROL", 0, control)]:
            name = f"authored-{axis}-{role.lower()}-{index}"
            result.append(Case(name, axis, mechanism, role, deepcopy(contract), *pair,
                               lineage="e9-manually-authored-"+name))
    return result


def default_config():
    return dict(schema="tomolab-online-comparison-v1", scope="EXPERIMENTAL_PROBE",
        methods=["A", "B", "C", "D"], seeds=[2081, 2099, 2131], budget=48,
        shrink_budget=8, max_seconds=30.0,
        source=dict(method="B", seed=71, budget=64, shrink_budget=8),
        evaluations=["IMPLEMENTATION_TRANSFER", "LEAVE_ONE_MECHANISM_OUT"],
        target_state_policy="RESET_EACH_RUN_SAME_FROZEN_SOURCE_PROVIDER",
        source_profile="AUTHORED_FUNCTIONAL_DEVELOPMENT",
        benchmark_independence="REAL_PROJECT_MINIMUM_NOT_MET",
        knowledge_status="EMPIRICAL_SEARCH_GUIDANCE_NOT_QUALIFIED",
        primary_comparison="E9_D_VS_E9_C",
        success=dict(require_more_detected_defects=True,
                     forbid_C_detected_D_missed=True,
                     maximum_wall_ratio=None,
                     overhead_target="NO_ACCEPTABLE_OVERHEAD_THRESHOLD_ESTABLISHED; COST_REPORTED_NO_COST_SUCCESS_CLAIM"),
        final_target_authorized=False, publication_authorized=False,
        allow_release=False)


HISTORICAL_CRITERIA = dict(
    primary="UNIQUE_HISTORICAL_DEFECTS",
    DETECTION_GAIN="MORE_UNIQUE_D_DEFECTS_AND_NO_C_ONLY_RUN",
    QUERY_EFFICIENCY_GAIN="NO_C_ONLY_RUN_AND_ALL_JOINT_D_CALLS_LE_C_WITH_ONE_STRICTLY_LOWER",
    WALL_TIME_GAIN="DESCRIPTIVE_ONLY_NO_PREDECLARED_COST_MARGIN",
    NEGATIVE_TRANSFER="C_ONLY_RUN_OR_HIGHER_D_FIRST_CALLS_OR_HIGHER_D_TOTAL_WALL",
    ADDED_VALUE_OVER_C="REPORT_DETECTION_QUERY_AND_COST_SEPARATELY_NO_COMPOSITE_EFFICIENCY_SUCCESS")


def historical_config(*, budgets, seeds, source_budget, source_seed,
                      shrink_budget=8, max_seconds=30):
    """Build a bounded profile after a Source/development budget check.

    No cost margin is invented: wall time remains a predeclared descriptive
    result, including when an otherwise valid detection/query gain is found.
    """
    if not isinstance(budgets,(list,tuple)) or not budgets:
        raise ValueError("Source/development-tested common budgets must be supplied explicitly")
    value = default_config()
    value.update(schema="tomolab-online-comparison-v2", corpus_profile="REVIEWED_HISTORICAL_DEFECTS",
        budgets=list(budgets), budget=budgets[0], seeds=list(seeds),
        shrink_budget=shrink_budget, max_seconds=max_seconds,
        source=dict(method="B",seed=source_seed,budget=source_budget,shrink_budget=shrink_budget),
        source_profile="REVIEWED_HISTORICAL_SOURCE",
        benchmark_independence="REVIEWED_PROVENANCE_NOT_INFERRED_FROM_PROJECT_COUNT",
        criteria=deepcopy(HISTORICAL_CRITERIA))
    return validate_config(value)


def validate_config(config):
    expected = default_config()
    historical = config.get("schema") == "tomolab-online-comparison-v2" if isinstance(config,dict) else False
    if historical:
        expected.update(schema="tomolab-online-comparison-v2",corpus_profile="REVIEWED_HISTORICAL_DEFECTS",
            budgets=[],criteria=deepcopy(HISTORICAL_CRITERIA),
            source_profile="REVIEWED_HISTORICAL_SOURCE",
            benchmark_independence="REVIEWED_PROVENANCE_NOT_INFERRED_FROM_PROJECT_COUNT")
    if not isinstance(config,dict) or set(config) != set(expected) or config["schema"] != expected["schema"]:
        raise ValueError("registered common online configuration schema required")
    for field in ("scope", "methods", "evaluations", "target_state_policy",
                  "source_profile", "benchmark_independence", "knowledge_status",
                  "primary_comparison", "final_target_authorized",
                  "publication_authorized", "allow_release"):
        if config[field] != expected[field]:
            raise ValueError("unsupported evaluation scope or gate")
    if (not isinstance(config["seeds"], list) or not config["seeds"] or
        len(set(config["seeds"])) != len(config["seeds"]) or
        any(type(seed) is not int or not 0 <= seed < 2**32 for seed in config["seeds"])):
        raise ValueError("distinct bounded integer seeds required")
    for key in ("budget", "shrink_budget"):
        if type(config[key]) is not int or not 0 <= config[key] <= 2048:
            raise ValueError("bounded integer call budget required")
    if config["budget"] < 8 or config["shrink_budget"] > config["budget"]//2:
        raise ValueError("confirmation and base-search budget required")
    if type(config["max_seconds"]) not in (int, float) or not 0 < config["max_seconds"] <= 120:
        raise ValueError("bounded cooperative wall deadline required")
    source = config["source"]
    if set(source) != {"method", "seed", "budget", "shrink_budget"} or source["method"] != "B":
        raise ValueError("Source must use the common unlearned online engine")
    if any(type(source[key]) is not int for key in ("seed", "budget", "shrink_budget")):
        raise ValueError("Source seed and budgets require integers")
    if not 0 <= source["seed"] < 2**32 or not 8 <= source["budget"] <= 2048 or not 0 <= source["shrink_budget"] <= source["budget"]//2:
        raise ValueError("Source generation budget outside supported bounds")
    success = config["success"]
    if not isinstance(success, dict) or set(success) != set(expected["success"]):
        raise ValueError("bounded predeclared success criteria required")
    if success["require_more_detected_defects"] is not True or success["forbid_C_detected_D_missed"] is not True:
        raise ValueError("primary criterion requires distinct defect improvement without C-only misses")
    ratio = success["maximum_wall_ratio"]
    if ratio is not None:
        import math
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 1 <= ratio <= 10:
            raise ValueError("finite predeclared overhead threshold required")
    if success["overhead_target"] != expected["success"]["overhead_target"]:
        raise ValueError("cost acceptance status must be explicit")
    if historical:
        if config["corpus_profile"] != expected["corpus_profile"] or config["criteria"] != HISTORICAL_CRITERIA:
            raise ValueError("historical classification and all five predeclared criteria required")
        budgets=config["budgets"]
        if (not isinstance(budgets,list) or not 1 <= len(budgets) <= 2
            or any(type(v) is not int or not 8 <= v <= 2048 or config["shrink_budget"] > v//2 for v in budgets)
            or budgets != sorted(set(budgets)) or config["budget"] != budgets[0]):
            raise ValueError("one or two ordered common budgets must be fixed before Target results")
        if success["maximum_wall_ratio"] is not None:
            raise ValueError("historical profile predeclares descriptive cost without an acceptance margin")
    return deepcopy(config)


def _corpus(config, corpus):
    if corpus is None:
        if config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
            raise ValueError("reviewed historical corpus must be supplied by the approved execution boundary")
        corpus=cases()
    rows=list(corpus)
    if not rows or len({case.id for case in rows}) != len(rows):
        raise ValueError("nonempty individually identified corpus required")
    for case in rows:
        if case.role not in ("SOURCE","TARGET","CONTROL"):
            raise ValueError("Source, Target and clean control roles must remain distinct")
        if config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
            metadata=case.metadata()
            required={"project","bug_identity","mechanism_family","input_kind",
                      "implementation_lineage","license","buggy_revision","fixed_revision"}
            if not required <= metadata.keys() or any(not metadata[name] for name in required):
                raise ValueError("historical cases require original/fixed provenance and independent classifications")
            if metadata["input_kind"] != case.contract["kind"] or metadata["mechanism_family"] != case.mechanism:
                raise ValueError("mechanism and input kind metadata disagree with their separate contracts")
    if config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
        source_bugs={c.metadata()["bug_identity"] for c in rows if c.role=="SOURCE"}
        target_bugs={c.metadata()["bug_identity"] for c in rows if c.role=="TARGET"}
        if not source_bugs or not target_bugs or source_bugs & target_bugs:
            raise ValueError("observed Source bugs and registered Target bugs must be disjoint")
    return rows


def fold_plan(config, corpus, prepared=None):
    """Use public contracts and frozen Source only, never Target outcomes."""
    from tomolab.discovery.online_schema import common_operators
    rows=_corpus(config,corpus)
    sources=[case for case in rows if case.role=="SOURCE"]
    historical=config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS"
    result=[]
    for evaluation in config["evaluations"]:
        for case in rows:
            if case.role=="SOURCE":
                continue
            family=case.mechanism if historical else case.axis
            fold="ALL" if evaluation=="IMPLEMENTATION_TRANSFER" else family
            excluded=[s for s in sources if fold!="ALL" and (s.mechanism if historical else s.axis)==fold]
            remaining=[s for s in sources if fold=="ALL" or (s.mechanism if historical else s.axis)!=fold]
            contact=[s for s in remaining if s.contract["kind"]==case.contract["kind"]
                     and set(common_operators(s.contract["kind"])) & set(common_operators(case.contract["kind"]))]
            mold=(prepared or {}).get("molds",{}).get(fold)
            retained=None if mold is None else sum(r["kind"]==case.contract["kind"] for r in mold.get("rules",[]))
            classification=("ROUTING_FALLBACK_CONTROL" if not contact else
                "MECHANISM_ABSENT_FROM_SOURCE" if historical and fold!="ALL" and not excluded else
                "TRANSFER_PROBE")
            result.append(dict(evaluation=evaluation,fold=fold,case_id=case.id,
                mechanism_family=case.mechanism,input_kind=case.contract["kind"],
                source_ids=[s.id for s in remaining],type_grammar_contact=bool(contact),
                excluded_source_ids=[s.id for s in excluded],excluded_source_count=len(excluded),
                compatible_source_ids=[s.id for s in contact],retained_type_rules=retained,
                classification=classification,
                execute=not(historical and evaluation=="LEAVE_ONE_MECHANISM_OUT" and
                            (not contact or not excluded))))
    return result


def prepare_sources(config, *, corpus=None, executor=None):
    """Collect real Source feedback, then compile six bounded providers once."""
    from tomolab.discovery.online_engine import run_online
    from tomolab.discovery.online_learning import learn_mold
    config = validate_config(config)
    corpus=_corpus(config,corpus)
    execute=executor or run_online
    execution_boundary=None
    if config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
        from tomolab.historical import require_reviewed_container
        execution_boundary=require_reviewed_container()["binding"]
    started = time.perf_counter()
    records, runs = [], []
    for case in (case for case in corpus if case.role == "SOURCE"):
        options=dict(method="B", seed=config["source"]["seed"],
            budget=config["source"]["budget"], shrink_budget=config["source"]["shrink_budget"],
            max_seconds=config["max_seconds"])
        if config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
            import inspect
            original=getattr(case.target,"upstream_function",None)
            options["mode"]="structural" if inspect.isfunction(original) else "black_box"
            if inspect.isfunction(original):options["inspection_target"]=original
        row = execute(case.target, case.oracle, case.contract,**options)
        runs.append(dict(case=case.metadata(), run=row))
        for event in row["observations"]:
            records.append(dict(input=deepcopy(event["input"]), status=event["status"],
                contract=deepcopy(case.contract), source_identity=case.metadata()["identity"]["implementation_sha256"],
                source_axis=case.axis,source_mechanism=case.mechanism,
                source_project=case.metadata().get("project","AUTHORED_FUNCTIONAL"),
                input_digest=input_identity(event["input"])))
    validate_prepared_inputs(dict(records=records,source_runs=runs))
    source_seconds = time.perf_counter()-started
    learned, learning_cost, learning_audits, learning_metrics = {}, {}, {}, {}
    historical=config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS"
    folds = (["ALL", *sorted({p["fold"] for p in fold_plan(config,corpus) if p["execute"] and p["fold"]!="ALL"})]
             if historical else ["ALL", *sorted({case.axis for case in corpus})])
    for fold in folds:
        training = [record for record in records if fold == "ALL" or record["source_mechanism" if historical else "source_axis"] != fold]
        tick = time.perf_counter()
        if historical:
            learning_audits[fold],learning_metrics[fold]={},{}
            learned[fold] = learn_mold(training,audit=learning_audits[fold],metrics=learning_metrics[fold])
        else:
            learned[fold] = learn_mold(training)
        learning_cost[fold] = time.perf_counter()-tick
    result=dict(schema="tomolab-online-source-preparation-v1",config_digest=digest(config),
        records=records, source_runs=runs, molds=learned,
        cost=dict(source_collection_seconds=source_seconds,
                  source_learning_seconds=learning_cost,
                  wall_seconds=time.perf_counter()-started),
        target_calls=sum(row["run"]["target_calls"] for row in runs),
        oracle_calls=sum(row["run"]["oracle_calls"] for row in runs),
        target_evaluation_calls=0, allow_release=False)
    if historical:
        result["execution_boundary"]=deepcopy(execution_boundary)
        result["fold_plan"]=fold_plan(config,corpus,result)
        result["learning_audits"]=learning_audits
        result["learning_metrics"]=learning_metrics
        result["coverage"]=source_coverage(corpus,result)
    return result


def source_coverage(corpus, prepared):
    """Pre-Target summary; does not assert that a rule will help a Target."""
    source_counts={}
    for case in corpus:
        if case.role!="SOURCE":continue
        metadata=case.metadata()
        key=canonical(dict(project=metadata.get("project"),bug_identity=metadata.get("bug_identity"),
            input_kind=case.contract["kind"],mechanism_family=case.mechanism))
        source_counts[key]=source_counts.get(key,0)+1
    models={}
    for fold,mold in prepared["molds"].items():
        summary=prepared.get("learning_audits",{}).get(fold,{}).get("ranked_rule_summaries",[])
        selected_ids={rule["rule_id"] for rule in mold["rules"]}
        groups={"selected":{},"omitted":{}}
        for rule in summary:
            key=canonical({name:rule[name] for name in ("kind","edit_composition","preconditions")})
            category="selected" if rule["rule_id"] in selected_ids else "omitted"
            groups[category][key]=groups[category].get(key,0)+1
        models[fold]=dict(rules=len(mold["rules"]),omitted_rules=mold["omitted_rules"],
            compact_bytes=len(canonical(mold).encode())+1,
            ranked_summary_status="RECORDED" if summary or not mold["rules"] else "UNAVAILABLE",
            kinds=sorted({r["kind"] for r in mold["rules"]}),breakdown=groups)
    return dict(source_groups=source_counts,models=models,
        target_contract_routing=deepcopy(prepared.get("fold_plan",[])),
        measured_before_registered_target_runs=True,target_calls=0,oracle_calls=0)


def _training(prepared, fold, *, historical=False):
    return [row for row in prepared["records"] if fold == "ALL" or row["source_mechanism" if historical else "source_axis"] != fold]


def _replays(records, contract, *, compatible_domain=False):
    from tomolab.discovery.online_schema import validate_input
    seen, result = set(), []
    for row in records:
        compatible=(row["contract"].get("kind")==contract.get("kind") and validate_input(row["input"],contract)
                    if compatible_domain else row["contract"]==contract)
        if row["status"] != "FAILURE" or not compatible:
            continue
        token = input_identity(row["input"])
        if token not in seen:
            seen.add(token)
            result.append(deepcopy(row["input"]))
    return result


def validate_prepared_inputs(prepared):
    """Bind ordered input semantics in addition to canonical metadata hashes."""
    if not isinstance(prepared,dict) or not isinstance(prepared.get("records"),list) or not isinstance(prepared.get("source_runs"),list):
        raise ValueError("recorded Source observations and executions required")
    def check(row):
        if not isinstance(row,dict) or "input" not in row or row.get("input_digest") != input_identity(row["input"]):
            raise ValueError("Source input identity or mapping insertion order changed")
    for row in prepared["records"]:
        check(row)
    for source in prepared["source_runs"]:
        run=source.get("run",{})
        if not isinstance(run.get("observations"),list):
            raise ValueError("Source execution observations required")
        for row in run["observations"]:
            check(row)
        for row in run.get("confirmed_failures",[]):
            check(row)
        shrink=run.get("shrinking",{})
        if shrink.get("witness") is not None:
            index=shrink.get("witness_reference_event")
            if type(index) is not int or not 0 <= index < len(run["observations"]):
                raise ValueError("Source shrink witness requires its actual observation reference")
            if input_identity(shrink["witness"]) != run["observations"][index]["input_digest"]:
                raise ValueError("Source shrink witness mapping order differs from its observation")
    return True


def run_comparison(config, prepared, *, event_path=None, corpus=None, executor=None):
    """Run every preregistered problem; no result-dependent case replacement."""
    from tomolab.discovery.online_engine import run_online
    config = validate_config(config)
    corpus=_corpus(config,corpus)
    execute=executor or run_online
    historical=config.get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS"
    if historical:
        from tomolab.historical import require_reviewed_container
        if require_reviewed_container()["binding"] != prepared.get("execution_boundary"):
            raise PermissionError("Source preparation and Target comparison require the same reviewed container binding")
    validate_prepared_inputs(prepared)
    if prepared.get("config_digest") != digest(config) or prepared.get("target_evaluation_calls") != 0:
        raise ValueError("Source preparation and registered configuration differ")
    expected_folds = ({"ALL",*(p["fold"] for p in fold_plan(config,corpus) if p["execute"])}
                      if historical else {"ALL", *(case.axis for case in corpus)})
    if set(prepared.get("molds", {})) != expected_folds:
        raise ValueError("all pre-evaluation frozen Source providers required")
    handle = None
    if event_path is not None:
        handle = Path(event_path).open("x", encoding="utf-8", newline="\n")
    started = time.perf_counter()
    runs = []
    plan=fold_plan(config,corpus,prepared)
    if historical and prepared.get("fold_plan") != plan:
        raise ValueError("public contract/Source-only fold applicability changed after preparation")
    try:
        evaluation_cases = [case for case in corpus if case.role != "SOURCE"]
        for evaluation in config["evaluations"]:
            for case_index, case in enumerate(evaluation_cases):
                routing=next(p for p in plan if p["evaluation"]==evaluation and p["case_id"]==case.id)
                if not routing["execute"]:
                    continue
                fold = routing["fold"]
                records = _training(prepared, fold,historical=historical)
                replays = _replays(records, case.contract,compatible_domain=historical)
                for budget in config.get("budgets",[config["budget"]]):
                    for seed_index, seed in enumerate(config["seeds"]):
                        # Rotate before observations. D gets no extra calls/time.
                        offset = (case_index+seed_index) % 4
                        methods = config["methods"][offset:]+config["methods"][:offset]
                        for method in methods:
                            options=dict(method=method, seed=seed, budget=budget,
                                shrink_budget=config["shrink_budget"], max_seconds=config["max_seconds"],
                                mold=deepcopy(prepared["molds"][fold]) if method == "D" else None,
                                replays=deepcopy(replays) if method in ("C", "D") else ())
                            if historical:
                                # Public original AST/root coverage is shared by
                                # all four methods. Adapter mapping stays unknown.
                                import inspect
                                original=getattr(case.target,"upstream_function",None)
                                options["mode"]="structural" if inspect.isfunction(original) else "black_box"
                                if inspect.isfunction(original):options["inspection_target"]=original
                            tick=time.perf_counter()
                            row = execute(case.target, case.oracle, deepcopy(case.contract),**options)
                            run = dict(evaluation=evaluation, fold=fold, case=case.metadata(),
                                seed=seed, method=("E9_R1_" if historical else "E9_")+method, result=row)
                            if historical:
                                run.update(budget=budget,routing=deepcopy(routing),
                                    executor_call_wall_seconds=time.perf_counter()-tick)
                            if handle is not None:
                                handle.write(json.dumps(run,ensure_ascii=True,allow_nan=False,
                                                        separators=(",",":"))+"\n")
                                handle.flush()
                            runs.append(run)
    finally:
        if handle is not None:
            handle.close()
    result = dict(schema="tomolab-online-comparison-results-v1",config=deepcopy(config),
        config_digest=digest(config), source_preparation_digest=digest(prepared),
        runs=runs, target_execution_wall_seconds=time.perf_counter()-started,
        source_cost=deepcopy(prepared["cost"]),
        source_target_calls=prepared["target_calls"],source_oracle_calls=prepared["oracle_calls"],
        benchmark_limits=dict(real_project_defects=0,independent_projects=0,
            authored_targets=10,authored_clean_controls=5,coarse_mechanism_families=5,
            human_blind=False,held_out_runtime_source_only=True),allow_release=False)
    if historical:
        result["generation"]="E9_R1"
        result["fold_plan"]=plan
        result["benchmark_limits"]=dict(real_project_defects=len({c.metadata()["bug_identity"] for c in corpus if c.role=="TARGET"}),
            projects=sorted({c.metadata()["project"] for c in corpus}),
            source_defects=len({c.metadata()["bug_identity"] for c in corpus if c.role=="SOURCE"}),
            target_implementations=len({c.metadata()["implementation_lineage"] for c in corpus if c.role=="TARGET"}),
            mechanism_families=sorted({c.mechanism for c in corpus if c.role=="TARGET"}),
            input_kinds=sorted({c.contract["kind"] for c in corpus}),
            clean_controls=sum(c.role=="CONTROL" for c in corpus),human_blind=False,
            discovery_class="HISTORICAL_DEFECT_REDISCOVERY_NOT_NEW_CURRENT_DEFECT",
            project_independence="ASSESS_FROM_PINNED_CODE_LINEAGE_NOT_PROJECT_COUNT")
    result["summary"] = summarize(result)
    return result


def summarize(result):
    if result["config"].get("corpus_profile") == "REVIEWED_HISTORICAL_DEFECTS":
        summary={}
        for evaluation in result["config"]["evaluations"]:
            budgets={}
            for budget in result["config"]["budgets"]:
                selected=[row for row in result["runs"] if row["evaluation"]==evaluation and row["budget"]==budget]
                if not selected:
                    continue
                # The same aggregation code is used for the authored v1 and
                # historical corpus. Method labels are a provenance boundary.
                normalized=[]
                for row in selected:
                    value=dict(row,method=row["method"].replace("E9_R1_","E9_",1))
                    normalized.append(value)
                view=dict(result,runs=normalized,config=dict(result["config"],
                    corpus_profile="SUMMARY_ONLY",evaluations=[evaluation]))
                part=summarize(view)[evaluation]
                part["methods"]={key.replace("E9_","E9_R1_",1):value for key,value in part["methods"].items()}
                for comparison in part["paired"].values():
                    comparison["outcome"]=comparison["outcome"].replace("AUTHORED_SCOPE","HISTORICAL_SCOPE")
                for method,group in part["methods"].items():
                    rows=[r for r in selected if r["method"]==method]
                    found=[r for r in rows if r["case"]["role"]=="TARGET" and r["result"]["first_confirmed_failure"] is not None]
                    group["detected_historical_defects"]=len({r["case"]["bug_identity"] for r in found})
                    group.pop("detected_authored_defects",None)
                    group["historical_defects"]=len({r["case"]["bug_identity"] for r in rows if r["case"]["role"]=="TARGET"})
                    group["discovery_class"]="HISTORICAL_DEFECT_REDISCOVERY"
                    group["generated_failure_attribution"]="CANDIDATE_UNTIL_PUBLIC_CONTRACT_FIX_AND_MECHANISM_REVIEW"
                    group["fixed_control_disagreements"]=[dict(case=r["case"]["id"],seed=r["seed"],
                        first_confirmation=r["result"]["first_confirmed_failure"],
                        status="UNRESOLVED_CONTRACT_DIFFERENCE") for r in rows
                        if r["case"]["role"]=="CONTROL" and r["result"]["first_confirmed_failure"] is not None]
                    group.pop("control_false_positives",None)
                    group["executor_call_wall_seconds"]=sum(r["executor_call_wall_seconds"] for r in rows)
                    for name in ("learned_rule_matches","learned_valid_proposals","learned_changed_common_proposals",
                                 "learned_changed_common_executions","learned_invalid_results",
                                 "learned_duplicate_results","learned_unexecutable_results"):
                        group[name]=sum(r["result"].get("scheduler",{}).get(name,0) for r in rows)
                part["criteria"]=assess_historical_gain(selected,result["config"]["criteria"])
                part["transfer_probe_criteria"]=assess_historical_gain(
                    [r for r in selected if r["routing"]["classification"]=="TRANSFER_PROBE"],
                    result["config"]["criteria"])
                part["applicability"]=dict(
                    type_grammar_contact_cases=len({r["case"]["id"] for r in selected if r["routing"]["type_grammar_contact"]}),
                    retained_rule_cases=len({r["case"]["id"] for r in selected if r["routing"]["retained_type_rules"]}),
                    actual_matching_rules=sum(r["result"].get("scheduler",{}).get("learned_rule_matches",0) for r in selected),
                    actual_different_candidates=sum(r["result"].get("scheduler",{}).get("learned_changed_common_executions",0) for r in selected))
                budgets[str(budget)]=part
            summary[evaluation]=dict(budgets=budgets,
                status="EVALUATED" if budgets else "NOT_TESTABLE_WITH_CURRENT_CORPUS",
                routing_controls=[p for p in result["fold_plan"] if p["evaluation"]==evaluation
                                  and p["classification"]=="ROUTING_FALLBACK_CONTROL"],
                no_applicable_lomo=(evaluation=="LEAVE_ONE_MECHANISM_OUT" and
                    not any(p["execute"] for p in result["fold_plan"] if p["evaluation"]==evaluation)),
                external_generalization="NOT_ESTABLISHED_BY_HISTORICAL_REDISCOVERY_ALONE")
        return summary
    summary = {}
    for evaluation in result["config"]["evaluations"]:
        rows = [row for row in result["runs"] if row["evaluation"] == evaluation]
        methods = {}
        for method in result["config"]["methods"]:
            selected = [row for row in rows if row["method"] == "E9_"+method]
            positive = [row for row in selected if row["case"]["role"] == "TARGET"]
            detected = [row for row in positive if row["result"]["first_confirmed_failure"] is not None]
            errors = sum(row["result"].get("status") != "COMPLETE" or
                         row["result"].get("execution_errors", 0) > 0 or
                         row["result"].get("oracle_errors", 0) > 0 for row in selected)
            methods["E9_"+method] = dict(
                target_problems=len({row["case"]["id"] for row in positive}),
                clean_controls=len({row["case"]["id"] for row in selected if row["case"]["role"] == "CONTROL"}),
                detected_authored_defects=len({row["case"]["id"] for row in detected}),
                detected_mechanism_families=len({row["case"]["mechanism"] for row in detected}),
                detected_runs=len(detected),target_runs=len(positive),
                missed_runs=len(positive)-len(detected),error_runs=errors,
                unknown_observations=sum(row["result"].get("unknown", 0) for row in selected),
                oracle_errors=sum(row["result"].get("oracle_errors", 0) for row in selected),
                execution_errors=sum(row["result"].get("execution_errors", 0) for row in selected),
                invalid_inputs=sum(row["result"].get("invalid_inputs", 0) for row in selected),
                duplicate_candidates=sum(row["result"].get("duplicate_candidates", 0) for row in selected),
                source_replay_calls=sum(row["result"].get("source_replay_calls", 0) for row in selected),
                new_valid_inputs=sum(row["result"].get("new_valid_inputs", 0) for row in selected),
                learned_rule_uses=sum(sum(bool(event.get("rule_id")) for event in row["result"].get("events", [])) for row in selected),
                learned_rule_proposals=sum(len(row["result"].get("scheduler", {}).get("learned_rule_uses", [])) for row in selected),
                learned_target_calls=sum(sum(event.get("origin") == "source_learned_policy" for event in row["result"].get("observations", [])) for row in selected),
                learned_lookups=sum(row["result"].get("scheduler", {}).get("learned_lookups", 0) for row in selected),
                guidance_not_applicable=sum(row["result"].get("scheduler", {}).get("guidance_not_applicable", 0) for row in selected),
                invalid_guidance=sum(row["result"].get("scheduler", {}).get("guidance_rejected", 0) for row in selected),
                duplicate_guidance=sum(row["result"].get("scheduler", {}).get("duplicate_guidance", 0) for row in selected),
                control_false_positives=sum(bool(row["result"]["first_confirmed_failure"]) for row in selected if row["case"]["role"] == "CONTROL"),
                target_calls=sum(row["result"]["target_calls"] for row in selected),
                oracle_calls=sum(row["result"]["oracle_calls"] for row in selected),
                target_wall_seconds=sum(row["result"]["cost"]["wall_seconds"] for row in selected),
                first_confirmed=[dict(case=row["case"]["id"],seed=row["seed"],
                                      measurement=row["result"]["first_confirmed_failure"])
                                 for row in positive])
        paired = {}
        for left, right, label in (("A", "B", "INNER_LOOP_GAIN"),("B","C","REPLAY_GAIN"),("C","D","OUTER_TRANSFER_GAIN")):
            mapping = {(row["case"]["id"], row["seed"], row["method"]): row for row in rows if row["case"]["role"] == "TARGET"}
            better, worse, equal = [], [], []
            for case, seed in sorted({(row["case"]["id"],row["seed"]) for row in rows if row["case"]["role"] == "TARGET"}):
                a=mapping[(case,seed,"E9_"+left)]["result"]["first_confirmed_failure"]
                b=mapping[(case,seed,"E9_"+right)]["result"]["first_confirmed_failure"]
                record=dict(case=case,seed=seed)
                (better if b and not a else worse if a and not b else equal).append(record)
            paired[label]=dict(improved_detection=better,negative_transfer=worse,equal_detection=equal,
                outcome="OBSERVED_AUTHORED_SCOPE_GAIN" if better and not worse else
                    "MIXED_AUTHORED_SCOPE" if better else "NO_ADDITIONAL_DETECTION_OBSERVED",
                external_generalization="NOT_ESTABLISHED")
        summary[evaluation] = dict(methods=methods,paired=paired)
    return summary


def assess_historical_gain(rows, criteria):
    """Frozen logical criteria, with every miss kept and no fitted threshold."""
    if criteria != HISTORICAL_CRITERIA:
        raise ValueError("gain logic must be fixed before registered execution")
    targets=[r for r in rows if r["case"]["role"]=="TARGET"]
    unresolved_controls=[dict(case=r["case"]["id"],seed=r["seed"],method=r["method"],
        status="UNRESOLVED_CONTRACT_DIFFERENCE") for r in rows
        if r["case"]["role"]=="CONTROL" and r["result"]["first_confirmed_failure"] is not None]
    incomparable=[dict(case=r["case"]["id"],seed=r["seed"],method=r["method"],
        status=r["result"].get("status","COMPLETE")) for r in rows
        if (r["method"] in ("E9_R1_C","E9_R1_D") or r["case"]["role"]=="CONTROL") and
        (r["result"].get("status","COMPLETE")!="COMPLETE" or
         any(r["result"].get(key,0)>0 for key in ("unknown","oracle_errors","execution_errors")))]
    def side(method):
        return {(r["case"]["id"],r["seed"]):r for r in targets if r["method"]=="E9_R1_"+method}
    c,d=side("C"),side("D")
    if set(c)!=set(d):
        raise ValueError("paired C/D execution identities must be complete")
    c_only,d_only,joint,both_missed=[],[],[],[]
    c_defects,d_defects=set(),set()
    for key in sorted(c):
        cf=c[key]["result"]["first_confirmed_failure"]
        df=d[key]["result"]["first_confirmed_failure"]
        item=dict(case=key[0],seed=key[1])
        if cf is not None:c_defects.add(c[key]["case"]["bug_identity"])
        if df is not None:d_defects.add(d[key]["case"]["bug_identity"])
        if cf is not None and df is not None:
            item.update(C_calls=cf["target_calls"],D_calls=df["target_calls"],
                        C_seconds=cf["seconds"],D_seconds=df["seconds"])
            joint.append(item)
        elif cf is not None:c_only.append(item)
        elif df is not None:d_only.append(item)
        else:both_missed.append(item)
    query_better=[r for r in joint if r["D_calls"]<r["C_calls"]]
    query_worse=[r for r in joint if r["D_calls"]>r["C_calls"]]
    time_better=[r for r in joint if r["D_seconds"]<r["C_seconds"]]
    time_worse=[r for r in joint if r["D_seconds"]>r["C_seconds"]]
    c_wall=sum(r["executor_call_wall_seconds"] for r in rows if r["method"]=="E9_R1_C")
    d_wall=sum(r["executor_call_wall_seconds"] for r in rows if r["method"]=="E9_R1_D")
    detection=len(d_defects)>len(c_defects) and not c_only and not unresolved_controls and not incomparable
    query=bool(query_better) and not query_worse and not c_only and not unresolved_controls and not incomparable
    status=("DETECTION_VALUE_OBSERVED_COST_DESCRIPTIVE" if detection else
            "QUERY_VALUE_OBSERVED_COST_DESCRIPTIVE" if query else
            "NO_ADDITIONAL_VALUE_OVER_C_OBSERVED")
    if c_only:status="MIXED_OR_NEGATIVE_TRANSFER_NOT_ESTABLISHED"
    if unresolved_controls:status="UNRESOLVED_FIXED_CONTROL_CONTRACT_DIFFERENCE"
    if incomparable:status="INCONCLUSIVE_EXECUTION_OR_ORACLE_OR_UNKNOWN"
    return dict(DETECTION_GAIN=dict(observed=detection,C_unique=len(c_defects),D_unique=len(d_defects),
                   C_only_runs=c_only,D_only_runs=d_only,
                   generated_attribution="REQUIRES_PUBLIC_CONTRACT_FIX_AND_MECHANISM_REVIEW"),
        QUERY_EFFICIENCY_GAIN=dict(observed=query,better=query_better,worse=query_worse,
            joint_detected=len(joint),both_missed=both_missed,
            scope="PAIRED_JOINT_DETECTION_CALLS_WITH_ALL_MISS_COUNTS_RETAINED"),
        WALL_TIME_GAIN=dict(status="DESCRIPTIVE_ONLY",faster=time_better,slower=time_worse,
            C_total_seconds=c_wall,D_total_seconds=d_wall,
            ratio=None if c_wall==0 else d_wall/c_wall,acceptable_cost_margin=None),
        NEGATIVE_TRANSFER=dict(C_detected_D_missed=c_only,higher_D_first_calls=query_worse,
            higher_D_total_wall=d_wall>c_wall,descriptive_not_statistical=True),
        ADDED_VALUE_OVER_C=dict(status=status,composite_efficiency_success=False,
            fixed_control_disagreements=unresolved_controls,
            incomparable_runs=incomparable,
            source_cost="REPORTED_SEPARATELY_NOT_TREATED_AS_FREE"))
