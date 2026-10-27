"""Strict, loss-aware exchange of planar straight LINE/(LW)POLYLINE geometry."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import ezdxf
import numpy as np

from .geometry import Drawing, Entity

APPID = "SLIPSURFACE"


def read_dxf(path: str | Path, *, metres_per_unit: float) -> Drawing:
    """Import modelspace only. Scale is explicit even if $INSUNITS is present.

    Curves, bulges, blocks, text and non-planar coordinates are rejected as a whole,
    not silently dropped or projected. Closed polylines on HOLE* layers are voids.
    Native exports retain entity name/type/region through XDATA.
    """
    if not np.isfinite(metres_per_unit) or metres_per_unit <= 0:
        raise ValueError("DXF ölçeği pozitif ve sonlu olmalıdır (metre / DXF birimi).")
    doc = ezdxf.readfile(path)
    entities = []
    modelspace: Any = doc.modelspace()
    for i, item in enumerate(modelspace, 1):
        kind = item.dxftype()
        if kind == "LINE":
            points = [item.dxf.start, item.dxf.end]
            closed = False
        elif kind == "LWPOLYLINE":
            if item.has_arc:
                raise ValueError(f"DXF #{i}: yay/bulge desteklenmiyor; düz parçalara dönüştürün.")
            points, closed = list(item.vertices_in_wcs()), item.closed
        elif kind == "POLYLINE" and item.is_2d_polyline:
            if any(v.dxf.get("bulge", 0) for v in item.vertices):
                raise ValueError(f"DXF #{i}: yay/bulge desteklenmiyor.")
            points, closed = list(item.points_in_wcs()), item.is_closed
        else:
            raise ValueError(
                f"DXF #{i}: {kind} desteklenmiyor. Yalnız düz LINE ve "
                "2D POLYLINE/LWPOLYLINE içeren dosya kullanın."
            )
        xyz = np.asarray([tuple(p) for p in points], dtype=float)
        if xyz.ndim != 2 or xyz.shape[0] < 2 or not np.isfinite(xyz).all():
            raise ValueError(f"DXF #{i}: geçersiz koordinatlar.")
        if not np.allclose(xyz[:, 2], 0, rtol=0, atol=1e-9 / metres_per_unit):
            raise ValueError(f"DXF #{i}: XY düzlemi dışında koordinat var (Z ≠ 0).")
        name = f"DXF_{i}"
        role = "hole" if item.dxf.layer.upper().startswith("HOLE") else "region"
        role = role if closed else "line"
        region = i
        if item.has_xdata(APPID):
            tags = item.get_xdata(APPID)
            if len(tags) == 3 and [t.code for t in tags] == [1000, 1000, 1071]:
                role, name, region = (t.value for t in tags)
                if (role == "line") == bool(closed):
                    raise ValueError(f"DXF #{i}: kapanış ve kayıt türü uyuşmuyor.")
        entities.append(Entity(name, role, tuple(map(tuple, xyz[:, :2] * metres_per_unit)), region))
    if not entities:
        raise ValueError("DXF modelspace içinde çizim bulunamadı.")
    names = [e.name for e in entities]
    if len(set(names)) != len(names):
        raise ValueError("DXF içinde yinelenen geometri adları var.")
    return Drawing(tuple(entities))


def write_dxf(drawing: Drawing, path: str | Path):
    """Export geometry in metres; FE conditions remain in .sscad.json/.ssproj."""
    doc = ezdxf.new("R2010")
    doc.units = 6  # metres
    doc.appids.add(APPID)
    for e in drawing.entities:
        layer = f"{'HOLE' if e.kind == 'hole' else e.kind.upper()}_{e.region}"
        layer = re.sub(r"[^A-Za-z0-9_]", "_", layer)
        if layer not in doc.layers:
            doc.layers.add(layer)
        item = doc.modelspace().add_lwpolyline(
            e.points, close=e.kind != "line", dxfattribs={"layer": layer}
        )
        item.set_xdata(APPID, [(1000, e.kind), (1000, e.name), (1071, int(e.region))])
    doc.saveas(path)
