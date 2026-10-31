"""Vector-drawn toolbar icons (no external image files).

Each icon is painted on a 64x64 logical canvas and returned as a QIcon with
24/32/48 px pixmaps, so it stays crisp on HiDPI screens.
"""

from __future__ import annotations

import math
from functools import cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK = QColor("#2d3a4a")
BLUE = QColor("#2f6fd6")
GREEN = QColor("#2e9d4f")
RED = QColor("#d23b2f")
ORANGE = QColor("#f08a24")
YELLOW = QColor("#f0c800")
GREY = QColor("#8a95a3")
BROWN = QColor("#a5753c")


def _pen(c=INK, w=4.0, style=Qt.SolidLine):
    p = QPen(c, w, style)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _magnifier(p: QPainter, sign: str | None = None, rect=False):
    p.setPen(_pen(INK, 5))
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawEllipse(QPointF(26, 26), 16, 16)
    p.setPen(_pen(INK, 8))
    p.drawLine(QPointF(38, 38), QPointF(56, 56))
    p.setPen(_pen(BLUE, 4.5))
    if sign in ("+", "-"):
        p.drawLine(QPointF(18, 26), QPointF(34, 26))
    if sign == "+":
        p.drawLine(QPointF(26, 18), QPointF(26, 34))
    if rect:
        p.setPen(_pen(BLUE, 3, Qt.DashLine))
        p.drawRect(QRectF(17, 19, 18, 14))


def _vertex(p, x, y, c=INK):
    p.setPen(_pen(c, 2))
    p.setBrush(QColor("white"))
    p.drawRect(QRectF(x - 4.5, y - 4.5, 9, 9))


