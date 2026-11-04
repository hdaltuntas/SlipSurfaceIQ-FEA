"""Diagnostic beam/interface nodal budget for a dry pile-only installation.

Continuum internal and body forces close shared tip nodes. This remains a
restricted nodal reconstruction, not a full coupled external-force benchmark.
"""

from __future__ import annotations

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType
from ..fem.elements import kernel
from ..fem.structural import BeamGroup
from .interface_nodal_audit import interface_nodal_force_transfer


def pile_installation_budget(model, stage, tag):
    """Reconstruct beam end internal forces, interface forces and own weight.

    Residual = beam + interface + soil internal - beam/soil body - reaction.
    Geometry/quadrature are rebuilt from the mesh; effective Gauss-point
    stresses are integrated directly without stress recovery/extrapolation.
    """
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Plane strain is required")
    steps = [step for step in model.stages if step.name == stage.name]
    if len(steps) != 1:
        raise ValueError("Expected exactly one matching stage definition")
    step = steps[0]
    preceding = model.stages[:model.stages.index(step) + 1]
    if (model.initial.water.mode != "none" or model.displacements
            or any(s.water.mode != "none" or s.loads or s.displacements
                   or s.seismic_kh or s.seismic_kv for s in preceding)):
        raise ValueError("Water, external loads or imposed displacements need separate terms")
    if model.initial.mode not in ("gravity", "k0_field") or stage.lam != 1.0:
        raise ValueError("Full gravity/K0 installation stages are required")
    if (any(s.material_override or (s.active_regions is not None
                                   and s.active_regions != model.mesh.regions())
            for s in preceding)
            or model.initial.active_regions not in (None, model.mesh.regions())):
        raise ValueError("Excavation and material changes need separate budgets")
    if any(spec.drainage is not Drainage.DRAINED for spec in model.materials.values()):
        raise ValueError("Undrained materials need separate pore-force terms")
    if model.liners[tag].shotcrete_EA:
        raise ValueError("Shotcrete maturity needs a stage-specific body force")
    if any(np.any(stage.active.get(name, False)) for name in model.bolts):
        raise ValueError("Active bars require a separate nodal contribution")
    if any(name != tag and np.any(stage.active.get(name, False)) for name in model.liners):
        raise ValueError("Other active beams require separate nodal contributions")
    mesh = model.mesh
    block = mesh.block(tag)
    if block.etype is not ElemType.BEAM2:
        raise ValueError("Expected a beam block")
    active = np.asarray(stage.active[tag], dtype=bool)
    if active.shape != (block.ne,) or not active.all():
        raise ValueError("All pile elements must be active")
    forces = np.asarray(stage.beams[tag], dtype=float)
    if forces.shape != (block.ne, 2, 3) or not np.isfinite(forces).all():
        raise ValueError("Invalid active beam end forces")
    group = BeamGroup(block, mesh.coords, model.liners[tag], model.analysis)
    # end_forces reports -local internal at end 1 and +local at end 2.
    local = forces.copy()
    local[:, 0] *= -1
    global_force = np.einsum("eji,ej->ei", group.T, local.reshape(-1, 6))
    beam = np.zeros((mesh.nn, 3))
    body = np.zeros_like(beam)
    np.add.at(beam, block.conn.ravel(), global_force.reshape(-1, 3))
    np.add.at(body, block.conn.ravel(), group.body_force(
        np.arange(block.ne)
    ).reshape(-1, 3))
    interface = np.zeros_like(beam)
    if set(stage.interfaces) != set(model.interfaces):
        raise ValueError("Missing or unexpected interface result blocks")
    for name, tractions in stage.interfaces.items():
        mask = np.asarray(stage.active[name], dtype=bool)
        if mask.shape != (mesh.block(name).ne,) or not mask.all():
            raise ValueError("Inactive interface ties need a separate nodal mapping")
        if not np.isfinite(np.asarray(tractions)).all():
            raise ValueError("Invalid active interface tractions")
        out = interface_nodal_force_transfer(
            mesh, name, tractions, model.interfaces[name], analysis=model.analysis,
        )
        interface[:, :2] += out["nodal_forces"]
    shared = set()
    soil_internal = np.zeros_like(beam)
    soil_body = np.zeros_like(beam)
    for soil in mesh.continuum_blocks():
        mask = np.asarray(stage.active[soil.tag], dtype=bool)
        if mask.shape != (soil.ne,) or not mask.all():
            raise ValueError("All soil elements must be active for installation")
        geom = kernel(soil.etype).precompute(
            mesh.coords, soil.conn, model.analysis, model.settings.gauss_order,
        )
        stress = np.asarray(stage.sig[soil.tag], dtype=float)
        if stress.shape != (*geom.wdet.shape, 4) or not np.isfinite(stress).all():
            raise ValueError("Invalid active continuum stresses")
        for field in (stage.pore, stage.excess_pore):
            if soil.tag in field:
                pressure = np.asarray(field[soil.tag])
                if (pressure.shape != geom.wdet.shape or not np.isfinite(pressure).all()
                        or np.any(pressure != 0)):
                    raise ValueError("Nonzero pore pressures require separate force terms")
        elemental = np.einsum(
            "egki,egk,eg->ei", geom.B, stress, geom.wdet, optimize=True,
        )
        np.add.at(soil_internal[:, :2], soil.conn.ravel(), elemental.reshape(-1, 2))
        gamma = np.array([
            model.materials[model.region_material[int(region)]].gamma_unsat
            for region in soil.region
        ])
        weight = -gamma[:, None] * (geom.wdet @ geom.N)
        np.add.at(soil_body[:, 1], soil.conn.ravel(), weight.ravel())
        shared.update(soil.conn[mask].ravel().tolist())
    nodes = np.unique(block.conn)
    residual = beam + interface - body
    reactions = np.asarray(stage.reactions, dtype=float)
    if reactions.shape != beam.shape or not np.isfinite(reactions).all():
        raise ValueError("Invalid nodal reactions")
    complete = residual + soil_internal - soil_body - reactions
    isolated = [node for node in nodes if int(node) not in shared]
    return {
        "status": "diagnostic_only",
        "convention": "beam internal + interface internal - beam weight",
        "complete_convention": (
            "beam + interface + soil internal - beam body - soil body - reaction"
        ),
        "max_complete_force_residual": float(np.max(np.abs(complete[nodes, :2]))),
        "max_complete_moment_residual": float(np.max(np.abs(complete[nodes, 2]))),
        "max_isolated_force_residual": float(np.max(np.abs(residual[isolated, :2])))
        if isolated else None,
        "max_isolated_moment_residual": float(np.max(np.abs(residual[isolated, 2])))
        if isolated else None,
        "max_isolated_horizontal_interface_force": float(
            np.max(np.abs(interface[isolated, 0]))
        ) if isolated else None,
        "nodes": [
            {
                "node": int(node), "xy_m": mesh.coords[node].tolist(),
                "shared_continuum": int(node) in shared,
                "beam_internal": beam[node].tolist(),
                "interface_internal": interface[node].tolist(),
                "beam_body": body[node].tolist(),
                "residual_without_continuum": residual[node].tolist(),
                "soil_internal": soil_internal[node].tolist(),
                "soil_body": soil_body[node].tolist(),
                "reaction": reactions[node].tolist(),
                "complete_residual": complete[node].tolist(),
            }
            for node in nodes
        ],
        "warning": (
            "Dry full-load installation nodal reconstruction only; no full coupled "
            "excavation or independent physical equilibrium acceptance implied."
        ),
    }
