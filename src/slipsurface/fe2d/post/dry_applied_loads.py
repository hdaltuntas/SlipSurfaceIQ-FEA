"""Closed-form dry straight-edge/point loads, independent of FEM load assembly."""

from __future__ import annotations

import numpy as np

from ..model.boundary import EdgeLoad, PointLoad
from .dry_load_balance import _boundary_edge_map


def independent_dry_applied_loads(model, step, active):
    """Return actual-node forces and analytical (Fx, Fy, Mz) about the origin.

    Uniform straight-edge tractions use exact endpoint/midpoint weights:
    linear (1/2, 1/2), quadratic (1/6, 1/6, 2/3). Only uniquely exposed
    active continuum faces are supported. Fully/partially excavated edge
    sets follow the solver's used-node filtering, with skipped edges counted.
    """
    mesh = model.mesh
    used = np.zeros(mesh.nn, dtype=bool)
    for block in mesh.blocks:
        used[block.conn[active[block.tag]].ravel()] = True
    neighbors = _boundary_edge_map(mesh, active)
    nodal = np.zeros((mesh.nn, 3))
    resultant = np.zeros(3)
    skipped = 0
    for load in step.loads:
        if isinstance(load, PointLoad):
            node = load.node
            if (not isinstance(node, (int, np.integer)) or isinstance(node, bool)
                    or not 0 <= node < mesh.nn or not used[node]):
                raise ValueError("Point load requires an active mesh node")
            force = np.asarray([load.fx, load.fy], dtype=float)
            if not np.isfinite(force).all():
                raise ValueError("Nonfinite point load")
            nodal[node, :2] += force
            x, y = mesh.coords[node]
            resultant += [force[0], force[1], x * force[1] - y * force[0]]
        elif isinstance(load, EdgeLoad):
            if not np.isfinite([load.qn, load.qt]).all():
                raise ValueError("Nonfinite edge traction")
            edges = mesh.edges(load.edge_set)
            live = used[edges].all(axis=1)
            skipped += int((~live).sum())
            if not live.any():
                raise ValueError("Loaded edge set has no active edges")
            for edge in edges[live]:
                if len(edge) not in (2, 3):
                    raise ValueError("Only linear/quadratic edges are supported")
                xy = mesh.coords[edge]
                midpoint = xy[:2].mean(axis=0)
                tangent = xy[1] - xy[0]
                length = np.linalg.norm(tangent)
                if not np.isfinite(length) or length <= 0:
                    raise ValueError("Degenerate loaded edge")
                if len(edge) == 3 and np.linalg.norm(xy[2] - midpoint) > 1e-8 * max(1., length):
                    raise ValueError("Curved/noncentral edge requires a different load reference")
                adjacent = neighbors.get(tuple(sorted(map(int, edge[:2]))), [])
                if len(adjacent) != 1:
                    raise ValueError("Loaded edge must have one active continuum owner")
                normal = np.array([tangent[1], -tangent[0]]) / length
                if normal @ (midpoint - adjacent[0]) < 0:
                    normal *= -1
                shear = np.array([-normal[1], normal[0]])
                force = (-load.qn * normal + load.qt * shear) * length
                fractions = np.array([0.5, 0.5]) if len(edge) == 2 else np.array([1/6, 1/6, 2/3])
                np.add.at(nodal[:, :2], edge, fractions[:, None] * force)
                resultant += [force[0], force[1],
                              midpoint[0] * force[1] - midpoint[1] * force[0]]
        else:
            raise ValueError("Unknown applied load type")
    return {"nodal": nodal, "resultant": resultant, "skipped_inactive_edges": skipped}
