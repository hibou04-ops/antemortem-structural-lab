"""Small independent truth-membership audit of the bounded authority policy.

The reference is a four-bit membership mask, not the production interpreter.
This checks formal conclusion soundness only, not natural-language fidelity or
the completeness of conservative UNKNOWN decisions.
"""
from research.c1.authority import adjudicate


def test_all_two_boolean_truth_sets_preserve_quantified_conclusion_soundness():
    states = [
        {"p": False, "q": False},
        {"p": False, "q": True},
        {"p": True, "q": False},
        {"p": True, "q": True},
    ]

    def expression(mask):
        # Construct a Boolean DNF from the independently enumerated membership.
        terms = [
            ["and", "p" if state["p"] else ["not", "p"],
             "q" if state["q"] else ["not", "q"]]
            for bit, state in enumerate(states) if mask & (1 << bit)
        ]
        if not terms:
            return False
        return terms[0] if len(terms) == 1 else ["or", *terms]

    checked = 0
    for claim_mask in range(16):
        for obligation_mask in range(16):
            for quantifier in ("forall", "exists"):
                contract = {
                    "schema": "c1-contract-v1",
                    "id": "independent-boolean-membership-audit",
                    "claim_text": "Manually enumerated Boolean truth membership",
                    "variables": {"p": {"type": "bool"}, "q": {"type": "bool"}},
                    "claim": expression(claim_mask),
                    "obligation": expression(obligation_mask),
                    "assumptions": [],
                    "exceptions": [],
                    "quantifier": quantifier,
                    "time": {"kind": "state", "horizon": 0},
                    "evidence_scope": {
                        "kind": "finite", "description": "All four Boolean assignments",
                    },
                    "interpretation": {
                        "status": "reviewed",
                        "source": "Separate review role: manual truth-mask membership",
                    },
                }
                # Truth is derived directly from mask membership, without evaluating DSL.
                claim_holds = (claim_mask == 15 if quantifier == "forall"
                               else claim_mask != 0)
                submissions = [
                    {"status": "PASS_EXHAUSTIVE"},
                    *({"status": "FAIL", "witness": state} for state in states),
                ]
                for evidence in submissions:
                    result = adjudicate(contract, evidence)
                    context = (claim_mask, obligation_mask, quantifier, evidence)
                    if result["status"] == "REFUTED":
                        assert not claim_holds, context
                    if result["status"] == "PROVED_BOUNDED":
                        assert claim_holds, context
                    assert result["conclusion_target"] == "SUPPLIED_FORMAL_CLAIM", context
                    assert result["natural_language_status"] == "UNKNOWN", context
                    assert result["semantic_fidelity"] == "NOT_ESTABLISHED", context
                    checked += 1

    assert checked == 2_560
