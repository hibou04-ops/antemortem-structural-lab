"""Reuse the reviewed transport with a separate E5-only module allowlist."""
from pathlib import Path

from ..mold.boundary import GeneratorBoundary
from .protocol import PROTOCOL, validate_request

GENERATOR_FILES = ("__init__.py", "schema.py", "features.py", "predicates.py", "engine.py",
                   "hypothesis_adapter.py", "solver.py", "transfer.py", "protocol.py", "worker.py")


class DiscoveryBoundary(GeneratorBoundary):
    module_root = Path(__file__).parent
    package_name = "discovery"
    generator_files = GENERATOR_FILES
    worker_entry = "tomolab.discovery.worker"
    protocol_name = PROTOCOL
    validate_message = staticmethod(validate_request)

    def __init__(self, backend="subprocess", image="tomolab-e5-generator:local", timeout=60):
        super().__init__(backend=backend, image=image, timeout=timeout)
