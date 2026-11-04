"""Bounded dry, full-load excavation budget including beams, bars and joints.

Reconstructs nodal internal forces from actual stage outputs and independently
integrates weights and straight-edge/point load first moments against reactions.
No water, imposed displacements, partial release or property changes are covered.
"""

from __future__ import annotations

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType
from ..core.units import GAMMA_W
from ..fem.activity import active_masks, interface_adjacency, tie_pairs
from ..fem.assembly import DofMap
from ..fem.elements import kernel
from ..fem.structural import BarGroup, BeamGroup, InterfaceGroup
from .balance_acceptance import classify_balance
from .dry_applied_loads import independent_dry_applied_loads
from .hydrostatic_nodal_forces import horizontal_head, hydrostatic_nodal_forces, nodal_resultant
from .interface_nodal_audit import interface_nodal_force_transfer
from .seepage_pressure_evidence import seepage_pressure_evidence


def _mask(stage, block):
    mask = np.asarray(stage.active[block.tag])
    if mask.dtype != bool or mask.shape != (block.ne,):
        raise ValueError(f"{block.tag}: invalid active mask")
    return mask


def _values(source, tag, shape, mask):
    values = np.asarray(source[tag], dtype=float)
    if values.shape != shape or not np.isfinite(values[mask]).all():
        raise ValueError(f"{tag}: invalid active result data")
    return values[mask]


