"""Frozen development gold, baseline isolation, and metric regression checks."""
import json
from pathlib import Path

import pytest

from research.c1.authority import analyze, adjudicate
from research.c1.evaluate import (
    FIXTURES, candidate_gold, canonical_sha256, evaluate_llm, load_json,
    oracle_expression, run,
)

CASES = load_json(FIXTURES / 'dev_contracts.json')['cases']
GOLD = {row['id']: row for row in load_json(FIXTURES / 'dev_gold.json')['cases']}


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_core_against_separately_frozen_membership_gold(case):
    """Production relation and lifting checked against independent authored truth sets."""
    gold = GOLD[case['id']]
    analysis = analyze(case['contract'])
    assert analysis['relation'] == gold['relation']
    assert analysis['premise_satisfiable'] == gold['premise_satisfiable'] or gold['relation'] in {'AMBIGUOUS', 'OUT_OF_SCOPE', 'UNKNOWN'}
    assert adjudicate(case['contract'], case['evidence'])['status'] == gold['expected_status']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_independent_candidate_oracle_matches_original_curated_truth_membership(case):
    gold = GOLD[case['id']]
    observed = [state for state in gold['admissible_states']
                if oracle_expression(case['contract']['obligation'], state)]
    assert observed == gold['obligation_true_states']


def test_paired_ablation_reduces_false_conclusions_without_losing_eligible_witnesses():
    report = run()
    unsafe = report['baseline_results']['unsafe_lifting_ablation']['metrics']
    guarded = report['baseline_results']['logical_authority']['metrics']
    assert unsafe['wrong_refuted_count'] == 12
    assert unsafe['unsupported_refuted_count'] == 24
    assert guarded['wrong_refuted_count'] == 0
    assert guarded['unsupported_refuted_count'] == 0
    assert guarded['true_counterexample_recall'] == {'numerator': 14, 'denominator': 14, 'value': 1.0}
    assert guarded['unknown_recall'] == {'numerator': 27, 'denominator': 27, 'value': 1.0}


def test_wrong_conclusion_and_invalid_support_are_not_conflated():
    rows = {r['id']: r for r in run()['baseline_results']['unsafe_lifting_ablation']['rows']}
    assert rows['B01']['wrong_refuted'] is True
    assert rows['B04']['wrong_refuted'] is False
    assert rows['B04']['unsupported_refuted'] is True
    assert rows['B04']['witness_violates_claim_predicate'] is False


def test_baseline_not_run_has_no_fabricated_score_or_receipt():
    baseline = run()['baseline_results']['llm_direct']
    assert baseline['status'] == 'NOT_RUN'
    assert baseline['metrics'] is None
    assert baseline['tokens'] is None
    assert baseline['api_cost_usd'] is None


def test_actual_c0_templates_accept_six_sentences_only():
    arm = run()['baseline_results']['c0_templates']
    assert arm['accepted'] == 6
    assert arm['metrics']['status_counts'] == {'UNKNOWN': 40, 'REFUTED': 6}


def test_imported_candidates_must_cover_once(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'candidates': [{'id': CASES[0]['id']}] * 2}))
    with pytest.raises(ValueError, match='exactly once'):
        evaluate_llm(CASES, GOLD, bad)


def test_content_hash_survives_newline_reformatting():
    data = load_json(FIXTURES / 'dev_gold.json')
    assert canonical_sha256(data) == canonical_sha256(json.loads(json.dumps(data, indent=4).replace('\n', '\r\n')))


def test_candidate_oracle_cannot_execute_code():
    with pytest.raises(ValueError):
        oracle_expression(['__import__', 'os'], {})
    with pytest.raises(ValueError):
        oracle_expression(['==', True, 1], {})


def test_empty_gold_support_and_mixed_quantifier_remain_unknown():
    for identifier in ('P03', 'Q03'):
        case = next(c for c in CASES if c['id'] == identifier)
        gold, _ = candidate_gold(case, GOLD[identifier], case['contract']['obligation'])
        assert gold['relation'] == 'UNKNOWN'
        assert gold['expected_status'] == 'UNKNOWN'


def test_holdout_is_commitment_only_in_public_tree():
    m = load_json(FIXTURES / 'holdout_commitment.json')
    assert m['evaluation_runs'] == 0
    assert m['case_count'] == 12
    assert not list(FIXTURES.rglob('*.zip'))


def test_generated_quantifiers_are_fair_and_receipts_preserved(tmp_path):
    selected = [c for c in CASES if c['id'] in ('Q02', 'Q03')]
    artifact = {'provenance': {'external_api_calls': 0, 'token_usage': None,
                              'monetary_cost': None, 'elapsed_seconds': 12.3},
                'candidates': [{'id': c['id'], 'decision': 'FORMALIZED',
                                'obligation': c['contract']['claim'], 'reason': 'Test candidate.'}
                               for c in selected]}
    path = tmp_path / 'generated.json'
    path.write_text(json.dumps(artifact))
    for guarded in (False, True):
        result = evaluate_llm(selected, GOLD, path, guarded=guarded)
        rows = {r['id']: r for r in result['rows']}
        assert rows['Q02']['status'] == 'PROVED_BOUNDED'
        assert rows['Q03']['status'] == 'REFUTED'
        assert rows['Q03']['gold_relation'] == 'EQUIVALENT'
        assert rows['Q02']['natural_language_status'] == 'UNKNOWN'
        assert result['generation_elapsed_seconds'] == 12.3
        assert result['external_api_calls'] == 0
        assert result['tokens'] is None
        assert result['new_generation_runs_for_this_arm'] == (0 if guarded else 1)


def test_oracle_resource_bounds_and_malformed_candidate_fail_closed(tmp_path):
    with pytest.raises(ValueError, match='literal limit'):
        oracle_expression(['==', 1_000_000_001, 1_000_000_001], {})
    with pytest.raises(ValueError, match='node limit'):
        oracle_expression(['and'] + [True] * 4096, {})
    huge = ['*', ['*', 1_000_000_000, 1_000_000_000],
            ['*', ['*', 1_000_000_000, 1_000_000_000], 1_000_000_000]]
    with pytest.raises(ValueError, match='intermediate integer limit'):
        oracle_expression(['==', huge, huge], {})
    case = CASES[0]
    path = tmp_path / 'bad-decision.json'
    path.write_text(json.dumps({'candidates': [{'id': case['id'], 'decision': 'GUESS',
                                               'obligation': True, 'reason': 'Bad status.'}]}))
    result = evaluate_llm([case], GOLD, path)
    assert result['rows'][0]['status'] == 'UNKNOWN'
    oversized = tmp_path / 'oversized.json'
    oversized.write_bytes(b' ' * 2_000_001)
    with pytest.raises(ValueError, match='byte limit'):
        load_json(oversized)
