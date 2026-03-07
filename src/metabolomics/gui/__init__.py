"""
GUI module for Metabolomics Data Normalization.
"""

from importlib import import_module

__all__ = ["DataNormalizationApp"]


def __getattr__(name):
    if name == "DataNormalizationApp":
        app_cls = import_module(f"{__name__}.app").DataNormalizationApp
        globals()[name] = app_cls
        return app_cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