def _coupled_dry_components(
    model, result, index, *, require_full=True, hydrostatic=False, seepage=False,
):
    """Reconstruct target-stage terms; partial-stage interpretation is separate."""
    if model.analysis is not Analysis.PLANE_STRAIN:
        raise ValueError("Only plane strain is supported")
    if not 0 <= index < len(result.stages) or index >= len(model.stages):
        raise IndexError("Stage outside computed results")
    if model.initial.mode not in ("gravity", "k0_field"):
        raise ValueError("Gravity/K0 initialization required")
    if hydrostatic and seepage:
        raise ValueError("Select one water reference")
    with_water = hydrostatic or seepage
    if (not with_water and model.initial.water.mode != "none") or model.displacements:
        raise ValueError("Water/displacement terms are outside this budget")
    if hydrostatic:
        horizontal_head(model.initial.water)
    for i, step in enumerate(model.stages[:index + 1]):
        if step.name != result.stages[i].name:
            raise ValueError("Stage order disagrees with model")
        if (not np.isfinite(result.stages[i].lam)
                or result.stages[i].lam != step.load_split):
            raise ValueError("Reported load factor disagrees with stage definition")
        if require_full and step.load_split != 1.0:
            raise ValueError("Partial stages need an incremental release budget")
        if hydrostatic:
            horizontal_head(step.water)
        if ((not with_water and step.water.mode != "none") or step.displacements
                or step.seismic_kh or step.seismic_kv or step.material_override):
            raise ValueError("Water, seismic or changed properties unsupported")
    if any(spec.drainage is not Drainage.DRAINED for spec in model.materials.values()):
        raise ValueError("Undrained soil requires additional pore terms")
    if any(spec.shotcrete_EA for spec in model.liners.values()):
        raise ValueError("Variable shotcrete sections require stage-specific weights")
    stage, mesh = result.stages[index], model.mesh
    groups = []
    for block in mesh.blocks:
        if block.etype is ElemType.BEAM2:
            groups.append(BeamGroup(block, mesh.coords, model.liners[block.tag], model.analysis))
        elif block.etype is ElemType.BAR2:
            groups.append(BarGroup(block, mesh.coords, model.bolts[block.tag], model.analysis))
        elif block.etype in (ElemType.IFACE4, ElemType.IFACE6):
            groups.append(InterfaceGroup(
                block, mesh.coords, model.interfaces[block.tag], model.analysis,
            ))
    continuum = mesh.continuum_blocks()
    definition = model.stages[index]
    expected_masks = active_masks(
        continuum, groups, interface_adjacency(continuum, groups),
        definition.active_regions, definition.active_structures, mesh.nn,
    )
    for block in mesh.blocks:
        if not np.array_equal(_mask(stage, block), expected_masks[block.tag]):
            raise ValueError(f"{block.tag}: activation disagrees with stage definition")
    names = {
        "soil": {b.tag for b in mesh.continuum_blocks()},
        "beam": {b.tag for b in mesh.blocks if b.etype is ElemType.BEAM2},
        "bar": {b.tag for b in mesh.blocks if b.etype is ElemType.BAR2},
        "interface": set(model.interfaces),
    }
    for source, expected in ((stage.sig, names["soil"]), (stage.beams, names["beam"]),
                             (stage.bars, names["bar"]),
                             (stage.interfaces, names["interface"])):
        if set(source) != expected:
            raise ValueError("Missing or unexpected stage result blocks")
    terms = {key: np.zeros((mesh.nn, 3)) for key in
             ("soil", "beam", "bar", "interface", "soil_body", "beam_body")}
    external = np.zeros(3)  # Fx, Fy, Mz about global origin
    head = horizontal_head(definition.water) if hydrostatic else -np.inf
    seepage_evidence = (seepage_pressure_evidence(model, stage, definition.water)
                        if seepage else None)
    pressure_error = 0.
    pressure_ratio = 0.
    if with_water:
        if set(stage.pore) != names["soil"]:
            raise ValueError("Missing or unexpected continuum pore-pressure blocks")
        terms["continuum_water"] = np.zeros((mesh.nn, 3))
    interfaces = []
    for block in mesh.continuum_blocks():
        mask = _mask(stage, block)
        geom = kernel(block.etype).precompute(
            mesh.coords, block.conn, model.analysis, model.settings.gauss_order,
        )
        stress = _values(stage.sig, block.tag, (*geom.wdet.shape, 4), mask)
        for source in (stage.pore, stage.excess_pore):
            if block.tag in source:
                pressure = _values(source, block.tag, geom.wdet.shape, mask)
                if source is stage.pore and with_water:
                    if seepage:
                        gp_head = np.einsum("gn,en->eg", geom.N,
                                            seepage_evidence["head"][block.conn[mask]])
                        expected_p = GAMMA_W * np.maximum(gp_head - geom.xg[mask, :, 1], 0.)
                    else:
                        expected_p = GAMMA_W * np.maximum(head - geom.xg[mask, :, 1], 0.)
                    error = float(np.max(np.abs(pressure - expected_p), initial=0.))
                    pressure_error = max(pressure_error, error)
                    pressure_ratio = max(pressure_ratio, error / max(
                        1., float(np.max(expected_p, initial=0.)),
                    ))
                elif np.any(pressure != 0):
                    raise ValueError("Nonzero pore force is outside the dry budget")
        weights = geom.wdet[mask]
        force = np.einsum("egki,egk,eg->ei", geom.B[mask], stress, weights)
        conn = block.conn[mask]
        np.add.at(terms["soil"][:, :2], conn.ravel(), force.reshape(-1, 2))
        gamma = np.array([model.materials[model.region_material[int(r)]].gamma_unsat
                          for r in block.region[mask]])
        if with_water:
            saturated = np.array([model.materials[model.region_material[int(r)]].gamma_sat
                                  for r in block.region[mask]])
            below = (expected_p > GAMMA_W * 1e-9 if seepage
                     else head - geom.xg[mask, :, 1] > 1e-9)
            gamma_gp = np.where(below,
                                saturated[:, None], gamma[:, None])
            pore_stress = expected_p[..., None] * np.array([1., 1., 1., 0.])
            pore_force = np.einsum("egki,egk,eg->ei", geom.B[mask], pore_stress, weights)
            np.add.at(terms["continuum_water"][:, :2], conn.ravel(), pore_force.reshape(-1, 2))
        else:
            gamma_gp = np.broadcast_to(gamma[:, None], weights.shape)
        nodal_weight = -np.einsum("eg,eg,gn->en", gamma_gp, weights, geom.N)
        np.add.at(terms["soil_body"][:, 1], conn.ravel(), nodal_weight.ravel())
        external[1] -= np.sum(gamma_gp * weights)
        external[2] -= np.sum(gamma_gp * weights * geom.xg[mask, :, 0])
    for block in mesh.blocks:
        mask = _mask(stage, block)
        if block.etype is ElemType.BEAM2:
            values = _values(stage.beams, block.tag, (block.ne, 2, 3), mask).copy()
            group = BeamGroup(block, mesh.coords, model.liners[block.tag], model.analysis)
            values[:, 0] *= -1
            force = np.einsum("eji,ej->ei", group.T[mask], values.reshape(-1, 6))
            np.add.at(terms["beam"], block.conn[mask].ravel(), force.reshape(-1, 3))
            body = group.body_force(np.flatnonzero(mask))
            np.add.at(terms["beam_body"], block.conn[mask].ravel(), body.reshape(-1, 3))
            weight = group.L[mask] * group.spec.A * group.spec.unit_weight
            external[1] -= weight.sum()
            external[2] -= np.sum(weight * mesh.coords[block.conn[mask], 0].mean(axis=1))
        elif block.etype is ElemType.BAR2:
            # StageResult bar force already includes out-of-plane spacing and pretension.
            axial = _values(stage.bars, block.tag, (block.ne,), mask)
            xy = mesh.coords[block.conn[mask]]
            vector = xy[:, 1] - xy[:, 0]
            direction = vector / np.linalg.norm(vector, axis=1)[:, None]
            ends = axial[:, None] * direction
            force = np.stack((-ends, ends), axis=1)
            np.add.at(terms["bar"][:, :2], block.conn[mask].ravel(), force.reshape(-1, 2))
        elif block.etype in (ElemType.IFACE4, ElemType.IFACE6):
            group = InterfaceGroup(block, mesh.coords, model.interfaces[block.tag], model.analysis)
            interfaces.append(group)
            _values(stage.interfaces, block.tag, (block.ne, group.npe, 2), mask)
            if not np.isnan(np.asarray(stage.interfaces[block.tag])[~mask]).all():
                raise ValueError("Inactive interface results must be absent (NaN)")
            force = interface_nodal_force_transfer(
                mesh, block.tag, stage.interfaces[block.tag], model.interfaces[block.tag],
                analysis=model.analysis,
            )["nodal_forces"]
            terms["interface"][:, :2] += force
    reactions = np.asarray(stage.reactions, dtype=float)
    if reactions.shape != (mesh.nn, 3) or not np.isfinite(reactions).all():
        raise ValueError("Invalid reaction data")
    ties = tie_pairs(interfaces, stage.active, mesh.nn)
    if ties.size and not np.allclose(mesh.coords[ties[:, 0]], mesh.coords[ties[:, 1]],
                                     rtol=0., atol=1e-10):
        raise ValueError("Separated tied nodes need a moment-transfer reference")
    # Use the actual tied-DOF convention, without the solver's assembled force vector.
    beam_nodes = np.concatenate([b.conn[_mask(stage, b)].ravel() for b in mesh.blocks
                                 if b.etype is ElemType.BEAM2]) if names["beam"] else None
    dm = DofMap(mesh, stage.active, beam_nodes=beam_nodes, fixities=model.fixities, ties=ties)
    applied = independent_dry_applied_loads(model, definition, stage.active)
    terms["applied_load"] = applied["nodal"]
    weight_resultant = external.copy()
    external += applied["resultant"]
    if with_water:
        water = hydrostatic_nodal_forces(
            mesh, stage.active, head,
            nodal_pressure=seepage_evidence["nodal_pressure"] if seepage else None,
        )
        terms["boundary_water"] = water["boundary"]
        terms["joint_water"] = water["joint"]
    for key, value in terms.items():
        mapped = np.zeros_like(value)
        np.add.at(mapped, dm.owner, value)
        terms[key] = mapped
    mapped_reactions = np.zeros_like(reactions)
    np.add.at(mapped_reactions, dm.owner, reactions)
    reactions = mapped_reactions
    annotations = {}
    effective = terms["soil_body"] + terms["beam_body"] + terms["applied_load"]
    if with_water:
        boundary_physical = terms["boundary_water"].copy()
        prescribed = np.isin(dm.node_dofs, dm.prescribed) & (dm.node_dofs >= 0)
        terms["boundary_water"][prescribed] = 0.
        water_total = terms["continuum_water"] + terms["joint_water"] + terms["boundary_water"]
        effective = effective + water_total
        water_resultant = nodal_resultant(mesh, water_total)
        external += water_resultant
        annotations = {
            "water_head_m": head if np.isfinite(head) else None,
            "water_mode": definition.water.mode,
            "bulk_weight_reference": "gauss_point_saturation",
            "joint_water_reference": "trapezoidal_or_simpson_nodal_tributaries",
            "max_pressure_reference_error_kpa": pressure_error,
            "water_resultant": water_resultant.tolist(),
            "unfiltered_boundary_water_resultant": nodal_resultant(
                mesh, boundary_physical,
            ).tolist(),
            "withheld_boundary_water_resultant": nodal_resultant(
                mesh, boundary_physical - terms["boundary_water"],
            ).tolist(),
            "warning": (
                "Horizontal-head full-stage water assembly only; no seepage or physical validation."
            ),
        }
        if seepage:
            annotations.update(seepage_evidence["annotations"])
            annotations["pressure_reference"] = "interpolated_head_then_gp_pressure_clip"
            annotations["boundary_pressure_reference"] = "clipped_nodal_pressure_then_interpolation"
            annotations["warning"] = (
                "Full-stage seepage head/pressure transfer and reported flux balance only; "
                "not independent Darcy or physical validation."
            )
            pressure_ratio = max(pressure_ratio, seepage_evidence["relative_residual"])
    return {
        "terms": terms, "reactions": reactions, "external": external,
        "weight_resultant": weight_resultant, "applied": applied, "dm": dm, "ties": ties,
        "structural_tags": names["beam"] | names["bar"],
        "effective_external": effective, "annotations": annotations,
        "reference_relative_residual": pressure_ratio,
    }


