"""E7 public-module allowlist on the existing reviewed transport."""
from pathlib import Path

from ..mold.boundary import GeneratorBoundary
from .knowledge_protocol import PROTOCOL, validate_request

GENERATOR_FILES = (
    "__init__.py", "schema.py", "features.py", "predicates.py", "engine.py",
    "hypothesis_adapter.py", "solver.py", "transfer.py", "temporal.py",
    "temporal_engine.py", "temporal_transfer.py", "efficient.py",
    "knowledge.py", "knowledge_engine.py", "knowledge_protocol.py", "knowledge_worker.py",
)


class KnowledgeBoundary(GeneratorBoundary):
    module_root = Path(__file__).parent
    package_name = "discovery"
    generator_files = GENERATOR_FILES
    worker_entry = "tomolab.discovery.knowledge_worker"
    protocol_name = PROTOCOL

    def __init__(self, backend="subprocess", image="tomolab-e7-generator:local", timeout=60):
        self._temporal_contract = None
        self._target_provenance = None
        super().__init__(backend=backend, image=image, timeout=timeout)

    def validate_message(self, message, spec=None):
        return validate_request(message, spec, self._temporal_contract, self._target_provenance)

    def _request(self, action, **fields):
        if action == "observe" and self._frozen:
            raise ValueError("frozen knowledge generators reject feedback before transport")
        # Capture independently from mutable caller-owned input. The shared
        # transport validates again, and only this captured public data is sent.
        fields = self.validate_message({"action": action, **fields}, self._spec)
        fields.pop("action")
        result = super()._request(action, **fields)
        if action == "init":
            self._temporal_contract = fields.get("temporal_contract")
            self._target_provenance = fields.get("target_provenance")
        elif action == "plan":
            self._frozen = True
        return result
