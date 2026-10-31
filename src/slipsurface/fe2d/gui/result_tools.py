"""Native, stage-aware query-line and liner N/V/M charts."""

import csv

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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


FORCE_COMPONENTS = {
    "beam": [
        ("N", "Normal kuvvet N", "kN/m"),
        ("V", "Kesme kuvveti V", "kN/m"),
        ("M", "Eğilme momenti M", "kNm/m"),
    ],
    "bar": [("N", "Eksenel kuvvet N", "kN")],
}


def structure_segments(result, stage, tag):
    """``(kind, segments)`` of one structure: per element its end points (traversal order),
    distance stations and end forces ``(2, ncomp)``; inactive elements are left out."""
    from ..core.enums import ElemType

    mesh = result.model.mesh
    block = mesh.block(tag)
    X = mesh.coords
    segments = []
    if block.etype is ElemType.BEAM2:
        for path in beam_paths(result, tag, stage):
            for (a, b), s, f in zip(path.nodes, path.distance, path.forces):
                segments.append((X[a], X[b], s, np.asarray(f, float)))
        return "beam", segments
    if block.etype is ElemType.BAR2:
        forces = stage.bars.get(tag)
        if forces is None:
            return "bar", []
        active = stage.active.get(tag, np.ones(block.ne, bool))
        distance = 0.0
        for e in np.flatnonzero(active):
            a, b = block.conn[e]
            length = float(np.linalg.norm(X[b] - X[a]))
            n = float(np.ravel(forces[e])[0])
            segments.append((X[a], X[b], (distance, distance + length), np.array([[n], [n]])))
            distance += length
        return "bar", segments
    raise ValueError(f"'{tag}' bir kiriş/kazık veya ankraj değil.")


def diagram_amplitude(segments, component, extent, fraction=0.22):
    """World-unit scale so the largest ordinate is ``fraction`` of ``extent``."""
    peak = max(
        (abs(float(v)) for *_, f in segments for v in np.asarray(f)[:, component]),
        default=0.0,
    )
    return fraction * extent / max(peak, 1e-30)


def force_diagram_line(segments, component, amplitude):
    """Offset polyline vertices ``(xy, value)`` of the section-force diagram."""
    pts = []
    for a, b, _, f in segments:
        a, b = np.asarray(a, float), np.asarray(b, float)
        tangent = (b - a) / max(float(np.linalg.norm(b - a)), 1e-30)
        normal = np.array([-tangent[1], tangent[0]])
        fa, fb = float(f[0, component]), float(f[1, component])
        pts.append((a + amplitude * fa * normal, fa))
        pts.append((b + amplitude * fb * normal, fb))
    return pts


def segment_end_displacements(result, stage, segments):
    """``s, |u|, ux, uy`` at each segment end, in traversal order."""
    X = result.model.mesh.coords
    s_vals, ux, uy = [], [], []
    for a, b, station, _f in segments:
        station = np.asarray(station, float).reshape(-1)
        for pt, st in ((a, station[0]), (b, station[-1])):
            i = int(np.argmin(np.sum((X - pt) ** 2, axis=1)))
            u = stage.u[i]
            s_vals.append(float(st))
            ux.append(float(u[0]) if np.isfinite(u[0]) else np.nan)
            uy.append(float(u[1]) if np.isfinite(u[1]) else np.nan)
    s_vals = np.asarray(s_vals, float)
    ux, uy = np.asarray(ux, float), np.asarray(uy, float)
    return s_vals, np.hypot(ux, uy), ux, uy


def beam_profile_tags(model):
    """``(tag, label)`` for liners and piles (beam members), in display order."""
    from .editing import structure_label

    tags = []
    for tag, kind in model.structure_tags().items():
        if kind != "beam":
            continue
        tags.append((tag, structure_label(model, tag)))
    return tags


