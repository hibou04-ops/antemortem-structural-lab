"""Explicit host approval for reviewed local CORR execution, never final use.

An expected context comes from trusted host configuration. A content hash or
this class alone is not an authority. No Source-only artifact is rewritten.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import re

from .schema import canonical, digest, integer, keys
from .numerical_guidance import public_input_contract, validate_input_contract

SCHEMA = "tomolab-corroboration-execution-permit-v1"
SCOPE = "INDEPENDENT_DEVELOPMENT_ONLY"
FIELDS = ("schema", "scope", "frozen_source_guide_digest", "approved_implementation_identity",
    "adapter_identity", "oracle_identity", "common_input_contract", "candidate_generation_contract",
    "reviewed_authority", "authority_id", "resource_budget", "candidate_plan_digest", "review_digest",
    "feedback_to_generator", "final_evaluation_authorized", "publication_authorized")


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("pinned SHA-256 identity required")
    return value


def build_permit_context(plan, implementation_identity, *, common_input_contract,
        resource_budget, authority_id, guide_digest, review_digest):
    """Describe a request for approval; this function grants no permission."""
    from .corroboration_adapters import adapter_identity, oracle_identity
    from .corroboration_service import validate_candidate_plan
    validate_candidate_plan(plan)
    return dict(schema=SCHEMA, scope=SCOPE, frozen_source_guide_digest=_sha(guide_digest),
        approved_implementation_identity=deepcopy(implementation_identity),
        adapter_identity=adapter_identity(), oracle_identity=oracle_identity(),
        common_input_contract=deepcopy(common_input_contract),
        candidate_generation_contract=deepcopy(plan["request"]["contract"]),
        reviewed_authority="EXPLICIT_USER_E8_R4_REVIEWED_LOCAL_LIBRARY_DEVELOPMENT",
        authority_id=_sha(authority_id), resource_budget=deepcopy(resource_budget),
        candidate_plan_digest=plan["plan_digest"], review_digest=_sha(review_digest),
        feedback_to_generator=False, final_evaluation_authorized=False, publication_authorized=False)


@dataclass(frozen=True)
class CorroborationExecutionPermit:
    _encoded: str

    @classmethod
    def from_host_approval(cls, context, expected_context):
        if not isinstance(expected_context, dict) or canonical(context) != canonical(expected_context):
            raise PermissionError("external trusted host CORR approval differs")
        value = json.loads(canonical(context))
        keys(value, FIELDS)
        if (value["schema"] != SCHEMA or value["scope"] != SCOPE
                or value["feedback_to_generator"] is not False
                or value["final_evaluation_authorized"] is not False
                or value["publication_authorized"] is not False
                or value["reviewed_authority"] != "EXPLICIT_USER_E8_R4_REVIEWED_LOCAL_LIBRARY_DEVELOPMENT"):
            raise PermissionError("CORR permit cannot authorize final execution, feedback or publication")
        for name in ("frozen_source_guide_digest", "authority_id", "candidate_plan_digest", "review_digest"):
            _sha(value[name])
        common = validate_input_contract(value["common_input_contract"])
        generation = validate_input_contract(value["candidate_generation_contract"])
        if common != public_input_contract() or generation != public_input_contract(lengths=[4,5,6]):
            raise ValueError("CORR uses the unchanged full Source domain and R3 fresh generation subdomain")
        keys(value["resource_budget"], ("pair_budget", "shrink_budget"))
        integer(value["resource_budget"]["pair_budget"], 3, 4096)
        integer(value["resource_budget"]["shrink_budget"], 0,
                min(1024, value["resource_budget"]["pair_budget"]-3))
        identity = value["approved_implementation_identity"]
        if not isinstance(identity, dict) or "usage_identity" not in identity:
            raise ValueError("reviewed implementation and lineage identity required")
        from .evaluation_usage import identity_tokens
        identity_tokens(identity["usage_identity"])
        # Bind the actual allowlisted adapter/Oracle source. No arbitrary import
        # path or user callback is installed by this authorization object.
        from .corroboration_adapters import adapter_identity, oracle_identity, reviewed_implementation_ids
        if identity.get("implementation_id") not in reviewed_implementation_ids():
            raise PermissionError("implementation is outside the reviewed local allowlist")
        if (canonical(value["adapter_identity"]) != canonical(adapter_identity()) or
                canonical(value["oracle_identity"]) != canonical(oracle_identity())):
            raise PermissionError("CORR adapter or independent Oracle identity differs")
        return cls(canonical(value))

    @property
    def context(self):
        return json.loads(self._encoded)

    @property
    def permit_digest(self):
        return digest(self.context)

    def validate(self, expected_context, *, plan=None):
        authorized = self.from_host_approval(self.context, expected_context)
        if plan is not None:
            from .corroboration_service import validate_candidate_plan
            validate_candidate_plan(plan)
            if plan["plan_digest"] != authorized.context["candidate_plan_digest"]:
                raise PermissionError("candidate plan differs from the host-approved CORR permit")
            if plan["method"] == "D" and plan["request"]["expected_digest"] != self.context["frozen_source_guide_digest"]:
                raise PermissionError("Source guide differs from approved CORR generation")
        return authorized
