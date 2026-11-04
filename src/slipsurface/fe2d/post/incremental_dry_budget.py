"""Partial dry elastic stages: actual external loads plus retained release forces.

No solver assembled force vector is read. Newly activated elements in partial
stages remain unsupported because their initialization needs a separate reference.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from ..core.enums import ElemType
from ..fem.activity import tie_pairs
from ..fem.assembly import DofMap
from ..fem.elements import kernel
from ..fem.structural import BeamGroup, InterfaceGroup
from ..model.stages import Stage
from .coupled_dry_budget import _coupled_dry_components, _mask, _summarize_dry_components


def _map_to_current(value, dm):
    mapped = np.zeros_like(value)
    used = dm.used_nodes
    np.add.at(mapped, dm.owner[used], value[used])
    return mapped


def _resultant(mesh, value):
    total = value.sum(axis=0)
    total[2] += np.sum(mesh.coords[:, 0] * value[:, 1] - mesh.coords[:, 1] * value[:, 0])
    return total


def _initial_external(model, initial):
    """Independently reconstruct initial dry gravity loads on initial owner nodes."""
    mesh = model.mesh
    body = np.zeros((mesh.nn, 3))
    interfaces = []
    for block in mesh.blocks:
        mask = _mask(initial, block)
        if block.etype in (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8):
            geom = kernel(block.etype).precompute(
                mesh.coords, block.conn, model.analysis, model.settings.gauss_order,
            )
            gamma = np.array([model.materials[model.region_material[int(r)]].gamma_unsat
                              for r in block.region[mask]])
            weight = -gamma[:, None] * (geom.wdet[mask] @ geom.N)
            np.add.at(body[:, 1], block.conn[mask].ravel(), weight.ravel())
        elif block.etype is ElemType.BEAM2:
            group = BeamGroup(block, mesh.coords, model.liners[block.tag], model.analysis)
            np.add.at(body, block.conn[mask].ravel(), group.body_force(
                np.flatnonzero(mask)
            ).reshape(-1, 3))
        elif block.etype in (ElemType.IFACE4, ElemType.IFACE6):
            interfaces.append(InterfaceGroup(
                block, mesh.coords, model.interfaces[block.tag], model.analysis,
            ))
    dm = DofMap(mesh, initial.active, ties=tie_pairs(interfaces, initial.active, mesh.nn))
    return _map_to_current(body, dm)


def _initial_hydrostatic_components(model, result):
    """Rebuild initial body/water fields with the initial declared activity and head."""
    structures = model.initial.active_structures
    if structures is None:
        structures = frozenset(model.interfaces)
    step = Stage(result.initial.name, active_regions=model.initial.active_regions,
                 active_structures=structures, water=model.initial.water)
    shadow_model = replace(model, stages=[step])
    shadow_result = replace(result, stages=[replace(result.initial, lam=1.)])
    return _coupled_dry_components(shadow_model, shadow_result, 0, hydrostatic=True)


def _water_field(terms):
    return terms["continuum_water"] + terms["joint_water"] + terms["boundary_water"]


def _start_components(model, result, index, current, *, hydrostatic=False):
    """Retain previous committed states on the current, excavation-only active set."""
    previous = result.initial if index == 0 else result.stages[index - 1]
    for block in model.mesh.blocks:
        if np.any(_mask(current, block) & ~_mask(previous, block)):
            raise ValueError("New activation in a partial stage needs an initialization reference")
    interfaces = {}
    for tag, value in previous.interfaces.items():
        interfaces[tag] = value.copy()
        interfaces[tag][~current.active[tag]] = np.nan
    start = replace(previous, name=current.name, active=current.active,
                    lam=current.lam, interfaces=interfaces)
    shadow = replace(result, stages=[*result.stages[:index], start])
    return _coupled_dry_components(model, shadow, index, require_full=False,
                                   hydrostatic=hydrostatic)


def _incremental_budget_by_stage(model, result, *, hydrostatic=False):
    """Reconstruct actual applied loads recursively; report unsupported history explicitly."""
    rows = []
    previous_external = None
    previous_water = None
    history_error = None
    for index, stage in enumerate(result.stages):
        if history_error:
            rows.append({"stage": stage.name, "status": "unsupported",
                         "reason": "Earlier incremental evidence unsupported: " + history_error})
            continue
        try:
            components = _coupled_dry_components(model, result, index, require_full=False,
                                                 hydrostatic=hydrostatic)
            if any(spec.model != "elastic" for spec in model.materials.values()):
                raise ValueError("Incremental reconstruction currently requires elastic soil")
            if previous_external is None:
                if hydrostatic:
                    initial = _initial_hydrostatic_components(model, result)
                    if initial["reference_relative_residual"] > 1e-6:
                        raise ValueError(
                            "Initial pore-pressure evidence disagrees with initial head"
                        )
                    previous_external = initial["effective_external"]
                    previous_water = _water_field(initial["terms"])
                else:
                    previous_external = _initial_external(model, result.initial)
            dm, terms = components["dm"], components["terms"]
            previous = _map_to_current(previous_external, dm)
            target = components["effective_external"]
            lam = stage.lam
            actual = lam * target + (1 - lam) * previous
            retained = np.zeros_like(actual)
            if lam < 1.:
                start = _start_components(model, result, index, stage,
                                          hydrostatic=hydrostatic)["terms"]
                internal0 = start["soil"] + start["beam"] + start["bar"] + start["interface"]
                retained = (1 - lam) * (internal0 - previous)
                # Reactions are recorded against actual applied loads at prescribed DOFs.
                prescribed = np.isin(dm.node_dofs, dm.prescribed) & (dm.node_dofs >= 0)
                retained[prescribed] = 0.
            terms["actual_applied_external"] = actual
            terms["retained_release"] = retained
            components["effective_external"] = actual + retained
            actual_resultant = lam * components["external"] + (1 - lam) * _resultant(
                model.mesh, previous,
            )
            retained_resultant = _resultant(model.mesh, retained)
            components["external"] = actual_resultant + retained_resultant
            components["annotations"] = {
                **components.get("annotations", {}),
                "load_fraction": lam,
                "actual_applied_resultant": actual_resultant.tolist(),
                "retained_release_resultant": retained_resultant.tolist(),
                "max_retained_release_force": float(np.abs(retained[:, :2]).max()),
                "warning": (
                    "Elastic incremental numerical equilibrium only; no physical validation."
                ),
            }
            if hydrostatic:
                actual_water = lam * _water_field(terms) + (1 - lam) * _map_to_current(
                    previous_water, dm,
                )
                terms["actual_applied_water"] = actual_water
                components["annotations"].update({
                    "actual_applied_water_resultant": _resultant(model.mesh, actual_water).tolist(),
                    "target_water_resultant": components["annotations"]["water_resultant"],
                    "water_resultant_scope": "current_stage_target",
                })
                previous_water = actual_water
            row = _summarize_dry_components(model, stage, components)
            previous_external = actual
        except (ValueError, KeyError, IndexError) as exc:
            history_error = str(exc)
            row = {"stage": stage.name, "status": "unsupported", "reason": history_error}
        rows.append(row)
    return rows


def incremental_dry_budget_by_stage(model, result):
    """Reconstruct dry elastic loading/release histories with explicit unsupported results."""
    return _incremental_budget_by_stage(model, result)
