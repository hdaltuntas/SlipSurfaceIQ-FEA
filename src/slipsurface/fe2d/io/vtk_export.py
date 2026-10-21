"""Dependency-free VTU (VTK XML UnstructuredGrid) writer for ParaView / PyVista (L5).

Data arrays are written inline as base64-encoded binary (VTK ``format="binary"``).
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..model.mesh import Mesh

_VTK_CELL = {
    ElemType.T3: 5,  # VTK_TRIANGLE
    ElemType.T6: 22,  # VTK_QUADRATIC_TRIANGLE (same node order as ours)
    ElemType.Q4: 9,
    ElemType.Q8: 23,
    ElemType.BEAM2: 3,
    ElemType.BAR2: 3,
}
_VTK_TYPE = {
    np.float64: "Float64",
    np.float32: "Float32",
    np.int64: "Int64",
    np.int32: "Int32",
    np.uint8: "UInt8",
}


def _b64(arr: NDArray) -> str:
    raw = np.ascontiguousarray(arr).tobytes()
    header = np.array([len(raw)], dtype=np.uint64).tobytes()
    return base64.b64encode(header + raw).decode()  # one stream: header + data


def _array(name: str, arr: NDArray, ncomp: int | None = None) -> str:
    arr = np.asarray(arr)
    vt = _VTK_TYPE[arr.dtype.type]
    nc = ncomp if ncomp is not None else (1 if arr.ndim == 1 else arr.shape[1])
    return (
        f'<DataArray type="{vt}" Name="{name}" NumberOfComponents="{nc}" '
        f'format="binary">{_b64(arr)}</DataArray>'
    )


def write_vtu(
    path: str | Path,
    mesh: Mesh,
    point_data: dict[str, NDArray] | None = None,
    cell_data: dict[str, NDArray] | None = None,
) -> Path:
    """Write continuum, beam and bar cells (interfaces omitted).

    Cell data must cover every exported cell, ordered block by block.
    """
    path = Path(path)
    blocks = [b for b in mesh.blocks if b.etype in _VTK_CELL]
    conn = np.concatenate([b.conn.ravel() for b in blocks]).astype(np.int64)
    offsets = np.cumsum(np.concatenate([np.full(b.ne, b.etype.nen) for b in blocks])).astype(
        np.int64
    )
    types = np.concatenate([np.full(b.ne, _VTK_CELL[b.etype]) for b in blocks]).astype(np.uint8)
    region = np.concatenate([b.region for b in blocks]).astype(np.int32)
    pts = np.column_stack([mesh.coords, np.zeros(mesh.nn)])
    ncell = types.size

    pd = []
    for k, v in (point_data or {}).items():
        v = np.asarray(v, dtype=np.float64)
        if v.ndim not in (1, 2) or v.shape[0] != mesh.nn:
            raise ValueError(f"point data '{k}' must have {mesh.nn} rows")
        if v.ndim == 2 and v.shape[1] == 2:  # 2D vectors -> 3D for ParaView glyphs
            v = np.column_stack([v, np.zeros(v.shape[0])])
        pd.append(_array(k, np.nan_to_num(v)))
    cd = [_array("region", region)]
    for k, v in (cell_data or {}).items():
        v = np.asarray(v)
        if v.ndim not in (1, 2) or v.shape[0] != ncell:
            raise ValueError(f"cell data '{k}' must have {ncell} rows")
        cd.append(_array(k, v))

    xml = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" '
        'header_type="UInt64">\n<UnstructuredGrid>\n'
        f'<Piece NumberOfPoints="{mesh.nn}" NumberOfCells="{ncell}">\n'
        f"<Points>{_array('Points', pts)}</Points>\n"
        "<Cells>"
        f"{_array('connectivity', conn, 1)}{_array('offsets', offsets, 1)}"
        f"{_array('types', types, 1)}</Cells>\n"
        f"<PointData>{''.join(pd)}</PointData>\n"
        f"<CellData>{''.join(cd)}</CellData>\n"
        "</Piece>\n</UnstructuredGrid>\n</VTKFile>\n"
    )
    path.write_text(xml, encoding="ascii")
    return path

