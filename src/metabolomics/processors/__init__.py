"""
Processing modules for metabolomics data normalization.

Available processors:
- istd: ISTD (Internal Standard) Correction
- qc_lowess: QC-LOESS Signal Drift Correction
- qc_batch_scaling: QC-based Batch Scaling
- normalization: Concentration Normalization (PQN)
"""

from importlib import import_module

__all__ = [
    'istd',
    'qc_lowess',
    'qc_batch_scaling',
    'normalization',
]


def __getattr__(name):
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
