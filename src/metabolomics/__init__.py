"""
Metabolomics Data Normalization Package

A comprehensive toolkit for metabolomics data preprocessing and normalization.
"""

from pathlib import Path

from .bootstrap_paths import ensure_ms_core_src_on_path

ensure_ms_core_src_on_path(Path(__file__).resolve())

__version__ = "2.0.0"
__author__ = "Metabolomics Team"

from . import processors
from . import utils
from . import gui
