"""F7 independently assembled *dry* boundary-load global force budget.

The audit integrates piecewise straight, externally exposed edge pressures in
global axes, and sums point loads without using the solver's nodal load vector.
It accounts for partial load stages by interpolating between previously applied
external loads and the current stage's *target* loads. The physical geometry
and active continuum/structures must remain unchanged across these stages.

In-situ gravity is included via the restricted independent weight budget.
Water, pseudostatic inertia, prescribed displacements, pretension, variable
material properties, and mesh/structure activation are deliberately rejected.
"""

from __future__ import annotations

import numpy as np

from slipsurface.fe2d.core.enums import Analysis, ElemType
from slipsurface.fe2d.model.boundary import EdgeLoad, PointLoad
from slipsurface.fe2d.post.balance_acceptance import classify_balance


def _boundary_edge_map(mesh, active_masks=None):
    """Undirected corner-edge -> adjacent element-centre coordinates."""
    adjacency = {}
    for block in mesh.continuum_blocks():
        corner_count = 3 if block.etype in (ElemType.T3, ElemType.T6) else 4
        corners = block.conn[:, :corner_count]
        if active_masks is not None:
            mask = np.asarray(active_masks[block.tag], dtype=bool)
            if mask.shape != (block.ne,):
                raise ValueError(f"{block.tag}: active mask shape mismatch")
            corners = corners[mask]
        centers = mesh.coords[corners].mean(axis=1)
        for j in range(corner_count):
            for edge_nodes, center in zip(
                corners[:, [j, (j + 1) % corner_count]], centers
            ):
                key = tuple(sorted(int(k) for k in edge_nodes))
                adjacency.setdefault(key, []).append(center)
    return adjacency


def independent_stage_loads(model, stage, *, active_masks=None):
    """Return external force (Fx,Fy) from straight edge and point loads.

    Orientation is fixed using a unique continuum-owner centroid and does
    not depend on the orientation of edge-set connectivity. Curved quadratic
    edges and internal surfaces are explicitly outside this reference.
    """
    mesh = model.mesh
    neighbors = _boundary_edge_map(mesh, active_masks)
    total = np.zeros(2)
    for load in stage.loads:
        if isinstance(load, PointLoad):
            if not 0 <= load.node < mesh.nn:
                raise ValueError("Point load node is outside the mesh")
            total += [load.fx, load.fy]
        elif isinstance(load, EdgeLoad):
            for edge in mesh.edges(load.edge_set):
                ends = mesh.coords[edge[:2]]
                tangent = ends[1] - ends[0]
                length = np.linalg.norm(tangent)
                if not np.isfinite(length) or length <= 0:
                    raise ValueError("Degenerate loaded edge")
                if edge.size == 3:
                    midpoint = mesh.coords[int(edge[2])]
                    if np.linalg.norm(
                        midpoint - ends.mean(axis=0)
                    ) > 1e-8 * max(1., length):
                        raise ValueError("Curved edge requires numerical load integration")
                key = tuple(sorted(int(k) for k in edge[:2]))
                adjacent = neighbors.get(key, [])
                if len(adjacent) != 1:
                    raise ValueError("Edge load must lie on a unique external boundary")
                midpoint = ends.mean(axis=0)
                normal = np.array([tangent[1], -tangent[0]]) / length
                if np.dot(normal, midpoint - adjacent[0]) < 0:
                    normal = -normal
                shear = np.array([-normal[1], normal[0]])
                total += (-load.qn * normal + load.qt * shear) * length
        else:
            raise ValueError(f"Unsupported stage load: {type(load).__name__}")
    return total


