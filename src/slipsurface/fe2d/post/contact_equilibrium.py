"""Bounded dry native-contact equilibrium, independently reassembled from snapshots.

Global external loads/reactions alone can hide an incorrect pair of internal contact
forces. Check every node and each continuum-connected component as well. Neither
StaticSolver's assembled residual nor a native contact group is used here. Continuum
shape derivatives/quadrature are shared with the FEM library, not a second FE solver.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType
from ..core.errors import ModelError
from ..fem.elements import kernel
from .contact_resultants import _geometry, moment_origin
from .contact_results import contact_points, normal_contact_tags
from .dry_applied_loads import independent_dry_applied_loads


class UnsupportedContactBudget(ValueError):
    """A valid problem requires terms outside this explicitly bounded audit."""


def _array(value, shape, label, *, kind="fiu"):
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in kind or not np.isfinite(array).all():
        raise ValueError(f"{label}: missing, malformed or nonfinite data")
    return array


def _contract(result, index):
    model = result.model
    if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)):
        raise ValueError("Stage index must be an integer (initial snapshot is not audited)")
    if not 0 <= index < len(model.stages) or len(result.stages) != len(model.stages):
        raise ValueError("Require matching, complete stage sequences and an in-range index")
    contacts = normal_contact_tags(model)
    bulk = model.mesh.continuum_blocks()
    if (
        model.analysis is not Analysis.PLANE_STRAIN
        or not contacts
        or not bulk
        or len(contacts) != len(model.interfaces)
        or model.liners
        or model.bolts
        or any(
            b.etype
            not in (
                ElemType.T3,
                ElemType.T6,
                ElemType.Q4,
                ElemType.Q8,
                ElemType.IFACE4,
                ElemType.IFACE6,
            )
            for b in model.mesh.blocks
        )
    ):
        raise UnsupportedContactBudget("Require plane-strain continuum and normal contact only")
    if (
        model.initial.mode != "none"
        or model.initial.gravity
        or model.initial.water.mode != "none"
        or any(m.drainage is not Drainage.DRAINED for m in model.materials.values())
    ):
        raise UnsupportedContactBudget("Require stress-free, dry, drained, zero-gravity history")
    regions = model.mesh.regions()
    if model.initial.active_regions is not None and model.initial.active_regions != regions:
        raise UnsupportedContactBudget("All continuum regions must remain active")
    for definition, snapshot in zip(model.stages[: index + 1], result.stages[: index + 1]):
        if (
            definition.load_split != 1.0
            or definition.water.mode != "none"
            or definition.seismic_kh
            or definition.seismic_kv
            or definition.material_override
            or (definition.active_regions is not None and definition.active_regions != regions)
        ):
            raise UnsupportedContactBudget(
                "Partial loads, water, seismic, property changes and excavation need another budget"
            )
        if (
            definition.name != snapshot.name
            or isinstance(snapshot.lam, (bool, np.bool_))
            or not isinstance(snapshot.lam, Real)
            or not math.isfinite(snapshot.lam)
            or snapshot.lam != 1.0
        ):
            raise ValueError("Snapshot sequence/load factor disagrees with full-stage definitions")
    if model.settings.method != "NR":
        raise UnsupportedContactBudget("Normal-contact audit currently requires NR")
    actual_tags = {
        b.tag for b in model.mesh.blocks if b.etype in (ElemType.IFACE4, ElemType.IFACE6)
    }
    if set(contacts) != actual_tags:
        raise ValueError("Declared contact properties do not match interface blocks")
    model.validate()
    mesh, snapshot = model.mesh, result.stages[index]
    if set(snapshot.active) != {b.tag for b in mesh.blocks}:
        raise ValueError("Missing or unexpected activity blocks")
    for block in mesh.blocks:
        mask = _array(snapshot.active[block.tag], (block.ne,), block.tag + " activity", kind="b")
        expected = block.tag not in contacts or block.tag in model.stages[index].active_structures
        if not np.all(mask == expected):
            raise ValueError(f"{block.tag}: activity contradicts the supported stage definition")
    if (
        set(snapshot.sig) != {b.tag for b in bulk}
        or set(snapshot.interfaces) != set(contacts)
        or set(snapshot.contact_gap) != set(contacts)
        or set(snapshot.contact_status) != set(contacts)
    ):
        raise ValueError("Missing or unexpected stress/contact snapshot maps")
    if snapshot.beams or snapshot.bars:
        raise ValueError("Unexpected beam/bar evidence in a continuum-contact snapshot")
    return model, snapshot, contacts


def _resultant(coords, force, origin):
    arms = coords - origin
    return np.array(
        [
            math.fsum(force[:, 0]),
            math.fsum(force[:, 1]),
            math.fsum(arms[:, 0] * force[:, 1] - arms[:, 1] * force[:, 0]),
        ]
    )


def _criterion(residual, scale, absolute, relative):
    residual, scale = np.asarray(residual, dtype=float), np.asarray(scale, dtype=float)
    limit = np.asarray(absolute) + relative * scale
    if not np.isfinite(residual).all() or not np.isfinite(limit).all() or np.any(limit <= 0):
        raise ValueError("Nonfinite equilibrium arithmetic")
    ratio = np.abs(residual) / limit
    return {
        "status": "passed" if np.all(ratio <= 1) else "failed",
        "maximum_absolute_residual": float(np.max(np.abs(residual), initial=0)),
        "maximum_tolerance_ratio": float(np.max(ratio, initial=0)),
    }


def _components(mesh, used):
    """Bulk-connected node sets; do not join opposite contact faces by coordinates."""
    parent = np.arange(mesh.nn)

    def root(node):
        while node != parent[node]:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return int(node)

    bulk_nodes = set()
    for block in mesh.continuum_blocks():
        for nodes in block.conn:
            bulk_nodes.update(map(int, nodes))
            first = root(int(nodes[0]))
            for node in nodes[1:]:
                parent[root(int(node))] = first
    bodies = {}
    for node in sorted(bulk_nodes):
        bodies.setdefault(root(node), []).append(node)
    partitions = [("continuum_component", np.array(nodes)) for nodes in bodies.values()]
    others = np.array(sorted(set(np.flatnonzero(used)) - bulk_nodes), dtype=int)
    if len(others):
        partitions.append(("contact_only_nodes", others))
    return partitions


def contact_stage_equilibrium(
    result,
    index,
    *,
    origin=(0.0, 0.0),
    force_atol=1e-8,
    moment_atol=1e-8,
    traction_atol=1e-8,
    rtol=1e-8,
):
    """Audit one full stage; indices refer to result.stages, excluding initial.

    Supported: dry stress-free plane-strain continuum/normal-contact models, constant
    active continuum topology, point/straight uniform edge loads and prescribed
    displacement. Contact activation/deactivation and report-datum resets are allowed.
    Explicit inactive contact contributes no force; missing active evidence is rejected.
    Custom extra_tractions are not persisted and cannot be audited from SolveResult.
    """
    origin = moment_origin(origin)
    for value in (force_atol, moment_atol, traction_atol, rtol):
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("Equilibrium tolerances must be finite and positive")
    model, st, tags = _contract(result, index)
    mesh, definition = model.mesh, model.stages[index]
    xy = _array(mesh.coords, (mesh.nn, 2), "coordinates").astype(float)
    soil = np.zeros((mesh.nn, 2))
    contact = np.zeros_like(soil)
    used = np.zeros(mesh.nn, dtype=bool)
    law_checks = []
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        for block in mesh.blocks:
            used[block.conn[st.active[block.tag]].ravel()] = True
        for block in mesh.continuum_blocks():
            geom = kernel(block.etype).precompute(
                xy, block.conn, model.analysis, model.settings.gauss_order
            )
            shape = (*geom.wdet.shape, 4)
            stress = _array(st.sig[block.tag], shape, block.tag + " stress")
            for mapping in (st.pore, st.excess_pore):
                if block.tag in mapping:
                    pressure = _array(mapping[block.tag], geom.wdet.shape, "pore pressure")
                    if np.any(pressure != 0):
                        raise ValueError("Nonzero pore evidence contradicts the dry model")
            force = np.einsum("egki,egk,eg->ei", geom.B, stress, geom.wdet)
            np.add.at(soil, block.conn.ravel(), force.reshape(-1, 2))
        for tag in tags:
            block = mesh.block(tag)
            _, _, normal, weights, _ = _geometry(mesh, block)
            points = contact_points(result, st, tag)
            for p in points:
                if not p.active:
                    continue
                if p.availability != "available":
                    raise ValueError(f"{tag}: missing active contact evidence")
                target = model.interfaces[tag].kn * min(p.gap_m, 0.0)
                law_checks.append((p.normal_traction_kpa - target, abs(target)))
                internal = p.normal_traction_kpa * weights[p.element, p.point] * normal[p.element]
                contact[p.face1_node] -= internal
                contact[p.face2_node] += internal
        load = independent_dry_applied_loads(model, definition, st.active)
        applied = load["nodal"][:, :2]
        reactions = _array(st.reactions, (mesh.nn, 3), "reactions").astype(float)
        prescribed = np.zeros((mesh.nn, 2), dtype=bool)
        for fix in model.fixities:
            prescribed[mesh.nodes(fix.node_set)] |= [fix.ux, fix.uy]
        for disp in (*model.displacements, *definition.displacements):
            prescribed[mesh.nodes(disp.node_set)] |= [disp.ux is not None, disp.uy is not None]
        prescribed &= used[:, None]
        scale = np.maximum.reduce([np.abs(x) for x in (soil, contact, applied, reactions[:, :2])])
        residual = soil + contact - applied - reactions[:, :2]
        external = np.array(load["resultant"], dtype=float)
        external[2] += -origin[0] * external[1] + origin[1] * external[0]
        reaction_total = _resultant(xy, reactions[:, :2], origin)
        global_residual = external + reaction_total
        total_scale = np.maximum(np.abs(external), np.abs(reaction_total))
        absolute = np.array([force_atol, force_atol, moment_atol])
        checks = {
            "nodal_force_kn_per_m": _criterion(residual, scale, force_atol, rtol),
            "global_force_kn_per_m": _criterion(
                global_residual[:2], total_scale[:2], force_atol, rtol
            ),
            "global_moment_knm_per_m": _criterion(
                global_residual[2:], total_scale[2:], moment_atol, rtol
            ),
            "reaction_on_free_or_inactive_dof": _criterion(
                reactions[:, :2][~prescribed], scale[~prescribed], force_atol, rtol
            ),
            "unexpected_rotational_reaction": _criterion(
                reactions[:, 2], np.zeros(mesh.nn), moment_atol, rtol
            ),
            "load_resultant_reconstruction": _criterion(
                _resultant(xy, applied, origin) - external, np.abs(external), absolute, rtol
            ),
        }
        if law_checks:
            errors, scales = np.array(law_checks).T
            checks["gap_pressure_law_kpa"] = _criterion(errors, scales, traction_atol, rtol)
        else:
            checks["gap_pressure_law_kpa"] = {
                "status": "not_applicable",
                "reason": "All declared contacts explicitly inactive",
            }
        partitions = []
        for number, (kind, nodes) in enumerate(_components(mesh, used)):
            point_xy = xy[nodes]
            terms = {
                "applied": _resultant(point_xy, applied[nodes], origin),
                "reaction": _resultant(point_xy, reactions[nodes, :2], origin),
                "contact_action": _resultant(point_xy, -contact[nodes], origin),
            }
            balance = sum(terms.values())
            local_scale = np.maximum.reduce([np.abs(v) for v in terms.values()])
            verdict = _criterion(balance, local_scale, absolute, rtol)
            partitions.append(
                {
                    "partition": number,
                    "kind": kind,
                    "nodes": nodes.tolist(),
                    **{k: v.tolist() for k, v in terms.items()},
                    "residual": balance.tolist(),
                    **verdict,
                }
            )
        bad = int(np.argmax(np.max(np.abs(residual), axis=1)))
        passed = all(x["status"] in ("passed", "not_applicable") for x in checks.values()) and all(
            x["status"] == "passed" for x in partitions
        )
        return {
            "stage_index": int(index),
            "stage": st.name,
            "origin_m": list(origin),
            "status": "passed" if passed else "failed",
            "checks": checks,
            "tolerances": dict(
                force_atol_kn_per_m=force_atol,
                moment_atol_knm_per_m=moment_atol,
                traction_atol_kpa=traction_atol,
                rtol=rtol,
            ),
            "external_resultant": external.tolist(),
            "reaction_resultant": reaction_total.tolist(),
            "global_residual": global_residual.tolist(),
            "partitions": partitions,
            "worst_node": {
                "id": bad,
                "soil_internal": soil[bad].tolist(),
                "contact_internal": contact[bad].tolist(),
                "applied": applied[bad].tolist(),
                "reaction": reactions[bad, :2].tolist(),
                "residual": residual[bad].tolist(),
            },
            "scope": "Bounded numerical equilibrium, not independent physical/model validation. "
            "No gravity, water, beams/bars, partial stages, excavation or restart. "
            "Only persisted model loads are included; no custom extra_tractions.",
        }


def contact_equilibrium_by_stage(result, **kwargs):
    """Preserve unsupported, invalid and measured failure as separate outcomes."""
    rows = []
    for index, snapshot in enumerate(result.stages):
        try:
            row = contact_stage_equilibrium(result, index, **kwargs)
        except UnsupportedContactBudget as exc:
            row = {
                "stage_index": index,
                "stage": snapshot.name,
                "status": "unsupported",
                "reason": str(exc),
            }
        except (
            ModelError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            OverflowError,
            FloatingPointError,
        ) as exc:
            row = {
                "stage_index": index,
                "stage": snapshot.name,
                "status": "invalid",
                "reason": str(exc),
            }
        rows.append(row)
    return {
        "status": "passed" if rows and all(r["status"] == "passed" for r in rows) else "failed",
        "stage_count": len(rows),
        "stages": rows,
    }
