from pathlib import Path

from metabolomics.bootstrap_paths import find_ms_core_src
from metabolomics.startup_bridge import apply_startup_bridge, parse_startup_args


def test_find_ms_core_src_prefers_worktree_copy(tmp_path):
    dnp_root = tmp_path / "Desktop" / "Data_Normalization_project_v2"
    dnp_root.mkdir(parents=True, exist_ok=True)

    main_src = tmp_path / "Desktop" / "MS Data process package" / "ms-core" / "src"
    worktree_src = (
        tmp_path
        / "Desktop"
        / "MS Data process package"
        / "ms-core"
        / ".worktrees"
        / "cross-project-bridge"
        / "src"
    )

    (main_src / "ms_core" / "utils").mkdir(parents=True, exist_ok=True)
    (worktree_src / "ms_core" / "utils").mkdir(parents=True, exist_ok=True)
    (worktree_src / "ms_core" / "utils" / "bridge_workspace.py").write_text(
        "# bridge marker",
        encoding="utf-8",
    )

    assert find_ms_core_src(dnp_root) == worktree_src


def test_parse_startup_args_reads_ms_bridge_options():
    args = parse_startup_args(
        ["--ms-session-dir", "C:/tmp/session", "--ms-bridge-file", "C:/tmp/input.xlsx"]
    )

    assert args.ms_session_dir == "C:/tmp/session"
    assert args.ms_bridge_file == "C:/tmp/input.xlsx"


def test_apply_startup_bridge_calls_set_input_file(tmp_path):
    bridge_file = tmp_path / "bridge.xlsx"
    bridge_file.write_text("placeholder", encoding="utf-8")

    calls: dict[str, str] = {}

    class DummyApp:
        def _set_input_file(self, value):
            calls["value"] = value

    assert apply_startup_bridge(DummyApp(), str(bridge_file)) is True
    assert calls["value"] == str(Path(bridge_file))