def dry_stage_load_balance(model, result, stage_index):
    """Independent boundary traction + weight versus global support reactions.

    Load factors are interpreted as interpolation from the *last actually
    applied* external load to the stage's target loads. All computed
    intermediate stages must be present in result.
    """
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane-strain dry balance is supported")
    if not 0 <= stage_index < len(result.stages):
        raise IndexError("Stage index is outside computed results")
    if model.initial.mode not in ("gravity", "k0_field"):
        raise ValueError("Requires gravity/K0 initialized models")
    if model.initial.water.mode != "none":
        raise ValueError("Groundwater requires an independent pore-force budget")
    if model.displacements:
        raise ValueError("Imposed displacement requires a separate budget")
    if getattr(model, "extra_tractions", None):
        raise ValueError("Extra tractions require a separate budget")

    initial_masks = result.initial.active
    last = np.zeros(2)
    for index in range(stage_index + 1):
        definition = model.stages[index]
        computed = result.stages[index]
        if definition.water.mode != "none":
            raise ValueError("Stage water needs a separate force budget")
        if definition.seismic_kh or definition.seismic_kv:
            raise ValueError("Seismic inertia needs a separate force budget")
        if definition.displacements or definition.material_override:
            raise ValueError("Stage displacement/material override is unsupported")
        if definition.active_regions is not None:
            raise ValueError("Staged excavation is outside the loaded-domain contract")
        if definition.active_structures:
            raise ValueError("Structure activation is outside the loaded-domain contract")
        if model.bolts and any(spec.pretension for spec in model.bolts.values()):
            raise ValueError("Bolt pretension needs a separate force budget")
        if model.liners and any(spec.shotcrete_EA for spec in model.liners.values()):
            raise ValueError("Changing shotcrete maturity needs a separate budget")
        for tag, mask in initial_masks.items():
            if tag not in computed.active or not np.array_equal(
                mask, computed.active[tag]
            ):
                raise ValueError("Active finite-element set changed between stages")
        desired = independent_stage_loads(model, definition)
        last = last + float(computed.lam) * (desired - last)

    # Existing gravity budget is restricted to stages with no external loads.
    # Compute its independent weight terms here using active quadrature
    # areas and (where applicable) beam lengths, not solver reactions.
    stage = result.stages[stage_index]
    soil_weight = 0.0
    for block in model.mesh.continuum_blocks():
        mask = np.asarray(stage.active[block.tag], dtype=bool)
        area = np.sum(result.geom[block.tag].wdet, axis=1)
        gamma = np.array([
            model.materials[model.region_material[int(region)]].gamma_unsat
            for region in block.region
        ])
        soil_weight += float(np.dot(area[mask], gamma[mask]))
    beam_weight = 0.0
    for block in model.mesh.blocks:
        if block.etype is ElemType.BEAM2:
            mask = stage.active[block.tag]
            spec = model.liners[block.tag]
            coords = model.mesh.coords[block.conn]
            length = np.linalg.norm(coords[:, 1] - coords[:, 0], axis=1)
            beam_weight += float(np.sum(length[mask]) * spec.A * spec.unit_weight)
    expected = -last + np.array([0., soil_weight + beam_weight])
    actual = np.asarray(stage.reactions)[:, :2].sum(axis=0)
    residual = actual - expected
    scale = max(np.linalg.norm(expected), np.linalg.norm(last), soil_weight, 1.)
    return {
        "stage": stage.name,
        "applied_external_fx_kn_per_m": float(last[0]),
        "applied_external_fy_kn_per_m": float(last[1]),
        "soil_weight_kn_per_m": soil_weight,
        "beam_weight_kn_per_m": beam_weight,
        "expected_rx_kn_per_m": float(expected[0]),
        "expected_ry_kn_per_m": float(expected[1]),
        "reaction_rx_kn_per_m": float(actual[0]),
        "reaction_ry_kn_per_m": float(actual[1]),
        "imbalance_fx_kn_per_m": float(residual[0]),
        "imbalance_fy_kn_per_m": float(residual[1]),
        "relative_imbalance": float(np.linalg.norm(residual) / scale),
    }


def dry_stage_load_balance_by_stage(model, result):
    """Audit all computed stages with explicit unsupported reasons."""
    rows = []
    for i, stage in enumerate(result.stages):
        try:
            entry = classify_balance(
                dry_stage_load_balance(model, result, i), "relative_imbalance"
            )
        except (KeyError, ValueError, IndexError) as exc:
            entry = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        rows.append(entry)
    return rows
