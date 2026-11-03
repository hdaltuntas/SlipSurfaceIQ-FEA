"""Native consolidation settlement calculation dialog (independent of FEM)."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..analysis.consolidation import ConsolidationInput


class ConsolidationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Consolidation settlement · Terzaghi 1D")
        self.resize(620, 570)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Independent oedometer-based primary consolidation estimate. "
            "This is NOT a coupled FEM pore-pressure/consolidation analysis. "
            "Enter layer-average initial effective stress and stress increment."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.controls = {}
        fields = [
            ("thickness", "Compressible layer thickness H (m)", 5.0),
            ("sigma_initial", "Initial vertical effective stress σ'v0 (kPa)", 100.0),
            ("delta_sigma", "Vertical stress increment Δσv (kPa)", 50.0),
            ("compression_index", "Compression index Cc (–)", 0.25),
            ("void_ratio", "Initial void ratio e0 (–)", 0.8),
            ("cv", "Consolidation coefficient cv (m²/day)", 0.001),
        ]
        for key, label, default in fields:
            field = QDoubleSpinBox()
            field.setDecimals(6)
            field.setRange(-1e6 if key == "delta_sigma" else 0, 1e9)
            field.setValue(default)
            self.controls[key] = field
            form.addRow(label, field)
        self.drainage = QComboBox()
        self.drainage.addItem("Double drainage (Hdr = H/2)", "double")
        self.drainage.addItem("Single drainage (Hdr = H)", "single")
        form.addRow("Drainage", self.drainage)
        layout.addLayout(form)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time (days)", "U (%)", "Settlement (mm)"])
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for widget in self.controls.values():
            widget.valueChanged.connect(self.calculate)
        self.drainage.currentIndexChanged.connect(self.calculate)
        self.calculate()

    def calculate(self, *_):
        try:
            data = ConsolidationInput(
                **{key: widget.value() for key, widget in self.controls.items()},
                drainage=self.drainage.currentData(),
            )
            ultimate = data.final_settlement()
            t90 = data.time_to_90()
            self.message.setText(
                f"Final primary settlement S∞ = {ultimate * 1000:.2f} mm · "
                f"t90 = {t90:.1f} days · drainage path = {data.drainage_path:.3g} m"
            )
            times = (0.0, t90 * 0.1, t90 * 0.25, t90 * 0.5, t90, t90 * 2, t90 * 5)
            self.table.setRowCount(len(times))
            for row, days in enumerate(times):
                values = (f"{days:.3f}", f"{100 * data.degree(days):.2f}",
                          f"{1000 * data.settlement(days):.3f}")
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~item.flags().ItemIsEditable)
                    self.table.setItem(row, col, item)
        except ValueError as exc:
            self.message.setText(f"Invalid input: {exc}")
            self.table.setRowCount(0)
