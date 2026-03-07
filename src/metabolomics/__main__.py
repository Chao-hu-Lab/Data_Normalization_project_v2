"""
Entry point for running the application as a module.

Usage:
    python -m metabolomics
"""

import sys
import os

# Add src to path for development mode
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from metabolomics.bootstrap_paths import ensure_ms_core_src_on_path

ensure_ms_core_src_on_path(os.path.dirname(src_dir))


def main(argv=None):
    """Launch the GUI application."""
    from metabolomics.gui.app import main as gui_main
    gui_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
