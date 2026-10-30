"""Compact numerical worker on the existing reviewed process/container boundary."""
from pathlib import Path

from ..mold.boundary import GeneratorBoundary
from .compact_guidance import PROTOCOL, validate_numerical_request

GENERATOR_FILES = ("__init__.py", "schema.py", "numerical_guidance.py", "compact_guidance.py", "numerical_worker.py")


class NumericalBoundary(GeneratorBoundary):
    module_root = Path(__file__).parent
    package_name = "discovery"
    generator_files = GENERATOR_FILES
    worker_entry = "tomolab.discovery.numerical_worker"
    protocol_name = PROTOCOL
    validate_message = staticmethod(validate_numerical_request)

    def __init__(self, backend="subprocess", image="tomolab-e7-generator:local", timeout=60):
        super().__init__(backend=backend, image=image, timeout=timeout)

    @property
    def receipt(self):
        value = super().receipt
        value["transmitted_data"] = "APPROVED_COMPACT_GUIDE_OR_PUBLIC_BASELINE_CONTRACT_WITH_C_ONLY_REVIEWED_INPUT_EXEMPLARS"
        value["full_archive_transmitted"] = False
        value["oracle_modules_transmitted"] = False
        return value

    def _request(self, action, **fields):
        if self._frozen and action not in ("freeze", "snapshot", "diagnose", "close"):
            raise ValueError("frozen numerical boundary rejects learning and parameter replacement before transport")
        result = super()._request(action, **fields)
        if action in ("plan", "baseline"):
            self._frozen = True
        return result
