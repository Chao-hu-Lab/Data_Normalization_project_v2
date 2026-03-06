from __future__ import annotations

from pathlib import Path
import sys


def find_ms_core_src(start_dir: str | Path | None = None) -> Path | None:
    anchor = Path(start_dir) if start_dir is not None else Path(__file__).resolve()
    anchor = anchor.resolve()
    seen: set[Path] = set()

    for base in (anchor, *anchor.parents):
        for repo_dir in (base / "MS Data process package" / "ms-core", base / "ms-core"):
            repo_dir = repo_dir.resolve()
            if repo_dir in seen or not repo_dir.exists():
                continue
            seen.add(repo_dir)

            worktree_root = repo_dir / ".worktrees"
            if worktree_root.exists():
                preferred = sorted(
                    path
                    for path in worktree_root.glob("*/src")
                    if (path / "ms_core" / "utils" / "bridge_workspace.py").exists()
                )
                for candidate in preferred:
                    if (candidate / "ms_core").exists():
                        return candidate

                for candidate in sorted(worktree_root.glob("*/src")):
                    if (candidate / "ms_core").exists():
                        return candidate

            src_dir = repo_dir / "src"
            if (src_dir / "ms_core").exists():
                return src_dir

    return None


def ensure_ms_core_src_on_path(start_dir: str | Path | None = None) -> Path | None:
    src_dir = find_ms_core_src(start_dir)
    if src_dir is not None and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    return src_dir
