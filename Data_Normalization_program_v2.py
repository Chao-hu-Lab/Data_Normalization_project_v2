import os
import sys


def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(root_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from metabolomics.gui_qt.app import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
