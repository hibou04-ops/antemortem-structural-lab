"""Bounded empirical edit selection from recorded Source observations.

Operators are the common prior shared with every online method. This module
learns which existing edits reproduced an observed PASS -> FAILURE difference;
it never calls an Oracle and never stores Source values as rule predicates.
The result is a search policy, not a necessary/sufficient failure predicate.
"""
from copy import deepcopy
from itertools import product
import time

from .claim_semantics import EMPIRICAL, SEMANTIC_VERSION, classify
from .schema import canonical, digest
from .online_schema import input_identity

from .online_mold import (MOLD_SCHEMA, MAX_MOLD_BYTES, MAX_OBSERVATIONS,
    MAX_RULES, PRECONDITIONS, _features, _matches, validate_mold,
    applicable_rules, select_edit, save_mold, load_mold)

STATUSES = {"PASS", "FAILURE", "INVALID_INPUT", "EXECUTION_ERROR", "ORACLE_ERROR", "UNKNOWN"}


def _operator_ids(kind, operator_grammar):
    from .online_schema import common_operators
    common = list(common_operators(kind))
    if operator_grammar is None:
        return common
    requested = operator_grammar.get(kind, []) if isinstance(operator_grammar, dict) else operator_grammar
    if not isinstance(requested, (list, tuple)) or any(item not in common for item in requested):
        raise ValueError("learning uses only the shared COMMON_PRIOR operator grammar")
    return list(dict.fromkeys(requested))


def _apply(point, script, contract):
    from .online_schema import apply_edit, validate_input
    value = deepcopy(point)
    for operator in script:
        value = apply_edit(value, operator, contract)
        if value is None:
            return None
        try:
            if not validate_input(value, contract):
                return None
        except (ValueError, TypeError):
            return None
    return value


def _clean_observations(observations):
    from .online_schema import validate_contract, validate_input
    if not isinstance(observations, (list, tuple)) or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("bounded Source observation list required")
    clean = []
    for row in observations:
        if not isinstance(row, dict) or not {"input", "status", "contract"} <= row.keys():
            raise ValueError("Source input, observation status and public contract required")
        status = row["status"]
        if status not in STATUSES:
            raise ValueError("unsupported Source observation status")
        contract = validate_contract(row["contract"])
        point = deepcopy(row["input"])
        point_identity = input_identity(point)
        if "input_digest" in row and row["input_digest"] != point_identity:
            raise ValueError("Source input identity differs from its actual ordered input")
        if status in ("PASS", "FAILURE"):
            if not validate_input(point, contract):
                raise ValueError("a valid Source label requires an in-domain input")
        identity = row.get("source_identity", "EXPLICIT_SOURCE_UNSPECIFIED_IDENTITY")
        if not isinstance(identity, str) or len(identity) > 512:
            raise ValueError("bounded Source provenance required")
        clean.append(dict(input=point, status=status, contract=contract,
                          source_digest=digest(identity),
                          observation_digest=digest(dict(input_identity=point_identity, status=status,
                              contract=contract, source_identity=identity))))
    return clean


