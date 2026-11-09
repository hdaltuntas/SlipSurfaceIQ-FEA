"""Read-only, stage-aware normal-contact point table and lossless CSV export."""

from collections import Counter

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..io.report import export_contact_csv
from ..post.contact_results import contact_points, normal_contact_tags
from .contact_history import ContactHistoryDialog
from .contact_resultants import ContactResultantsDialog


class ContactResultsDialog(QDialog):
    def __init__(self, result, stage_index=0, tag=None, parent=None):
        super().__init__(parent)
        self.result = result
        self.snapshots = [result.initial, *result.stages]
        self.points = ()
        self._history_window = None
        self._resultants_window = None
        self.setWindowTitle("Normal contact · stored integration-point results")
        self.resize(1080, 600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.stage = QComboBox()
        for i, snapshot in enumerate(self.snapshots):
            self.stage.addItem(f"{i}: {snapshot.name}", i)
        self.stage.setCurrentIndex(max(0, min(stage_index, len(self.snapshots) - 1)))
        self.interface = QComboBox()
        self.interface.addItem("All normal-contact interfaces", None)
        for key in normal_contact_tags(result.model):
            self.interface.addItem(key, key)
        self.interface.setCurrentIndex(max(0, self.interface.findData(tag)))
        form.addRow("Stage", self.stage)
        form.addRow("Interface", self.interface)
        layout.addLayout(form)
        note = QLabel(
            "Stored gap: positive = opening, negative = penalty penetration (mm). "
            "Pressure is compression-positive (kPa); stored normal traction is tension-positive. "
            "Contact state is categorical, not a plastic flag. No point averaging. "
            "Coordinates and node IDs refer to the undeformed mesh; CSV gap is in metres."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Interface", "Element", "Point", "Face 1 node", "Face 2 node", "x (m)", "y (m)",
            "Gap (mm)", "Pressure (kPa)", "Contact state", "Data",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.history_button = QPushButton("Selected point history…")
        self.history_button.clicked.connect(self.show_history)
        self.table.itemSelectionChanged.connect(self.update_history_button)
        self.resultants_button = QPushButton("Interface force / moment…")
        self.resultants_button.clicked.connect(self.show_resultants)
        self.csv_button = QPushButton("Selected stage CSV…")
        self.all_csv_button = QPushButton("All stages CSV…")
        self.csv_button.clicked.connect(lambda: self.export(False))
        self.all_csv_button.clicked.connect(lambda: self.export(True))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (self.history_button, self.resultants_button, self.csv_button,
                       self.all_csv_button, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.stage.currentIndexChanged.connect(self.refresh)
        self.interface.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        selected = self.selected_point()
        identity = None if selected is None else (selected.tag, selected.element, selected.point)
        self.history_button.setEnabled(False)
        self.resultants_button.setEnabled(False)
        self.points = ()
        self.table.setRowCount(0)
        self.csv_button.setEnabled(False)
        self.all_csv_button.setEnabled(False)
        try:
            snapshot = self.snapshots[self.stage.currentIndex()]
            self.points = contact_points(self.result, snapshot, self.interface.currentData())
        except (ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Contact data rejected: {exc}")
            return
        if not self.points:
            self.status.setText("No normal-contact results. Goodman interfaces are not gap data.")
            return
        self.resultants_button.setEnabled(True)
        self.table.setRowCount(len(self.points))
        for row, point in enumerate(self.points):
            values = [
                point.tag, str(point.element), str(point.point), str(point.face1_node),
                str(point.face2_node), f"{point.x_m:.8g}", f"{point.y_m:.8g}",
                "—" if point.gap_m is None else f"{point.gap_m * 1000:.8g}",
                "—" if point.pressure_kpa is None else f"{point.pressure_kpa:.8g}",
                point.status, point.availability,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        counts = Counter(p.status for p in self.points)
        self.status.setText(
            f"{snapshot.name} · accepted λ={snapshot.lam:.6g} · "
            + " · ".join(f"{label}: {count}" for label, count in sorted(counts.items()))
            + ". Missing/inactive measurements are blank, never zero."
        )
        self.csv_button.setEnabled(True)
        self.all_csv_button.setEnabled(True)
        row = next((i for i, p in enumerate(self.points)
                    if (p.tag, p.element, p.point) == identity), 0)
        self.table.setCurrentCell(row, 0)
        self.update_history_button()

    def selected_point(self):
        row = self.table.currentRow()
        return self.points[row] if 0 <= row < len(self.points) else None

    def update_history_button(self):
        self.history_button.setEnabled(self.selected_point() is not None)

    def show_history(self):
        point = self.selected_point()
        if point is None:
            return
        if self._history_window is not None:
            self._history_window.close()
            self._history_window.deleteLater()
        self._history_window = ContactHistoryDialog(
            self.result, point.tag, point.element, point.point,
            self.stage.currentIndex(), self,
        )
        self._history_window.show()

    def show_resultants(self):
        if not self.points:
            return
        if self._resultants_window is not None:
            self._resultants_window.close()
            self._resultants_window.deleteLater()
        self._resultants_window = ContactResultantsDialog(
            self.result, self.stage.currentIndex(), self.interface.currentData(), self,
        )
        self._resultants_window.show()

    def export(self, all_stages=False):
        path, _ = QFileDialog.getSaveFileName(self, "Export contact points", "contact.csv",
                                             "CSV (*.csv)")
        if not path:
            return
        try:
            export_contact_csv(self.result, path, self.snapshots[self.stage.currentIndex()],
                               tag=self.interface.currentData(), all_stages=all_stages)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Export rejected: {exc}")
            return
        self.status.setText(f"Exported contact points: {path}")
