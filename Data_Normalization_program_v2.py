import os
import sys


def main(argv=None):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(root_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from metabolomics.bootstrap_paths import ensure_ms_core_src_on_path

    ensure_ms_core_src_on_path(root_dir)
    from metabolomics.gui.app import main as gui_main
    gui_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
