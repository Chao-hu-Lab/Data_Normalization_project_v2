"""Small reusable controls for the Qt theme preference."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QWidget

from metabolomics.gui_qt.qss import ThemeManager, ThemePreference


class ThemeSelector(QFrame):
    """Segmented System/Light/Dark control bound to a ``ThemeManager``."""

    def __init__(self, manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("themeSelector")
        self._manager = manager
        self._preferences: tuple[ThemePreference, ...] = ("system", "light", "dark")
        self._buttons: dict[ThemePreference, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        for button_id, preference in enumerate(self._preferences):
            button = QPushButton(preference.title())
            button.setObjectName("themeOption")
            button.setCheckable(True)
            self._button_group.addButton(button, button_id)
            self._buttons[preference] = button
            layout.addWidget(button)

        self._button_group.idClicked.connect(self._select_preference)
        self._manager.preference_changed.connect(self._sync_preference)
        self._sync_preference(self._manager.preference)

    @Slot(int)
    def _select_preference(self, button_id: int) -> None:
        self._manager.set_preference(self._preferences[button_id])

    @Slot(str)
    def _sync_preference(self, preference: str) -> None:
        self._buttons[preference].setChecked(True)
