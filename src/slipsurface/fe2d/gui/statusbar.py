"""Status bar: hints, live coordinates and drawing toggles.

Toggles mirror the SlipSurfaceIQ-LE CAD status bar: SNAP / GRID / ORTHO
keys F9 / F7 / F8 / F3, AutoCAD style. Toggles only affect canvases that
are currently drawing (the CAD dialog); the result canvas ignores them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QStatusBar, QToolButton

TOGGLE_CSS = (
    "QToolButton{border:none;padding:0 5px;color:#9aa0a6;font-weight:bold;}"
    "QToolButton:checked{color:#111;}"
)


class CadStatusBar(QStatusBar):
    def __init__(self, parent=None, with_toggles: bool = True) -> None:
        super().__init__(parent)
        self.showMessage("Hazır · Birimler kN, m, kPa · Gerilmede çekme pozitif")
        self.coords = QLabel("x: —   y: —")
        self.coords.setMinimumWidth(190)
        self.addPermanentWidget(self.coords)
        self.toggles: dict[str, QToolButton] = {}
        self._canvas = None
        if with_toggles:
            for name, key, tip in (
                ("SNAP", "F9", "Izgara noktalarına yakala"),
                ("GRID", "F7", "Izgarayı göster"),
                ("ORTHO", "F8", "Yatay/düşey kısıtla"),
            ):
                b = QToolButton()
                b.setText(name)
                b.setCheckable(True)
                b.setStyleSheet(TOGGLE_CSS)
                b.setToolTip(f"{tip} ({key})")
                self.addPermanentWidget(b)
                self.toggles[name.lower()] = b
                sc = QShortcut(QKeySequence(key), parent or self)
                sc.setContext(Qt.WindowShortcut)
                sc.activated.connect(b.toggle)

    def attach(self, canvas) -> None:
        """Bind toggles to a CAD canvas (the one used for drawing)."""
        self._canvas = canvas
        canvas.cursor_changed.connect(lambda t: self.showMessage(t, 8000))
        snap = self.toggles.get("snap")
        grid = self.toggles.get("grid")
        ortho = self.toggles.get("ortho")
        if snap is not None:
            snap.blockSignals(True)
            snap.setChecked(canvas.snapping)
            snap.blockSignals(False)
            snap.toggled.connect(lambda on: setattr(canvas, "snapping", on))
        if grid is not None:
            grid.blockSignals(True)
            grid.setChecked(canvas.grid > 0)
            grid.blockSignals(False)
            grid.toggled.connect(
                lambda on: setattr(canvas, "grid", canvas.grid if on else 0.0)
            )
        if ortho is not None:
            ortho.blockSignals(True)
            ortho.setChecked(canvas.ortho)
            ortho.blockSignals(False)
            ortho.toggled.connect(lambda on: setattr(canvas, "ortho", on))

    def show_coords(self, x: float, y: float) -> None:
        self.coords.setText(f"x: {x:10.3f}   y: {y:10.3f}")

    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802 (Qt API)
        super().showMessage(text, timeout)
