"""P0 resize kill-gate for the PySide6 GUI rebuild.

This is deliberately a non-functional, near-final-density view.  It exists to
test the rebuild's core premise in a packaged executable before controller or
workflow work begins.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)


WINDOW_TITLE = "Data Normalization Workflow v2 — Qt Resize Probe"
STEP_TITLES = (
    "ISTD Correction",
    "QC-LOESS",
    "Concentration Normalization",
    "QC Batch Scaling (paused / diagnostics-only)",
)


def _row(*widgets: QWidget, object_name: str) -> QWidget:
    row = QWidget()
    row.setObjectName(object_name)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    return row


def _build_step_card(step_number: int, title: str) -> QFrame:
    card = QFrame()
    card.setObjectName(f"stepCard{step_number}")
    card.setFrameShape(QFrame.Shape.StyledPanel)
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(7)

    body = QWidget()
    body.setObjectName("cardBody")
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(7)

    step_badge = QFrame()
    step_badge.setObjectName("stepBadge")
    badge_layout = QVBoxLayout(step_badge)
    badge_layout.setContentsMargins(6, 3, 6, 3)
    badge_layout.addWidget(QLabel(f"Step {step_number}"))

    title_label = QLabel(title)
    title_label.setWordWrap(True)
    title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    status = QLabel("Idle")
    status.setObjectName("statusPill")
    body_layout.addWidget(
        _row(
            step_badge,
            title_label,
            status,
            object_name="cardHeader",
        )
    )

    source = QLabel(
        "Selected workbook" if step_number == 1 else f"Output from Step {step_number - 1}"
    )
    source.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    body_layout.addWidget(_row(QLabel("Input:"), source, object_name="inputSource"))

    if step_number == 3:
        reference_pqn = QRadioButton("PQN with QC reference")
        reference_pqn.setChecked(True)
        body_layout.addWidget(
            _row(
                QLabel("Method:"),
                reference_pqn,
                QRadioButton("Plain PQN"),
                object_name="methodOptions",
            )
        )
        hint = QLabel(
            "PQN is the urine/global-dilution default; SpecNorm uses a trusted "
            "tissue reference."
        )
    else:
        hint = QLabel("Output and diagnostics appear here after this step completes.")
    hint.setWordWrap(True)
    hint.setObjectName("cardHint")
    body_layout.addWidget(hint)

    if step_number == 3:
        body_layout.addWidget(QLabel("Normalization diagnostics are written beside the workbook."))
    elif step_number == 4:
        body_layout.addWidget(QLabel("Manual diagnostic step; Auto Run stops before this card."))

    divider = QFrame()
    divider.setObjectName("cardDivider")
    divider.setFrameShape(QFrame.Shape.HLine)
    body_layout.addWidget(divider)
    layout.addWidget(body)

    actions = QFrame()
    actions.setObjectName("cardActions")
    actions_layout = QVBoxLayout(actions)
    actions_layout.setContentsMargins(0, 0, 0, 0)
    actions_layout.setSpacing(6)

    run_button = QPushButton("Run Step")
    run_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    actions_layout.addWidget(_row(run_button, object_name="primaryAction"))

    open_excel = QPushButton("Open Excel")
    open_plots = QPushButton("Open Plots")
    open_excel.setEnabled(False)
    open_plots.setEnabled(False)
    actions_layout.addWidget(
        _row(open_excel, open_plots, object_name="secondaryActions")
    )
    layout.addWidget(actions)
    return card


def _build_left_pane() -> QWidget:
    scroll = QScrollArea()
    scroll.setObjectName("workflowScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    contents = QWidget()
    contents.setObjectName("workflowCards")
    layout = QVBoxLayout(contents)
    layout.setContentsMargins(0, 0, 6, 0)
    layout.setSpacing(10)
    for step_number, title in enumerate(STEP_TITLES, start=1):
        layout.addWidget(_build_step_card(step_number, title))
    layout.addStretch(1)
    scroll.setWidget(contents)
    return scroll


def _build_log_pane() -> QWidget:
    pane = QFrame()
    pane.setObjectName("logPane")
    pane.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)

    clear_button = QPushButton("Clear")
    layout.addWidget(
        _row(
            QLabel("Real-time execution output"),
            clear_button,
            object_name="logHeader",
        )
    )

    log = QPlainTextEdit()
    log.setObjectName("executionLog")
    log.setReadOnly(True)
    log.setPlainText(
        "Qt P0 resize probe\n"
        "Packaged Qt resize probe is running.\n"
        "Drag every window edge and the splitter handle to evaluate responsiveness."
    )
    layout.addWidget(log, 1)

    layout.addWidget(
        _row(
            QLabel("Progress"),
            QLabel("Not started"),
            object_name="progressRow",
        )
    )
    session = QLabel("Session: none yet")
    session.setObjectName("sessionPath")
    session.setWordWrap(True)
    layout.addWidget(session)
    return pane


def build_main_window() -> QMainWindow:
    """Build the representative-density P0 window without starting the event loop."""
    window = QMainWindow()
    window.setObjectName("dnpQtResizeProbe")
    window.setWindowTitle(WINDOW_TITLE)
    window.resize(1480, 940)
    window.setMinimumSize(980, 680)

    central = QWidget()
    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(18, 14, 18, 12)
    root_layout.setSpacing(10)

    title = QLabel("Data Normalization Workflow v2")
    title.setObjectName("pageTitle")
    subtitle = QLabel(
        "Metabolomics data processing pipeline | VBA-formatted Excel required"
    )
    subtitle.setObjectName("pageSubtitle")
    root_layout.addWidget(title)
    root_layout.addWidget(subtitle)

    browse = QPushButton("Browse")
    file_path = QLabel("No file selected...")
    file_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    root_layout.addWidget(
        _row(QLabel("Input"), file_path, browse, object_name="fileBar")
    )

    root_layout.addWidget(
        _row(
            QPushButton("Auto Run"),
            QPushButton("Stop"),
            QPushButton("Reset"),
            object_name="workflowControls",
        )
    )

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setObjectName("workspaceSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(_build_left_pane())
    splitter.addWidget(_build_log_pane())
    splitter.setSizes([620, 800])
    splitter.setStretchFactor(0, 5)
    splitter.setStretchFactor(1, 7)
    root_layout.addWidget(splitter, 1)

    window.setCentralWidget(central)
    status_bar = QStatusBar()
    status_bar.setObjectName("applicationStatusBar")
    status_bar.showMessage("P0 resize kill-gate — no workflow actions are connected")
    window.setStatusBar(status_bar)
    return window


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_main_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