def _summarize_dry_components(model, stage, components):
    """Evaluate separately reconstructed nodal and resultant terms."""
    mesh = model.mesh
    terms, reactions = components["terms"], components["reactions"]
    external, weight_resultant = components["external"], components["weight_resultant"]
    applied, dm, ties = components["applied"], components["dm"], components["ties"]
    effective = components.get("effective_external",
                               terms["soil_body"] + terms["beam_body"] + terms["applied_load"])
    residual = (terms["soil"] + terms["beam"] + terms["bar"] + terms["interface"]
                - effective - reactions)
    scale = np.maximum(1., np.maximum.reduce(
        [np.abs(value) for value in terms.values()] + [np.abs(reactions)]
    ))
    ratio = np.abs(residual) / scale
    reaction_total = reactions.sum(axis=0)
    reaction_total[2] += np.sum(mesh.coords[:, 0] * reactions[:, 1]
                                - mesh.coords[:, 1] * reactions[:, 0])
    global_residual = external + reaction_total
    force_scale = max(1., abs(weight_resultant[1]),
                      float(np.linalg.norm(applied["resultant"][:2])),
                      float(np.linalg.norm(external[:2])))
    length_scale = max(1., float(np.ptp(mesh.coords, axis=0).max()))
    metric = max(float(ratio.max()), float(np.linalg.norm(global_residual[:2]) / force_scale),
                 float(abs(global_residual[2]) / (force_scale * length_scale)),
                 components.get("reference_relative_residual", 0.))
    structural_nodes = np.unique(np.concatenate([
        b.conn[_mask(stage, b)].ravel() for b in mesh.blocks
        if b.etype in (ElemType.BEAM2, ElemType.BAR2)
    ])) if components["structural_tags"] else np.array([], dtype=int)
    owners = np.unique(dm.owner[structural_nodes])
    return classify_balance({
        "stage": stage.name,
        "external_weight_resultant": weight_resultant.tolist(),
        "applied_load_resultant": applied["resultant"].tolist(),
        "external_resultant": external.tolist(),
        "skipped_inactive_loaded_edges": applied["skipped_inactive_edges"],
        "reaction_resultant": reaction_total.tolist(),
        "global_residual": global_residual.tolist(),
        "max_nodal_force_residual": float(np.abs(residual[:, :2]).max()),
        "max_nodal_moment_residual": float(np.abs(residual[:, 2]).max()),
        "relative_residual": metric,
        "tied_node_pairs": len(ties),
        "structural_nodes": [
            {"node": int(n), "xy_m": mesh.coords[n].tolist(),
             "structural_source_nodes": structural_nodes[dm.owner[structural_nodes] == n].tolist(),
             **{key: value[n].tolist() for key, value in terms.items()},
             "reaction": reactions[n].tolist(), "residual": residual[n].tolist()}
            for n in owners
        ],
        "warning": "Dry full-stage assembly/equilibrium only; no independent physical validation.",
        **components.get("annotations", {}),
    }, "relative_residual")


def coupled_dry_stage_budget(model, result, index):
    """Return dry full-stage equilibrium acceptance, not physical validation."""
    components = _coupled_dry_components(model, result, index)
    return _summarize_dry_components(model, result.stages[index], components)


def coupled_dry_budget_by_stage(model, result):
    """Keep unsupported contracts distinct from measured equilibrium failures."""
    rows = []
    for index, stage in enumerate(result.stages):
        try:
            row = coupled_dry_stage_budget(model, result, index)
        except (ValueError, KeyError, IndexError) as exc:
            row = {"stage": stage.name, "status": "unsupported", "reason": str(exc)}
        rows.append(row)
    return rows
