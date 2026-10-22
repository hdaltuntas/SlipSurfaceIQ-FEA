"""Coordinate entry parsing, AutoCAD style (from the SlipSurfaceIQ-LE CAD tools).

    x,y        absolute            (also "x y")
    @dx,dy     relative to the last point
    @L<a       polar: length L at angle a degrees from the last point
"""

from __future__ import annotations

import math
import re

_NUM = r"[-+]?\d*[.,]?\d+(?:[eE][-+]?\d+)?"


def parse_coordinate(text: str, last):
    """Parse 'x,y', 'x y', '@dx,dy', '@L<a'. Returns (x, y) or None."""
    t = text.strip().replace(";", ",")
    m = re.fullmatch(rf"@\s*({_NUM})\s*<\s*({_NUM})", t)
    if m and last is not None:
        L = float(m.group(1).replace(",", "."))
        a = math.radians(float(m.group(2).replace(",", ".")))
        return last[0] + L * math.cos(a), last[1] + L * math.sin(a)
    rel = t.startswith("@")
    if rel:
        t = t[1:].strip()
    m = re.fullmatch(rf"({_NUM})\s*(?:,|\s)\s*({_NUM})", t)
    if not m:
        return None
    x, y = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    if rel:
        if last is None:
            return None
        return last[0] + x, last[1] + y
    return x, y
