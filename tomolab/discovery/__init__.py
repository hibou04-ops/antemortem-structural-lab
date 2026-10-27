"""Typed structural discovery; optional integrations load only when requested."""
from importlib import import_module

_EXPORTS = {"DiscoveryEngine":"engine", "transfer":"engine", "validate_spec":"schema",
            "validate_inputs":"schema", "decode_inputs":"schema", "normalize_evidence":"schema",
            "generate_pool":"hypothesis_adapter", "native_find":"hypothesis_adapter",
            "run_discovery":"service", "plan_discovery":"service"}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module("."+_EXPORTS[name],__name__),name)
