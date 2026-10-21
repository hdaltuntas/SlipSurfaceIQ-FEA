"""Native, stage-aware query-line and liner N/V/M charts."""

import csv

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..post.inspection import beam_paths, field_unit, line_profile


class TracePlot(QWidget):
    def __init__(self, title="", unit="", parent=None):
        super().__init__(parent)
        self.title, self.unit = title, unit
        self.x = self.y = np.array([])
        self.setMinimumSize(480, 240)

    def set_data(self, x, y, title=None, unit=None):
        self.x, self.y = np.asarray(x), np.asarray(y)
        if title is not None:
            self.title = title
        if unit is not None:
            self.unit = unit
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QColor("#213547"))
        p.drawText(16, 24, f"{self.title} · {self.unit}")
        box = QRectF(92, 48, max(1, self.width() - 116), max(1, self.height() - 110))
        p.drawRect(box)
        finite = np.isfinite(self.x) & np.isfinite(self.y)
        if not finite.any():
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "Aktif sonuç yok")
            return
        xmin, xmax = float(self.x.min()), float(self.x.max())
        ymin, ymax = min(0.0, float(self.y[finite].min())), max(0.0, float(self.y[finite].max()))
        dy = ymax - ymin
        if dy < 1e-12:
            dy = max(abs(ymax), 1.0)
        ymin, ymax = ymin - 0.07 * dy, ymax + 0.07 * dy

        def screen(x, y):
            return (
                box.left() + (x - xmin) / max(xmax - xmin, 1e-15) * box.width(),
                box.bottom() - (y - ymin) / (ymax - ymin) * box.height(),
            )

        p.setPen(QPen(QColor("#cbd5e1"), 1, Qt.PenStyle.DashLine))
        p.drawLine(
            int(box.left()), int(screen(xmin, 0)[1]), int(box.right()), int(screen(xmin, 0)[1])
        )
        path, connected = QPainterPath(), False
        for x, y, valid in zip(self.x, self.y, finite):
            if not valid:
                connected = False
                continue
            xx, yy = screen(x, y)
            path.lineTo(xx, yy) if connected else path.moveTo(xx, yy)
            connected = True
        p.setPen(QPen(QColor("#087f9b"), 2))
        p.drawPath(path)
        p.setPen(QColor("#213547"))
        for i in range(5):
            value = ymin + (ymax - ymin) * i / 4
            p.drawText(3, int(screen(xmin, value)[1]) + 5, f"{value:.4g}")
        p.drawText(int(box.left()), int(box.bottom()) + 22, f"{xmin:.5g}")
        p.drawText(int(box.right()) - 55, int(box.bottom()) + 22, f"{xmax:.5g}")
        p.drawText(int(box.center().x()) - 65, self.height() - 12, "Yol mesafesi s (m)")


