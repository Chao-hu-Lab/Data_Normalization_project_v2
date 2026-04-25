"""Run the Step 1 -> Step 3 cleanup acceptance workflow on a real workbook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _configure_import_paths() -> None:
    root_dir = _project_root()
    src_dir = root_dir / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))


def _result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "file_path": str(getattr(result, "file_path", "")),
        "output_path": str(getattr(result, "output_path", "")),
        "metabolites": getattr(result, "metabolites", None),
        "samples": getattr(result, "samples", None),
        "extra": getattr(result, "extra", {}) or {},
    }


def run_workflow(input_file: Path, method: str, session_dir: Path) -> dict[str, Any]:
    _configure_import_paths()

    from metabolomics.bootstrap_paths import ensure_ms_core_src_on_path
    from metabolomics.processors import istd, normalization, qc_lowess

    ensure_ms_core_src_on_path(str(_project_root()))
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "plots").mkdir(exist_ok=True)

    step1_result = istd.main(input_file=str(input_file), session_dir=session_dir)
    step2_result = qc_lowess.main(
        input_file=step1_result.output_path,
        session_dir=session_dir,
    )
    step3_result = normalization.main(
        input_file=step2_result.output_path,
        session_dir=session_dir,
        normalization_method=method,
    )

    payload = {
        "method": method,
        "input_file": str(input_file),
        "session_dir": str(session_dir),
        "step1": _result_to_dict(step1_result),
        "step2": _result_to_dict(step2_result),
        "step3": _result_to_dict(step3_result),
    }

    manifest_path = session_dir / "acceptance_run.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload["manifest_path"] = str(manifest_path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run DNP cleanup acceptance workflow through Step 3.",
    )
    parser.add_argument("--input", required=True, help="Input workbook path.")
    parser.add_argument(
        "--method",
        default="SpecNorm+PQN",
        help="Step 3 normalization method.",
    )
    parser.add_argument(
        "--session-dir",
        required=True,
        help="Output session directory for deterministic acceptance artifacts.",
    )
    args = parser.parse_args(argv)

    input_file = Path(args.input).resolve()
    if not input_file.exists():
        parser.error(f"Input workbook does not exist: {input_file}")

    payload = run_workflow(
        input_file=input_file,
        method=args.method,
        session_dir=Path(args.session_dir),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