def learn_mold(observations, *, operator_grammar=None, max_rules=8,
               max_bytes=MAX_MOLD_BYTES, metrics=None, audit=None):
    """Extract one/two-edit scripts and select using observed counterevidence.

    ``observations`` contains actual Source executions, not evaluator-only
    Target cases. PASS/FAILURE pairs are matched within one Source identity
    and input contract. UNKNOWN/invalid/error rows provide no negative labels.
    ``metrics`` optionally receives measured extraction cost; timing is outside
    the deterministic, digest-bound execution Mold.
    """
    started = time.perf_counter()
    if type(max_rules) is not int or not 1 <= max_rules <= MAX_RULES:
        raise ValueError("bounded maximum learned rules required")
    if type(max_bytes) is not int or not 512 <= max_bytes <= MAX_MOLD_BYTES:
        raise ValueError("execution Mold limit must be at most 10KiB")
    rows = _clean_observations(observations)
    groups = {}
    for row in rows:
        key = (row["source_digest"], digest(row["contract"]))
        groups.setdefault(key, []).append(row)
    candidates, pairs, unmatched = {}, set(), set()
    delta_records = []
    attempted, unknown = 0, sum(row["status"] not in ("PASS", "FAILURE") for row in rows)
    for group in groups.values():
        contract = group[0]["contract"]
        operators = _operator_ids(contract["kind"], operator_grammar)
        labels = {}
        for row in group:
            if row["status"] in ("PASS", "FAILURE"):
                labels.setdefault(input_identity(row["input"]), []).append(row)
        # Conflicting repeated observations are censored, never forced to PASS.
        stable = {key: value[0] for key, value in labels.items()
                  if len({row["status"] for row in value}) == 1}
        unknown += sum(len({row["status"] for row in value}) > 1 for value in labels.values())
        passes = [row for row in stable.values() if row["status"] == "PASS"]
        failures = {key: row for key, row in stable.items() if row["status"] == "FAILURE"}
        paired_failures = set()
        scripts = [(operator,) for operator in operators]
        scripts += [script for script in product(operators, repeat=2) if script[0] != script[1]]
        for base in passes:
            single_results = {}
            for operator in operators:
                value = _apply(base["input"], (operator,), contract)
                if value is not None:
                    single_results[operator] = input_identity(value)
            for script in scripts:
                attempted += 1
                value = _apply(base["input"], script, contract)
                if value is None or input_identity(value) == input_identity(base["input"]):
                    continue
                if len(script) == 2:
                    intermediate = _apply(base["input"], script[:1], contract)
                    # Do not call a redundant two-edit rendering composition.
                    if intermediate is None or input_identity(intermediate) == input_identity(base["input"]) or input_identity(value) in single_results.values():
                        continue
                outcome = stable.get(input_identity(value))
                if outcome is None:
                    continue
                key = (contract["kind"], script)
                item = candidates.setdefault(key, dict(kind=contract["kind"], script=list(script), positive=[], negative=[]))
                record = dict(base_digest=base["observation_digest"], result_digest=outcome["observation_digest"],
                              features=_features(base["input"]), source_digest=base["source_digest"])
                if outcome["status"] == "FAILURE":
                    item["positive"].append(record)
                    pair = digest([record["base_digest"], record["result_digest"]])
                    pairs.add(pair); paired_failures.add(input_identity(value))
                    if audit is not None and len(delta_records) < 128:
                        delta_records.append(dict(x_pass=deepcopy(base["input"]),
                            x_fail=deepcopy(outcome["input"]), edit_composition=list(script),
                            contract_digest=digest(contract), source_digest=base["source_digest"],
                            reproduction="EXACT_MATCH_TO_RECORDED_SOURCE_EXECUTIONS",
                            minimality="NOT_CLAIMED_EDIT_MATCH_ONLY", global_minimum=False,
                            causal_uniqueness=False))
                else:
                    item["negative"].append(record)
        unmatched.update(row["observation_digest"] for key, row in failures.items() if key not in paired_failures)
    ranked = []
    for item in candidates.values():
        if not item["positive"]:
            continue
        # Learn a structural restriction only when it actually excludes
        # observed counterevidence while retaining every support observation.
        preconditions = {}
        positives, negatives = item["positive"], item["negative"]
        for name in sorted(PRECONDITIONS):
            values = [record["features"].get(name) for record in positives]
            if values and values[0] is not None and all(value == values[0] for value in values):
                if any(name in record["features"] and record["features"][name] != values[0] for record in negatives):
                    preconditions[name] = values[0]
        accepted_negative = [record for record in negatives
                             if all(record["features"].get(name) == value for name, value in preconditions.items())]
        support = sorted({digest([record["base_digest"], record["result_digest"]]) for record in positives})
        counterevidence = sorted({digest([record["base_digest"], record["result_digest"]]) for record in negatives})
        remaining = len({digest([record["base_digest"], record["result_digest"]]) for record in accepted_negative})
        prediction = classify(True, True, EMPIRICAL)
        rule = dict(kind=item["kind"], operator_schema="COMMON_PRIOR_TYPED_EDITS_V1",
            typed_roles=[dict(role="input", kind=item["kind"])], preconditions=preconditions,
            edit_composition=item["script"], source_support=support,
            counterevidence=counterevidence, applicability="EMPIRICAL_INPUT_STRUCTURE_ONLY",
            uncertainty="UNKNOWN_OUTSIDE_RECORDED_SOURCE_SUPPORT",
            claim_kind=EMPIRICAL, semantic_support=prediction["supports"],
            selection_statistics=dict(support=len(support), counterevidence=len(counterevidence),
                applicable_counterevidence=remaining, empirical_score=len(support)/(len(support)+remaining+1)),
            provenance=["COMMON_PRIOR", "SOURCE_LEARNED_SELECTION"]
                + (["SOURCE_LEARNED_COMPOSITION"] if len(item["script"]) == 2 else [])
                + (["SOURCE_LEARNED_APPLICABILITY"] if preconditions else []))
        # Bounded digest samples retain the complete set's identity without
        # copying one proof array into every execution rule.
        rule["source_support_digest"] = digest(support)
        rule["counterevidence_digest"] = digest(counterevidence)
        rule["source_support"] = support[:2]
        rule["counterevidence"] = counterevidence[:2]
        rule["rule_id"] = digest(rule)
        ranked.append(rule)
    ranked.sort(key=lambda rule: (-rule["selection_statistics"]["empirical_score"],
                                 -rule["selection_statistics"]["support"],
                                 len(rule["edit_composition"]), rule["rule_id"]))
    mold = dict(schema_version=MOLD_SCHEMA, semantic_contract_version=SEMANTIC_VERSION,
        usage_scope="EXPERIMENTAL_PROBE", claim_kind=EMPIRICAL,
        algorithm="RECORDED_PASS_FAILURE_TYPED_EDIT_MATCHING_DEPTH_2",
        source_observation_digest=digest(sorted(row["observation_digest"] for row in rows)),
        source_summary=dict(observations=len(rows), failure_observations=sum(row["status"] == "FAILURE" for row in rows),
            unknown_observations=unknown, matched_pairs=len(pairs), unpaired_failures=len(unmatched)),
        rules=[], omitted_rules=0, max_bytes=max_bytes, final_target_authorized=False,
        publication_authorized=False)
    for rule in ranked[:max_rules]:
        trial = deepcopy(mold); trial["rules"].append(rule)
        if len(canonical(dict(trial, artifact_digest="0"*64)).encode())+1 <= max_bytes:
            mold = trial
    mold["omitted_rules"] = len(ranked)-len(mold["rules"])
    mold["artifact_digest"] = digest(mold)
    validate_mold(mold, expected_digest=mold["artifact_digest"])
    if metrics is not None:
        metrics.update(learning_wall_seconds=time.perf_counter()-started,
            edit_applications_considered=attempted, source_target_calls=0, source_oracle_calls=0,
            cost_scope="RECORDED_OBSERVATION_EXTRACTION_ONLY_SOURCE_COLLECTION_SEPARATE")
    if audit is not None:
        selected_ids={rule["rule_id"] for rule in mold["rules"]}
        audit.update(deltas=delta_records, bounded_trace_limit=128,
            all_matched_pairs=len(pairs), unpaired_failure_digests=sorted(unmatched),
            unpaired_status="UNAVAILABLE" if unmatched else "NONE",
            source_delta_minimality="NOT_CLAIMED", target_calls=0, oracle_calls=0,
            ranked_rule_summaries=[dict(rule_id=rule["rule_id"],kind=rule["kind"],
                edit_composition=list(rule["edit_composition"]),preconditions=deepcopy(rule["preconditions"]),
                selected=rule["rule_id"] in selected_ids,
                omission_reason=None if rule["rule_id"] in selected_ids else
                    "PREDECLARED_RANK_LIMIT" if index>=max_rules else "PREDECLARED_SIZE_LIMIT")
                for index,rule in enumerate(ranked)])
    return mold