class QueryDialog(QDialog):
    line_changed = Signal(object)

    def __init__(self, result, stage, parent=None):
        super().__init__(parent)
        self.result, self.stage, self.profile = result, stage, None
        self.setWindowTitle(f"Sorgu çizgisi · {stage.name}")
        self.resize(850, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        lo, hi = result.model.mesh.coords.min(0), result.model.mesh.coords.max(0)
        self.start = QLineEdit(f"{lo[0]:.8g}, {(lo[1] + hi[1]) / 2:.8g}")
        self.end = QLineEdit(f"{hi[0]:.8g}, {(lo[1] + hi[1]) / 2:.8g}")
        self.field = QComboBox()
        self.field.addItems(
            [
                "|u|",
                "ux",
                "uy",
                "sxx",
                "syy",
                "szz",
                "txy",
                "s1",
                "s2",
                "s3",
                "q",
                "pore",
                "excess_pore",
            ]
        )
        self.count = QSpinBox()
        self.count.setRange(2, 10001)
        self.count.setValue(101)
        self.region = QComboBox()
        self.region.addItem("Tüm aktif bölgeler", None)
        for r in sorted(result.model.mesh.regions()):
            self.region.addItem(str(r), r)
        for label, widget in [
            ("Başlangıç x,y (m)", self.start),
            ("Bitiş x,y (m)", self.end),
            ("Alan", self.field),
            ("Örnek sayısı", self.count),
            ("Bölge / sınır tarafı", self.region),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        note = QLabel(
            "Deforme olmamış koordinatlar. Boşluk/pasif elemanda veri yoktur; "
            "grafik boşlukları birleştirmez. Gerilmeler eleman içi GP ekstrapolasyonudur. "
            "Tam sınırda ilk eleman seçilir; taraf için bölge filtresini kullanın."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.plot = TracePlot()
        layout.addWidget(self.plot, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for label, slot in [("Sorgula", self.query), ("CSV", self.export), ("Kapat", self.accept)]:
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)

    def query(self):
        try:
            a = tuple(map(float, self.start.text().replace(",", " ").split()))
            b = tuple(map(float, self.end.text().replace(",", " ").split()))
            self.profile = line_profile(
                self.result,
                a,
                b,
                self.field.currentText(),
                self.count.value(),
                self.stage,
                self.region.currentData(),
            )
            p = self.profile
            self.plot.set_data(p.distance, p.values, p.field, p.unit)
            self.status.setText(f"{np.isfinite(p.values).sum()}/{len(p.values)} aktif örnek")
            self.line_changed.emit((a, b))
        except Exception as exc:
            self.profile = None
            self.plot.set_data([], [])
            self.status.setText(str(exc))

    def export(self):
        if self.profile is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Çizgi sorgusu", "sorgu.csv", "CSV (*.csv)")
        if path:
            try:
                self.export_path(path)
            except Exception as exc:
                self.status.setText(str(exc))

    def export_path(self, path):
        p = self.profile
        with open(path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["s_m", "x_m", "y_m", "region", f"{p.field}_{field_unit(p.field)}"])
            for s, xy, r, v in zip(p.distance, p.xy, p.regions, p.values):
                writer.writerow([s, *xy, r if r >= 0 else "", v if np.isfinite(v) else ""])


class BeamDiagramDialog(QDialog):
    def __init__(self, result, stage, parent=None):
        super().__init__(parent)
        self.result, self.stage, self.paths = result, stage, []
        self.setWindowTitle(f"Liner N–V–M · {stage.name}")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.tag, self.path = QComboBox(), QComboBox()
        self.tag.addItems(sorted(stage.beams))
        controls.addWidget(QLabel("Yapı"))
        controls.addWidget(self.tag)
        controls.addWidget(QLabel("Bağlantılı yol"))
        controls.addWidget(self.path)
        layout.addLayout(controls)
        note = QLabel(
            "Yerel x yol yönünde, y buna 90° saat yönü tersi. N çekme (+). "
            "Kesit N/V/M: başlangıçta −yerel düğüm etkisi, bitişte +yerel etki. "
            "Ters elemanda uçlar yer değiştirir, M işaret değiştirir; N/V korunur. "
            "Ortak uçlar ortalanmaz; dallar ve pasif parçalar ayrı yoldur."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        self.plots = [
            TracePlot(title, unit) for title, unit in [("N", "kN/m"), ("V", "kN/m"), ("M", "kNm/m")]
        ]
        for title, plot in zip(["Normal kuvvet N", "Kesme kuvveti V", "Moment M"], self.plots):
            self.tabs.addTab(plot, title)
        layout.addWidget(self.tabs, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for title, slot in [
            ("Yol CSV", self.export),
            ("Grafik PNG", self.export_image),
            ("Kapat", self.accept),
        ]:
            button = QPushButton(title)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self.tag.currentTextChanged.connect(self.refresh)
        self.path.currentIndexChanged.connect(self.draw)
        self.refresh()

    def refresh(self):
        try:
            self.paths = (
                beam_paths(self.result, self.tag.currentText(), self.stage)
                if self.tag.currentText()
                else []
            )
            self.path.blockSignals(True)
            self.path.clear()
            self.path.addItems([str(i + 1) for i in range(len(self.paths))])
            self.path.blockSignals(False)
            self.draw()
        except Exception as exc:
            self.paths = []
            self.draw()
            self.status.setText(str(exc))

    def draw(self):
        i = self.path.currentIndex()
        if i < 0 or i >= len(self.paths):
            for plot in self.plots:
                plot.set_data([], [])
            self.status.setText("Bu aşamada aktif liner yok.")
            return
        path = self.paths[i]
        for j, plot in enumerate(self.plots):
            plot.set_data(path.distance.ravel(), path.forces[..., j].ravel())
        a, b = path.nodes[0, 0], path.nodes[-1, 1]
        X = self.result.model.mesh.coords
        self.status.setText(
            f"Yol başlangıcı: düğüm {a} ({X[a, 0]:.4g}, {X[a, 1]:.4g}) → "
            f"bitişi: düğüm {b} ({X[b, 0]:.4g}, {X[b, 1]:.4g}) m · "
            f"{len(path.elements)} eleman · s={path.distance[-1, 1]:.5g} m"
        )

    def export(self):
        if not self.paths:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Liner yolu", "liner.csv", "CSV (*.csv)")
        if path:
            try:
                self.export_path(path)
            except Exception as exc:
                self.status.setText(str(exc))

    def export_path(self, filename):
        path = self.paths[self.path.currentIndex()]
        with open(filename, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["element", "node", "s_m", "N_kN_m", "V_kN_m", "M_kNm_m"])
            for e, nodes, s, f in zip(path.elements, path.nodes, path.distance, path.forces):
                for node, station, forces in zip(nodes, s, f):
                    writer.writerow([e, node, station, *forces])

    def export_image(self):
        path, _ = QFileDialog.getSaveFileName(self, "Liner grafiği", "liner.png", "PNG (*.png)")
        if path and not self.tabs.currentWidget().grab().save(path, "PNG"):
            self.status.setText("PNG kaydedilemedi.")
