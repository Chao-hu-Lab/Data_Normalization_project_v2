import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QSplitter, QWidget

from metabolomics.gui_qt.p0_resize_probe import STEP_TITLES, build_main_window


def test_resize_probe_has_representative_workspace_density():
    app = QApplication.instance() or QApplication([])
    window = build_main_window()

    assert isinstance(window, QMainWindow)
    splitter = window.findChild(QSplitter, "workspaceSplitter")
    assert splitter is not None
    assert splitter.count() == 2

    cards = [window.findChild(QFrame, f"stepCard{index}") for index in range(1, 5)]
    assert all(card is not None for card in cards)
    assert len(STEP_TITLES) == 4
    widget_counts = [len(card.findChildren(QWidget)) for card in cards]
    assert widget_counts == [17, 17, 22, 18]

    window.show()
    app.processEvents()
    assert window.isVisible()
    window.close()
    app.processEvents()