class StructureDiagram(QWidget):
    """Force diagram drawn on the structure itself, perpendicular to its axis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments, self.component, self.unit = [], 0, ""
        self.setMinimumSize(420, 420)

    def set_data(self, segments, component, unit):
        self.segments, self.component, self.unit = segments, component, unit
        self.update()

    def extremes(self):
        values = [
            (float(f[k, self.component]), np.asarray(a if k == 0 else b, float))
            for a, b, _, f in self.segments
            for k in (0, 1)
        ]
        if not values:
            return None
        return min(values, key=lambda v: v[0]), max(values, key=lambda v: v[0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        if not self.segments:
            p.setPen(QColor("#526677"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Bu aşamada aktif eleman yok")
            return
        pts = np.array([pt for a, b, _, _ in self.segments for pt in (a, b)], float)
        lo, hi = pts.min(0), pts.max(0)
        extent = max(float(np.ptp(pts, axis=0).max()), 1e-9)
        amplitude = diagram_amplitude(self.segments, self.component, extent)
        # World box including the diagram, then an equal-aspect map into the widget.
        lo, hi = lo - 0.3 * extent, hi + 0.3 * extent
        margin = 30
        scale = min(
            (self.width() - 2 * margin) / (hi[0] - lo[0]),
            (self.height() - 2 * margin) / (hi[1] - lo[1]),
        )
        cx, cy = (lo + hi) / 2

        def screen(xy):
            return QPointF(
                self.width() / 2 + (xy[0] - cx) * scale, self.height() / 2 - (xy[1] - cy) * scale
            )

        p.setPen(QPen(QColor("#213547"), 3))
        for a, b, _, _ in self.segments:
            p.drawLine(screen(a), screen(b))
        line = force_diagram_line(self.segments, self.component, amplitude)
        path = QPainterPath()
        for i, (xy, _value) in enumerate(line):
            pt = screen(xy)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor("#156798"), 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        ext = self.extremes()
        p.setPen(QColor("#213547"))
        for label, (value, where) in zip(("min", "maks"), ext):
            at = screen(where)
            p.drawEllipse(at, 3, 3)
            p.drawText(at + QPointF(6, -6), f"{label} {value:.4g} {self.unit}")


class StructureForceDialog(QDialog):
    """Plaxis-style section forces of one pile/liner/anchor, on the structure and along s."""

    def __init__(self, result, stage_index, tag, parent=None):
        super().__init__(parent)
        from .editing import structure_label

        self.result, self.tag = result, tag
        self.setWindowTitle(f"Kesit tesirleri · {structure_label(result.model, tag)}")
        self.resize(980, 680)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.stage = QComboBox()
        snapshots = [result.initial, *result.stages]
        for i, st in enumerate(snapshots):
            self.stage.addItem(st.name, i)
        controls.addWidget(QLabel("Aşama"))
        controls.addWidget(self.stage, 1)
        self.component = QComboBox()
        controls.addWidget(QLabel("Kesit tesiri"))
        controls.addWidget(self.component, 1)
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.diagram = StructureDiagram()
        self.trace = TracePlot()
        self.tabs.addTab(self.diagram, "Yapı üzerinde")
        self.tabs.addTab(self.trace, "Uzunluk boyunca")
        self.disp_plots = [
            TracePlot(title, "m") for title in ("|u|", "ux", "uy")
        ]
        disp_page = QWidget()
        disp_layout = QVBoxLayout(disp_page)
        disp_layout.setContentsMargins(0, 0, 0, 0)
        for plot in self.disp_plots:
            disp_layout.addWidget(plot, 1)
        self.tabs.addTab(disp_page, "Deplasman")
        layout.addWidget(self.tabs, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        for title, slot in [("Grafik PNG", self.export_image), ("Kapat", self.accept)]:
            button = QPushButton(title)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self.kind, self.segments = "beam", []
        self.stage.currentIndexChanged.connect(self.refresh)
        self.component.currentIndexChanged.connect(self.draw)
        shown = max(0, min(stage_index, len(snapshots) - 1))
        if not self._has_forces(shown):
            for i in range(len(snapshots) - 1, -1, -1):
                if self._has_forces(i):
                    shown = i
                    break
        self.stage.setCurrentIndex(shown)
        self.refresh()

    def _has_forces(self, index: int) -> bool:
        snapshots = [self.result.initial, *self.result.stages]
        if not 0 <= index < len(snapshots):
            return False
        try:
            _, segments = structure_segments(self.result, snapshots[index], self.tag)
        except Exception:
            return False
        return any(np.isfinite(f).any() for *_, f in segments)

    def refresh(self, *_):
        i = self.stage.currentData() or 0
        st = self.result.initial if i == 0 else self.result.stages[i - 1]
        try:
            self.kind, self.segments = structure_segments(self.result, st, self.tag)
        except Exception as exc:
            self.kind, self.segments = "beam", []
            self.status.setText(str(exc))
        current = self.component.currentIndex()
        self.component.blockSignals(True)
        self.component.clear()
        for _, title, unit in FORCE_COMPONENTS[self.kind]:
            self.component.addItem(f"{title} ({unit})")
        self.component.setCurrentIndex(max(0, min(current, self.component.count() - 1)))
        self.component.blockSignals(False)
        self.draw()

    def draw(self, *_):
        items = FORCE_COMPONENTS[self.kind]
        k = max(0, min(self.component.currentIndex(), len(items) - 1))
        key, title, unit = items[k]
        self.diagram.set_data(self.segments, k, unit)
        s = np.array([st for *_, st, _ in self.segments], float).reshape(-1)
        values = np.array([f[:, k] for *_, f in self.segments], float).reshape(-1)
        self.trace.set_data(s, values, title, unit)
        i = self.stage.currentData() or 0
        st = self.result.initial if i == 0 else self.result.stages[i - 1]
        ds, umag, ux, uy = segment_end_displacements(self.result, st, self.segments)
        for plot, y, name in zip(self.disp_plots, (umag, ux, uy), ("|u|", "ux", "uy")):
            plot.set_data(ds, y, name, "m")
        ext = self.diagram.extremes()
        if ext is None:
            self.status.setText("Bu aşamada yapı pasif; kesit tesiri yok.")
            return
        (vmin, pmin), (vmax, pmax) = ext
        ranges = []
        for j, (name, _, unit) in enumerate(FORCE_COMPONENTS[self.kind]):
            col = np.array([f[:, j] for *_, f in self.segments], float)
            ranges.append(f"{name} [{np.nanmin(col):.4g}, {np.nanmax(col):.4g}] {unit}")
        self.status.setText(
            f"{key}: min {vmin:.5g} {unit} @ ({pmin[0]:.3g}, {pmin[1]:.3g}) m · "
            f"maks {vmax:.5g} {unit} @ ({pmax[0]:.3g}, {pmax[1]:.3g}) m · "
            + " · ".join(ranges)
            + f" · {len(self.segments)} eleman · N çekme (+)"
        )

    def export_image(self):
        path, _ = QFileDialog.getSaveFileName(self, "Kesit tesiri", "kesit.png", "PNG (*.png)")
        if path and not self.tabs.currentWidget().grab().save(path, "PNG"):
            self.status.setText("PNG kaydedilemedi.")


class StructureDisplacementDialog(QDialog):
    """Displacement along tunnel lining and piles, as line charts vs path length."""

    def __init__(self, result, stage_index, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Deplasman · tünel / kazık")
        self.resize(920, 640)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.stage = QComboBox()
        snapshots = [result.initial, *result.stages]
        for i, st in enumerate(snapshots):
            self.stage.addItem(st.name, i)
        self.tag = QComboBox()
        for tag, label in beam_profile_tags(result.model):
            self.tag.addItem(label, tag)
        controls.addWidget(QLabel("Aşama"))
        controls.addWidget(self.stage, 1)
        controls.addWidget(QLabel("Yapı"))
        controls.addWidget(self.tag, 1)
        layout.addLayout(controls)
        note = QLabel(
            "Kaplama (tünel çevresi) ve kazık boyunca düğüm deplasmanı. "
            "Kanvasta yalnız ısı haritası kalır; sayısal değerler bu grafiktedir."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.plots = [TracePlot(title, "m") for title in ("|u|", "ux", "uy")]
        for plot in self.plots:
            layout.addWidget(plot, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        shown = max(0, min(stage_index, len(snapshots) - 1))
        self.stage.setCurrentIndex(shown)
        self.stage.currentIndexChanged.connect(self.draw)
        self.tag.currentIndexChanged.connect(self.draw)
        self.draw()

    def draw(self, *_):
        tag = self.tag.currentData()
        if not tag:
            for plot in self.plots:
                plot.set_data([], [])
            self.status.setText("Kaplama veya kazık yok.")
            return
        i = self.stage.currentData() or 0
        st = self.result.initial if i == 0 else self.result.stages[i - 1]
        try:
            _kind, segments = structure_segments(self.result, st, tag)
        except Exception as exc:
            for plot in self.plots:
                plot.set_data([], [])
            self.status.setText(str(exc))
            return
        s, umag, ux, uy = segment_end_displacements(self.result, st, segments)
        for plot, y, name in zip(self.plots, (umag, ux, uy), ("|u|", "ux", "uy")):
            plot.set_data(s, y, name, "m")
        finite = np.isfinite(umag)
        if not finite.any():
            self.status.setText("Bu aşamada yapı pasif; deplasman yok.")
            return
        imin, imax = int(np.nanargmin(umag)), int(np.nanargmax(umag))
        self.status.setText(
            f"|u| min {umag[imin]:.5g} m @ s={s[imin]:.4g} m · "
            f"maks {umag[imax]:.5g} m @ s={s[imax]:.4g} m · "
            f"{len(segments)} eleman"
        )
