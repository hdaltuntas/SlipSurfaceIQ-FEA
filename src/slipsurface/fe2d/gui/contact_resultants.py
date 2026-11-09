"""Read-only, stage-aware contact actions and explicit moment-origin selection."""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..io.contact_resultants_csv import export_contact_resultants_csv
from ..post.contact_resultants import contact_resultants, moment_origin
from ..post.contact_results import normal_contact_tags


class ContactResultantsDialog(QDialog):
    def __init__(self, result, stage_index=0, tag=None, parent=None):
        super().__init__(parent)
        self.result = result
        self.snapshots = [result.initial, *result.stages]
        self.summaries = ()
        self.setWindowTitle("Normal contact · interface force and moment resultants")
        self.resize(1240, 450)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.stage = QComboBox()
        for i, st in enumerate(self.snapshots):
            self.stage.addItem(f"{i}: {st.name}", i)
        self.stage.setCurrentIndex(max(0, min(stage_index, len(self.snapshots)-1)))
        self.interface = QComboBox()
        self.interface.addItem("All normal-contact interfaces (kept separate)", None)
        for key in normal_contact_tags(result.model):
            self.interface.addItem(key, key)
        self.interface.setCurrentIndex(max(0, self.interface.findData(tag)))
        form.addRow("Stage", self.stage)
        form.addRow("Interface", self.interface)
        self.origin_x, self.origin_y = QLineEdit("0"), QLineEdit("0")
        self.apply_button = QPushButton("Apply moment origin")
        origin_row = QHBoxLayout()
        for item in (QLabel("x (m)"), self.origin_x, QLabel("y (m)"), self.origin_y,
                     self.apply_button):
            origin_row.addWidget(item)
        form.addRow("Moment origin", origin_row)
        layout.addLayout(form)
        note = QLabel(
            "Contact ACTIONS ON each face: Fx, Fy (kN/m), Mz (kN·m/m), counter-clockwise positive. "
            "Native internal-force contributions have the opposite sign (both exported to CSV). "
            "Arms use undeformed coordinates. These are NOT support reactions or a complete "
            "external equilibrium/capacity check. Pressure integral = sum(w·p), "
            "not vector magnitude. "
            "Inactive elements are excluded; missing active evidence leaves totals blank."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels([
            "Interface", "Data", "Elements\nactive/total", "Points\navailable/active",
            "Active length\n(m)", "∑w·p\n(kN/m)", "Face 1 Fx\n(kN/m)", "Face 1 Fy\n(kN/m)",
            "Face 1 Mz\n(kN·m/m)", "Face 2 Fx\n(kN/m)", "Face 2 Fy\n(kN/m)", "Face 2 Mz\n(kN·m/m)",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.csv_button, self.all_csv_button = QPushButton("Selected stage CSV…"), QPushButton(
            "All stages CSV…")
        close = QPushButton("Close")
        for button in (self.csv_button, self.all_csv_button, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        close.clicked.connect(self.accept)
        self.csv_button.clicked.connect(lambda: self.export(False))
        self.all_csv_button.clicked.connect(lambda: self.export(True))
        self.stage.currentIndexChanged.connect(self.refresh)
        self.interface.currentIndexChanged.connect(self.refresh)
        self.origin_x.textChanged.connect(self.invalidate)
        self.origin_y.textChanged.connect(self.invalidate)
        self.apply_button.clicked.connect(self.refresh)
        self.refresh()

    def invalidate(self, *_):
        self.summaries = ()
        self.table.setRowCount(0)
        self.csv_button.setEnabled(False)
        self.all_csv_button.setEnabled(False)
        self.status.setText("Moment origin changed. Apply to recalculate; stale totals cleared.")

    def origin(self):
        return moment_origin((float(self.origin_x.text()), float(self.origin_y.text())))

    def refresh(self, *_):
        self.invalidate()
        try:
            origin = self.origin()
            snapshot = self.snapshots[self.stage.currentIndex()]
            self.summaries = contact_resultants(self.result, snapshot, self.interface.currentData(),
                                                origin=origin)
        except (ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Contact resultants rejected: {exc}")
            return
        if not self.summaries:
            self.status.setText("No normal-contact interfaces. Goodman is not normal-contact data.")
            return
        self.table.setRowCount(len(self.summaries))

        def show(value):
            return "—" if value is None else f"{value:.8g}"

        for i, row in enumerate(self.summaries):
            values = [
                row.tag, row.availability, f"{row.active_elements}/{row.element_count}",
                f"{row.available_points}/{row.available_points+row.unavailable_points}",
                show(row.active_length_m), show(row.pressure_integral),
                *(show(None if face is None else getattr(face, part))
                  for face in (row.face1, row.face2) for part in ("fx", "fy", "moment")),
            ]
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.status.setText(
            f"Snapshot {self.stage.currentIndex()}: {snapshot.name} · moment origin "
            f"({origin[0]:.8g}, {origin[1]:.8g}) m · fixed-frame solver quadrature. "
            "Opposite faces are not summed into a misleading zero total."
        )
        self.csv_button.setEnabled(True)
        self.all_csv_button.setEnabled(True)

    def export(self, all_stages=False):
        path, _ = QFileDialog.getSaveFileName(self, "Export interface contact resultants",
                                             "contact-resultants.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            export_contact_resultants_csv(
                self.result, path, stage_index=None if all_stages else self.stage.currentIndex(),
                tag=self.interface.currentData(), origin=self.origin(),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Export rejected: {exc}")
            return
        self.status.setText(f"Exported contact actions and internal contributions: {path}")
