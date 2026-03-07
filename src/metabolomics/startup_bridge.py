import argparse
from pathlib import Path


def parse_startup_args(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ms-session-dir")
    parser.add_argument("--ms-bridge-file")
    args, _ = parser.parse_known_args(argv)
    return args


def apply_startup_bridge(app, bridge_file: str | None) -> bool:
    if not bridge_file:
        return False

    path = Path(bridge_file)
    if not path.exists():
        return False

    app._set_input_file(str(path))
    return True
