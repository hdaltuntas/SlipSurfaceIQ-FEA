"""Independent horizontal-head water loads on straight exposed edges and joints."""

from __future__ import annotations

import numpy as np

from ..core.enums import ElemType
from ..core.units import GAMMA_W


def nodal_resultant(mesh, value):
    total = value.sum(axis=0)
    total[2] += np.sum(mesh.coords[:, 0] * value[:, 1] - mesh.coords[:, 1] * value[:, 0])
    return total


def horizontal_head(water):
    if water.mode == "none":
        return -np.inf
    if water.mode != "piezo_line":
        raise ValueError("Only horizontal piezometric heads are supported")
    line = np.asarray(water.piezo_polyline, dtype=float)
    if not np.isfinite(line).all() or not np.allclose(line[:, 1], line[0, 1], rtol=0., atol=1e-10):
        raise ValueError("Water head must be horizontal and finite")
    return float(line[0, 1])


def _straight(coords):
    tangent = coords[1] - coords[0]
    length = np.linalg.norm(tangent)
    if not np.isfinite(length) or length <= 0:
        raise ValueError("Degenerate water-loaded edge")
    if len(coords) == 3 and not np.allclose(coords[2], coords[:2].mean(axis=0),
                                           rtol=0., atol=1e-10 * max(1., length)):
        raise ValueError("Curved/noncentral water-loaded edges are unsupported")
    return tangent, length


def _edge_pressure(coords, head):
    """Exactly integrate linear hydrostatic pressure times edge shape polynomials."""
    tangent, length = _straight(coords)
    if max(head - coords[0, 1], head - coords[1, 1]) <= 0:
        return np.zeros(len(coords))
    breaks = [0., 1.]
    if tangent[1] != 0:
        cut = (head - coords[0, 1]) / tangent[1]
        if 0 < cut < 1:
            breaks.insert(1, cut)
    # Three-point Gauss integrates cubic N*p exactly on each wet/dry subinterval.
    points, weights = np.polynomial.legendre.leggauss(3)
    nodal = np.zeros(len(coords))
    for low, high in zip(breaks, breaks[1:]):
        s = low + (high - low) * (points + 1) / 2
        if len(coords) == 2:
            shape = np.column_stack((1 - s, s))
        else:
            shape = np.column_stack(((1 - s) * (1 - 2*s), s * (2*s - 1), 4*s*(1 - s)))
        pressure = GAMMA_W * np.maximum(head - (coords[0, 1] + s*tangent[1]), 0.)
        nodal += (weights * pressure * length * (high - low) / 2) @ shape
    return nodal


def hydrostatic_nodal_forces(mesh, active, head, *, nodal_pressure=None):
    """Return raw boundary and joint nodal loads; no FEM water assembler is used.

    Boundary pressure is exact even across a water-table cut. Joint loads
    follow the independent trapezoidal/Simpson tributary convention.
    """
    boundary = np.zeros((mesh.nn, 3))
    joint = np.zeros_like(boundary)
    if nodal_pressure is not None:
        nodal_pressure = np.asarray(nodal_pressure, dtype=float)
        if nodal_pressure.shape != (mesh.nn,) or not np.isfinite(nodal_pressure).all():
            raise ValueError("Nodal water pressures must be finite and match the mesh")
    excluded = set()
    for block in mesh.blocks:
        if block.etype not in (ElemType.IFACE4, ElemType.IFACE6):
            continue
        npe = block.etype.nen // 2
        for face in (block.conn[:, :npe], block.conn[:, npe:]):
            excluded.update(tuple(sorted(map(int, edge[:2]))) for edge in face)
        fractions = np.array([0.5, 0.5]) if npe == 2 else np.array([1/6, 1/6, 2/3])
        for conn in block.conn[active[block.tag]]:
            face1, face2 = conn[:npe], conn[npe:]
            xy = mesh.coords[face1]
            tangent, length = _straight(xy)
            if not np.allclose(xy, mesh.coords[face2], rtol=0., atol=1e-10):
                raise ValueError("Separated joint faces need a distinct water moment reference")
            normal = np.array([-tangent[1], tangent[0]]) / length
            pressure = (GAMMA_W * np.maximum(head - xy[:, 1], 0.)
                        if nodal_pressure is None else nodal_pressure[face1])
            force = fractions[:, None] * length * pressure[:, None] * normal
            np.add.at(joint[:, :2], face1, -force)
            np.add.at(joint[:, :2], face2, force)
    edges = {}
    for block in mesh.continuum_blocks():
        nc = 3 if block.etype in (ElemType.T3, ElemType.T6) else 4
        quadratic = block.etype in (ElemType.T6, ElemType.Q8)
        for conn in block.conn[active[block.tag]]:
            center = mesh.coords[conn[:nc]].mean(axis=0)
            for i in range(nc):
                edge = [conn[i], conn[(i + 1) % nc]]
                if quadratic:
                    edge.append(conn[nc + i])
                key = tuple(sorted(map(int, edge[:2])))
                edges.setdefault(key, []).append((edge, center))
    for key, owners in edges.items():
        if len(owners) != 1 or key in excluded:
            continue
        edge, center = owners[0]
        xy = mesh.coords[edge]
        tangent, length = _straight(xy)
        normal = np.array([tangent[1], -tangent[0]]) / length
        if normal @ (xy[:2].mean(axis=0) - center) < 0:
            normal *= -1
        if nodal_pressure is None:
            pressure_integrals = _edge_pressure(xy, head)
        else:
            # Exact integral of N_i*N_j for a straight linear/quadratic edge.
            mass = (np.array([[2., 1.], [1., 2.]]) / 6 if len(edge) == 2 else
                    np.array([[4., -1., 2.], [-1., 4., 2.], [2., 2., 16.]]) / 30)
            pressure_integrals = length * (mass @ nodal_pressure[edge])
        np.add.at(boundary[:, :2], edge, -pressure_integrals[:, None] * normal)
    return {"boundary": boundary, "joint": joint}
