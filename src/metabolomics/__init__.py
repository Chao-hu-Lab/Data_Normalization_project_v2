"""
Metabolomics Data Normalization Package

A comprehensive toolkit for metabolomics data preprocessing and normalization.
"""

from importlib import import_module
from pathlib import Path

from .bootstrap_paths import ensure_ms_core_src_on_path

ensure_ms_core_src_on_path(Path(__file__).resolve())

__version__ = "2.0.0"
__author__ = "Metabolomics Team"
__all__ = ["processors", "utils", "gui"]


def __getattr__(name):
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
