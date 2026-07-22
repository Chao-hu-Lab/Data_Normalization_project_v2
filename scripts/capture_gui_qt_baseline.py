"""Capture reproducible P3 Qt-only GUI baselines with ``QWidget.grab()``.

Run on the native Windows Qt platform. The PNGs are local review artifacts and
are intentionally not a cross-framework or cross-platform pixel oracle.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import PySide6
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from metabolomics.gui.workflow import STEP1_NAME
from metabolomics.gui_qt.app import DNPMainWindow
from metabolomics.gui_qt.controller import WorkflowController
from metabolomics.utils.results import ProcessingResult, WorkflowOutcome


SCENARIOS = (
    "fresh",
    "file_selected",
    "running",
    "done",
    "skipped",
    "error",
    "cancelled",
)


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _controller_for(
    scenario: str,
    release_running: threading.Event | None = None,
) -> WorkflowController:
    processors = {}
    if release_running is not None:
        def running_processor(**kwargs):
            if not release_running.wait(10):
                raise TimeoutError("Baseline running-state worker was not released")
            return ProcessingResult(
                kwargs["input_file"],
                "C:/DNP_output/session_preview/step1.xlsx",
                1200,
                48,
            )

        processors[STEP1_NAME] = running_processor

    controller = WorkflowController(
        processors=processors,
        session_factory=lambda _input: "C:/DNP_output/session_preview",
    )
    if scenario == "fresh":
        return controller

    input_path = "C:/datasets/demo_input.xlsx"
    output_path = "C:/DNP_output/session_preview/step1.xlsx"
    controller.select_input(input_path)
    if scenario == "file_selected":
        return controller

    if scenario == "running":
        return controller
    controller.workflow.begin(STEP1_NAME)
    if scenario == "done":
        controller.workflow.complete(
            STEP1_NAME,
            ProcessingResult(input_path, output_path, 1200, 48),
        )
    elif scenario == "skipped":
        controller.workflow.complete(
            STEP1_NAME,
            ProcessingResult(
                input_path,
                output_path,
                1200,
                48,
                status=WorkflowOutcome.SKIPPED,
                reason="insufficient_good_istd",
            ),
        )
    elif scenario == "error":
        controller.workflow.fail(STEP1_NAME, "Representative processor failure")
    elif scenario == "cancelled":
        controller.workflow.cancel(STEP1_NAME, "Stopped by user")
    return controller


def capture(output_dir: Path) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    output_dir.mkdir(parents=True, exist_ok=True)
    screen = app.primaryScreen()
    captures = []

    for scenario in SCENARIOS:
        release_running = threading.Event() if scenario == "running" else None
        controller = _controller_for(scenario, release_running)
        window = DNPMainWindow(controller=controller)
        window.theme_manager.set_preference("light")
        if scenario == "running":
            controller.start_step(STEP1_NAME)
        elif scenario not in {"fresh", "file_selected"}:
            controller.session_changed.emit("C:/DNP_output/session_preview")
        window.resize(1280, 760)
        window.show()
        app.processEvents()
        pixmap = window.grab()
        image_path = output_dir / f"{scenario}.png"
        if not pixmap.save(str(image_path)):
            raise RuntimeError(f"Could not save {image_path}")
        captures.append(
            {
                "scenario": scenario,
                "file": image_path.name,
                "width": pixmap.width(),
                "height": pixmap.height(),
                "device_pixel_ratio": pixmap.devicePixelRatio(),
            }
        )
        if release_running is not None:
            release_running.set()
            deadline = time.monotonic() + 10
            while controller.is_running and time.monotonic() < deadline:
                app.processEvents()
            if controller.is_running:
                raise TimeoutError("Baseline running-state worker did not finish")
        window.close()
        app.processEvents()

    manifest = {
        "purpose": "P3 Qt-internal visual review baseline",
        "warning": "Do not pixel-compare against tkinter or across platform/font/DPI environments.",
        "commit": _commit(),
        "python": platform.python_version(),
        "pyside6": PySide6.__version__,
        "qt": qVersion(),
        "platform": platform.platform(),
        "qt_style": app.style().objectName()
        or app.style().metaObject().className(),
        "font": app.font().family(),
        "logical_dpi": screen.logicalDotsPerInch() if screen else None,
        "captures": captures,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "tests" / "baselines" / "gui_qt" / "p3_windows",
    )
    args = parser.parse_args()
    manifest = capture(args.output_dir.resolve())
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
