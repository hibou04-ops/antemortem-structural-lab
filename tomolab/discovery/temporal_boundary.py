"""E6 reviewed public-module allowlist on the existing transport."""
from pathlib import Path

from ..mold.boundary import GeneratorBoundary
from .temporal_protocol import PROTOCOL, validate_request

GENERATOR_FILES = (
    "__init__.py", "schema.py", "features.py", "predicates.py", "engine.py",
    "hypothesis_adapter.py", "solver.py", "transfer.py",
    "temporal.py", "temporal_engine.py", "temporal_transfer.py",
    "efficient.py", "temporal_protocol.py", "temporal_worker.py",
)


class TemporalBoundary(GeneratorBoundary):
    module_root = Path(__file__).parent
    package_name = "discovery"
    generator_files = GENERATOR_FILES
    worker_entry = "tomolab.discovery.temporal_worker"
    protocol_name = PROTOCOL

    def __init__(self, backend="subprocess", image="tomolab-e6-generator:local", timeout=60):
        self._temporal_contract = None
        super().__init__(backend=backend,image=image,timeout=timeout)

    def validate_message(self, message, spec=None):
        return validate_request(message,spec,self._temporal_contract)

    def _request(self, action, **fields):
        if action in ("observe","register") and self._frozen:
            raise ValueError("frozen temporal generators reject learning before transport")
        result = super()._request(action,**fields)
        if action == "init":
            from .temporal import validate_temporal_contract
            self._temporal_contract = validate_temporal_contract(fields["temporal_contract"],self._spec)
        return result
