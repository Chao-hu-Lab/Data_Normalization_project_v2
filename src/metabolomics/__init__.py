"""
Metabolomics Data Normalization Package

A comprehensive toolkit for metabolomics data preprocessing and normalization.
"""

from importlib import import_module

__version__ = "2.0.0"
__author__ = "Metabolomics Team"
__all__ = ["processors", "utils", "gui", "workflow"]


def __getattr__(name):
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