def _draw(name: str, p: QPainter) -> None:
    if name == "new":
        p.setPen(_pen(INK, 3.5))
        p.setBrush(QColor("white"))
        p.drawPolygon(_poly((14, 6), (40, 6), (52, 18), (52, 58), (14, 58)))
        p.drawPolyline(_poly((40, 6), (40, 18), (52, 18)))
    elif name == "open":
        p.setPen(_pen(BROWN, 3))
        p.setBrush(QColor("#f3c45a"))
        p.drawPolygon(_poly((6, 16), (24, 16), (28, 22), (54, 22), (54, 54), (6, 54)))
        p.setBrush(QColor("#ffd978"))
        p.drawPolygon(_poly((6, 54), (14, 30), (62, 30), (54, 54)))
    elif name == "save":
        p.setPen(_pen(QColor("#1f3d7a"), 3))
        p.setBrush(QColor("#3b6fc4"))
        p.drawRoundedRect(QRectF(8, 8, 48, 48), 4, 4)
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(18, 8, 28, 16))
        p.setBrush(QColor("#dfe7f5"))
        p.drawRect(QRectF(16, 34, 32, 22))
    elif name in ("undo", "redo"):
        p.save()
        if name == "redo":
            p.translate(64, 0)
            p.scale(-1, 1)
        path = QPainterPath(QPointF(50, 50))
        path.cubicTo(QPointF(54, 26), QPointF(36, 18), QPointF(18, 22))
        p.setPen(_pen(BLUE, 6))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setBrush(BLUE)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly((8, 22), (24, 10), (24, 34)))
        p.restore()
    elif name == "settings":
        p.setPen(_pen(INK, 3))
        p.setBrush(GREY)
        path = QPainterPath()
        for k in range(16):
            a = k * math.pi / 8
            r = 26 if k % 2 == 0 else 19
            pt = QPointF(32 + r * math.cos(a), 32 + r * math.sin(a))
            path.moveTo(pt) if k == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(32, 32), 8, 8)
    elif name == "summary":
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(12, 6, 40, 52))
        p.setPen(_pen(GREY, 3))
        for y in (18, 27, 36, 45):
            p.drawLine(QPointF(19, y), QPointF(45, y))
    elif name == "materials":
        for i, c in enumerate([YELLOW, GREEN, ORANGE, QColor("#8080d0")]):
            p.setPen(_pen(INK, 2))
            p.setBrush(c)
            p.drawRect(QRectF(8 + (i % 2) * 26, 8 + (i // 2) * 26, 22, 22))
    elif name == "compute":
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("#d8dde4"))
        p.drawRoundedRect(QRectF(6, 10, 52, 44), 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(GREEN)
        p.drawPolygon(_poly((24, 20), (46, 32), (24, 44)))
    elif name == "interpret":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 56), (4, 40), (24, 40), (42, 24), (60, 24), (60, 56)))
        path = QPainterPath(QPointF(20, 40))
        path.quadTo(QPointF(34, 54), QPointF(48, 24))
        p.setPen(_pen(RED, 3.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(_pen(GREEN, 2))
        p.drawLine(QPointF(30, 6), QPointF(20, 40))
        p.drawLine(QPointF(30, 6), QPointF(48, 24))
    elif name == "zoom_all":
        p.setPen(_pen(INK, 5))
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 32 - sx * 22, 32 - sy * 22
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * 12, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * 12))
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * 10, cy + sy * 10))
    elif name == "zoom_in":
        _magnifier(p, "+")
    elif name == "zoom_out":
        _magnifier(p, "-")
    elif name == "zoom_window":
        _magnifier(p, None, rect=True)
    elif name == "pan":
        p.setPen(_pen(INK, 4))
        p.drawLine(QPointF(32, 6), QPointF(32, 58))
        p.drawLine(QPointF(6, 32), QPointF(58, 32))
        p.setBrush(INK)
        for poly in (
            _poly((32, 2), (24, 12), (40, 12)),
            _poly((32, 62), (24, 52), (40, 52)),
            _poly((2, 32), (12, 24), (12, 40)),
            _poly((62, 32), (52, 24), (52, 40)),
        ):
            p.drawPolygon(poly)
    elif name == "select":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(QColor("white"))
        p.drawPolygon(_poly((16, 6), (16, 52), (27, 41), (35, 58), (42, 55), (34, 38), (49, 38)))
    elif name == "measure":
        p.save()
        p.translate(32, 32)
        p.rotate(-35)
        p.setPen(_pen(INK, 2.5))
        p.setBrush(QColor("#f3d27a"))
        p.drawRect(QRectF(-28, -9, 56, 18))
        for i in range(-24, 28, 6):
            p.drawLine(QPointF(i, -9), QPointF(i, -2 if (i // 6) % 2 else 1))
        p.restore()
    elif name == "external":
        pts = [(6, 52), (6, 34), (24, 34), (40, 18), (58, 18), (58, 52)]
        p.setPen(_pen(INK, 3.5))
        p.setBrush(QColor(240, 200, 0, 120))
        p.drawPolygon(_poly(*pts))
        for x, y in pts:
            _vertex(p, x, y)
    elif name == "material_boundary":
        p.setPen(_pen(GREY, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(6, 10, 52, 44))
        pts = [(6, 38), (24, 32), (40, 36), (58, 28)]
        p.setPen(_pen(ORANGE, 4))
        p.drawPolyline(_poly(*pts))
        for x, y in pts:
            _vertex(p, x, y, ORANGE)
    elif name == "water":
        p.setPen(_pen(BLUE, 4))
        p.drawPolyline(_poly((4, 40), (22, 40), (40, 30), (60, 30)))
        p.setBrush(BLUE)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly((40, 14), (52, 14), (46, 24)))
        p.setPen(_pen(BLUE, 2))
        p.drawLine(QPointF(38, 50), QPointF(54, 50))
        p.drawLine(QPointF(42, 56), QPointF(50, 56))
    elif name in ("add_vertex", "delete_vertex"):
        p.setPen(_pen(INK, 3.5))
        p.drawPolyline(_poly((6, 48), (32, 24), (58, 40)))
        _vertex(p, 32, 24, RED if name == "delete_vertex" else GREEN)
        p.setPen(_pen(GREEN if name == "add_vertex" else RED, 5))
        p.drawLine(QPointF(42, 10), QPointF(58, 10))
        if name == "add_vertex":
            p.drawLine(QPointF(50, 2), QPointF(50, 18))
    elif name == "assign":
        p.setPen(_pen(INK, 3))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((6, 56), (6, 34), (58, 26), (58, 56)))
        p.setBrush(GREEN)
        p.drawPolygon(_poly((6, 34), (6, 20), (58, 10), (58, 26)))
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("white"))
        p.drawPolygon(_poly((30, 38), (30, 58), (36, 52), (41, 62), (45, 60), (40, 50), (48, 50)))
    elif name == "coords":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(6, 8, 52, 48))
        p.setPen(_pen(GREY, 2))
        for y in (20, 32, 44):
            p.drawLine(QPointF(6, y), QPointF(58, y))
        p.drawLine(QPointF(32, 8), QPointF(32, 56))
        p.setPen(_pen(BLUE, 2.5))
        p.setFont(QFont("Source Sans 3", 9, QFont.Bold))
        p.drawText(QRectF(6, 8, 26, 12), Qt.AlignCenter, "x")
        p.drawText(QRectF(32, 8, 26, 12), Qt.AlignCenter, "y")
    elif name == "surface_options":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 58), (4, 42), (22, 42), (40, 24), (60, 24), (60, 58)))
        path = QPainterPath(QPointF(18, 42))
        path.quadTo(QPointF(34, 60), QPointF(48, 24))
        p.setPen(_pen(RED, 4))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(_pen(INK, 2))
        p.setBrush(GREY)
        p.drawEllipse(QPointF(14, 14), 9, 9)
    elif name == "slope_limits":
        p.setPen(_pen(INK, 3))
        p.drawPolyline(_poly((4, 44), (22, 44), (40, 26), (60, 26)))
        p.setPen(Qt.NoPen)
        p.setBrush(BLUE)
        p.drawPolygon(_poly((10, 26), (10, 40), (20, 33)))
        p.drawPolygon(_poly((54, 8), (54, 22), (44, 15)))
    elif name == "user_surface":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(QColor(240, 200, 0, 140))
        p.drawPolygon(_poly((4, 58), (4, 40), (22, 40), (40, 22), (60, 22), (60, 58)))
        p.setPen(_pen(RED, 3.5))
        p.setBrush(Qt.NoBrush)
        pts = [(16, 40), (26, 50), (40, 46), (50, 22)]
        p.drawPolyline(_poly(*pts))
        for x, y in pts:
            _vertex(p, x, y, RED)
    elif name == "info":
        p.setPen(_pen(BLUE, 3))
        p.setBrush(QColor("#e8f0ff"))
        p.drawEllipse(QPointF(32, 32), 26, 26)
        p.setPen(_pen(BLUE, 6))
        p.drawLine(QPointF(32, 28), QPointF(32, 46))
        p.setBrush(BLUE)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(32, 18), 4, 4)
    elif name == "export":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(QColor("#cfe3ff"))
        p.drawRect(QRectF(6, 10, 52, 42))
        p.setBrush(GREEN)
        p.drawPolygon(_poly((6, 52), (22, 30), (34, 44), (44, 34), (58, 52)))
        p.setBrush(YELLOW)
        p.drawEllipse(QPointF(46, 20), 5, 5)
    elif name == "slice_query":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((14, 10), (34, 10), (34, 54), (14, 46)))
        p.setPen(_pen(BLUE, 4))
        p.setFont(QFont("Source Sans 3", 20, QFont.Bold))
        p.drawText(QRectF(34, 14, 28, 36), Qt.AlignCenter, "?")
    elif name == "global_min":
        p.setPen(_pen(GREEN, 3))
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(4, 16, 56, 32))
        p.setFont(QFont("Source Sans 3", 15, QFont.Bold))
        p.drawText(QRectF(4, 16, 56, 32), Qt.AlignCenter, "FS")
    elif name == "all_surfaces":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 58), (4, 40), (22, 40), (40, 22), (60, 22), (60, 58)))
        for i, c in enumerate([RED, ORANGE, GREEN, BLUE]):
            path = QPainterPath(QPointF(16 + i * 2, 40))
            path.quadTo(QPointF(34, 58 - i * 4), QPointF(48 + i * 3, 22))
            p.setPen(_pen(c, 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
    elif name == "legend":
        for i, c in enumerate([YELLOW, GREEN, ORANGE]):
            p.setPen(_pen(INK, 2))
            p.setBrush(c)
            p.drawRect(QRectF(6, 8 + i * 17, 14, 12))
            p.setPen(_pen(GREY, 3))
            p.drawLine(QPointF(26, 14 + i * 17), QPointF(56, 14 + i * 17))
    elif name == "grid":
        p.setPen(_pen(GREY, 2))
        for k in range(8, 64, 12):
            p.drawLine(QPointF(k, 4), QPointF(k, 60))
            p.drawLine(QPointF(4, k), QPointF(60, k))
    elif name == "load_distributed":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawRect(QRectF(4, 44, 56, 16))
        p.setPen(_pen(RED, 3))
        p.drawLine(QPointF(8, 10), QPointF(56, 10))
        for x in (10, 22, 34, 46, 56):
            p.drawLine(QPointF(x, 10), QPointF(x, 40))
            p.setBrush(RED)
            p.setPen(Qt.NoPen)
            p.drawPolygon(_poly((x - 4, 34), (x + 4, 34), (x, 42)))
            p.setPen(_pen(RED, 3))
    elif name == "load_line":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawRect(QRectF(4, 44, 56, 16))
        p.setPen(_pen(RED, 5))
        p.drawLine(QPointF(32, 4), QPointF(32, 34))
        p.setBrush(RED)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly((22, 30), (42, 30), (32, 44)))
    elif name in ("support", "support_props"):
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 60), (4, 44), (18, 44), (36, 12), (60, 12), (60, 60)))
        p.setPen(_pen(QColor("#1f3d7a"), 3.5))
        p.drawLine(QPointF(26, 30), QPointF(58, 40))
        p.setPen(_pen(QColor("#1f3d7a"), 7))
        p.drawLine(QPointF(46, 36), QPointF(58, 40))
        p.setPen(_pen(QColor("#1f3d7a"), 4))
        p.drawLine(QPointF(23, 24), QPointF(29, 36))
        if name == "support_props":
            p.setPen(_pen(INK, 2))
            p.setBrush(GREY)
            p.drawEllipse(QPointF(14, 14), 9, 9)
    elif name == "seismic":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawRect(QRectF(4, 44, 56, 16))
        p.setPen(_pen(RED, 3))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(
            _poly((4, 26), (12, 14), (20, 36), (28, 10), (36, 38), (44, 16), (52, 30), (60, 22))
        )
    elif name == "tension_crack":
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 60), (4, 44), (20, 44), (36, 14), (60, 14), (60, 60)))
        p.setPen(_pen(BROWN, 3))
        p.drawPolyline(_poly((46, 14), (42, 20), (48, 26), (43, 32), (47, 38)))
        p.setPen(_pen(BROWN, 2.5, Qt.DashLine))
        p.drawLine(QPointF(38, 38), QPointF(60, 38))
    elif name in ("bolt", "bolt_pattern"):
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 60), (4, 52), (14, 52), (40, 6), (60, 6), (60, 60)))
        heads = [(30, 24)] if name == "bolt" else [(36, 14), (28, 28), (20, 42)]
        for hx, hy in heads:
            tx, ty = hx + 26, hy + 7  # ~15° below horizontal
            p.setPen(_pen(QColor("#1f3d7a"), 3.5 if name == "bolt" else 3))
            p.drawLine(QPointF(hx, hy), QPointF(tx, ty))
            p.setPen(_pen(QColor("#1f3d7a"), 3.5))
            p.drawLine(QPointF(hx - 3, hy - 5), QPointF(hx + 3, hy + 5))
        if name == "bolt":
            p.setPen(_pen(RED, 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(22, 16, 30, 16), -16 * 15, 16 * 15)
            p.drawLine(QPointF(30, 24), QPointF(54, 24))
    elif name in ("facing", "facing_props"):
        p.setPen(_pen(INK, 2.5))
        p.setBrush(YELLOW)
        p.drawPolygon(_poly((4, 60), (4, 48), (18, 48), (40, 12), (60, 12), (60, 60)))
        p.setPen(_pen(QColor("#7f8c8d"), 7))
        p.drawLine(QPointF(18, 48), QPointF(40, 12))
        p.setPen(_pen(INK, 1.5, Qt.DashLine))
        p.drawLine(QPointF(14, 46), QPointF(36, 10))
        if name == "facing_props":
            p.setPen(_pen(INK, 2))
            p.setBrush(GREY)
            p.drawEllipse(QPointF(14, 14), 9, 9)
    elif name == "annot_text":
        p.setPen(_pen(INK, 2.5))
        f = QFont("Sans")
        f.setPixelSize(44)
        f.setBold(True)
        p.setFont(f)
        p.setPen(RED)
        p.drawText(QRectF(0, 4, 64, 56), Qt.AlignCenter, "A")
        p.setPen(_pen(INK, 2.5))
        p.drawLine(QPointF(10, 58), QPointF(54, 58))
    elif name == "annot_line":
        p.setPen(_pen(RED, 4))
        p.drawLine(QPointF(8, 54), QPointF(56, 10))
    elif name == "annot_arrow":
        p.setPen(_pen(RED, 4))
        p.drawLine(QPointF(8, 54), QPointF(50, 14))
        p.setBrush(RED)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly((56, 8), (38, 14), (50, 26)))
    elif name == "annot_rect":
        p.setPen(_pen(RED, 4))
        p.setBrush(QColor(246, 214, 90, 120))
        p.drawRect(QRectF(8, 14, 48, 36))
    elif name == "annot_ellipse":
        p.setPen(_pen(RED, 4))
        p.setBrush(QColor(246, 214, 90, 120))
        p.drawEllipse(QRectF(6, 14, 52, 36))
    elif name == "report":
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("white"))
        p.drawPolygon(_poly((12, 4), (42, 4), (54, 16), (54, 60), (12, 60)))
        p.drawPolyline(_poly((42, 4), (42, 16), (54, 16)))
        p.setPen(_pen(GREY, 2.5))
        for y in (24, 31, 38):
            p.drawLine(QPointF(18, y), QPointF(48, y))
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawRect(QRectF(6, 42, 40, 16))
        f = QFont("Sans")
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(6, 42, 40, 16), Qt.AlignCenter, "PDF")
    elif name == "cad_polygon":
        p.setPen(_pen(BLUE, 3.5))
        p.setBrush(QColor(47, 111, 214, 60))
        corners = ((8, 52), (14, 14), (40, 8), (56, 30), (44, 54))
        p.drawPolygon(_poly(*corners))
        for x, y in corners:
            _vertex(p, x, y)
    elif name == "cad_rect":
        p.setPen(_pen(BLUE, 3.5))
        p.setBrush(QColor(47, 111, 214, 60))
        p.drawRect(QRectF(10, 16, 44, 32))
        _vertex(p, 10, 16)
        _vertex(p, 54, 48)
    elif name == "cad_split":
        p.setPen(_pen(GREY, 3))
        p.setBrush(QColor(165, 117, 60, 70))
        p.drawRect(QRectF(6, 10, 52, 44))
        p.setPen(_pen(ORANGE, 4, Qt.DashLine))
        p.drawPolyline(_poly((6, 30), (24, 30), (24, 54)))
        _vertex(p, 24, 30, ORANGE)
    elif name == "cad_hole":
        p.setPen(_pen(GREY, 3))
        p.setBrush(QColor(165, 117, 60, 70))
        p.drawRect(QRectF(6, 10, 52, 44))
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(32, 32), 13, 13)
    elif name == "cad_polyline":
        p.setPen(_pen(INK, 3.5))
        bends = ((6, 50), (22, 18), (40, 42), (58, 12))
        p.drawPolyline(_poly(*bends))
        for x, y in bends:
            _vertex(p, x, y)
    elif name == "cad_pile":
        p.setPen(_pen(GREY, 3))
        p.drawLine(QPointF(4, 18), QPointF(60, 18))
        p.setPen(_pen(QColor("#8455b6"), 8))
        p.drawLine(QPointF(32, 8), QPointF(32, 58))
    elif name == "cad_tunnel":
        p.setPen(_pen(GREY, 3))
        p.setBrush(QColor(165, 117, 60, 70))
        p.drawRect(QRectF(4, 6, 56, 52))
        p.setPen(_pen(BROWN, 5))
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(32, 34), 17, 17)
        _vertex(p, 32, 34)
    elif name == "cad_natm":
        p.setPen(_pen(GREY, 3))
        p.setBrush(QColor(165, 117, 60, 70))
        p.drawRect(QRectF(4, 4, 56, 56))
        path = QPainterPath(QPointF(14, 50))
        path.lineTo(14, 30)
        path.arcTo(QRectF(14, 12, 36, 36), 180, -180)
        path.lineTo(50, 50)
        path.quadTo(32, 56, 14, 50)
        p.setPen(_pen(BROWN, 4.5))
        p.setBrush(QColor("white"))
        p.drawPath(path)
        p.setPen(_pen(ORANGE, 2, Qt.DashLine))
        p.drawLine(QPointF(14, 34), QPointF(50, 34))
        p.drawLine(QPointF(14, 46), QPointF(50, 46))
    elif name == "cad_liner":
        p.setPen(_pen(BROWN, 6))
        p.drawPolyline(_poly((8, 54), (8, 24), (20, 10), (44, 10), (56, 24), (56, 54)))
    elif name == "delete":
        p.setPen(_pen(RED, 8))
        p.drawLine(QPointF(14, 14), QPointF(50, 50))
        p.drawLine(QPointF(50, 14), QPointF(14, 50))
    elif name in ("mesh", "mesh_view", "results"):
        nodes = (
            (8, 12),
            (32, 12),
            (56, 12),
            (8, 32),
            (32, 32),
            (56, 32),
            (8, 52),
            (32, 52),
            (56, 52),
        )
        tris = (
            (0, 3, 4),
            (0, 4, 1),
            (1, 4, 5),
            (1, 5, 2),
            (3, 6, 7),
            (3, 7, 4),
            (4, 7, 8),
            (4, 8, 5),
        )
        fills = (
            [BLUE, GREEN, YELLOW, ORANGE, QColor("#6f8fd0"), GREEN, ORANGE, BLUE]
            if name == "results"
            else [QColor(47, 111, 214, 70)] * 8
        )
        p.setPen(_pen(INK, 2.2))
        for (a, b, c), fill in zip(tris, fills):
            p.setBrush(fill)
            p.drawPolygon(_poly(nodes[a], nodes[b], nodes[c]))
        if name == "mesh":
            p.setPen(_pen(GREEN, 5))
            p.drawLine(QPointF(44, 8), QPointF(58, 8))
            p.drawLine(QPointF(51, 1), QPointF(51, 15))
    elif name == "stop":
        p.setPen(_pen(QColor("#8a1f18"), 3))
        p.setBrush(RED)
        p.drawRoundedRect(QRectF(14, 14, 36, 36), 6, 6)
    else:
        p.setPen(_pen(RED, 4))
        p.drawRect(QRectF(8, 8, 48, 48))


@cache
def icon(name: str) -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.scale(size / 64.0, size / 64.0)
        _draw(name, p)
        p.end()
        ic.addPixmap(pm)
    return ic


def color_icon(color: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.setPen(QPen(QColor("#333"), 1))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)
