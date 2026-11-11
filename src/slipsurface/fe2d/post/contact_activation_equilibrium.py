"""Partial contact activation budgets with an explicit retained-release load.

Every node must belong to unchanged active continuum. The original public audit
requires fixed prescribed-DOF membership; the private engine also serves the
explicit temporary-support audit. Total displacement is recovered from stored
reported snapshots and datum resets. No native residual, private applied-force
vector, or restart state is read.
"""

from __future__ import annotations

import math
from dataclasses import replace
from numbers import Real

import numpy as np

from ..fem.elements import kernel
from ..model.boundary import PointLoad
from .contact_equilibrium import (
    UnsupportedContactBudget,
    _array,
    _contract,
    _criterion,
    _resultant,
    contact_stage_equilibrium,
)
from .contact_partial_equilibrium import (
    _ERRORS,
    _fraction,
    _full_view,
    _initial_reference,
    _prescribed,
)
from .contact_resultants import _geometry, moment_origin
from .contact_results import contact_points, normal_contact_tags
from .dry_applied_loads import independent_dry_applied_loads

_SCOPE = (
    "Dry stress-free zero-gravity normal contact; fixed active continuum covering every "
    "node and fixed prescribed-DOF membership. Contact tags may switch on/off. Retained "
    "release is a numerical stage term, NOT an additional physical applied load. No "
    "excavation, support removal, hydraulic contact, restart or design certification."
)


def _soil_internal(model, snapshot):
    """Shared continuum quadrature, independently assembled from stored stresses."""
    force = np.zeros((model.mesh.nn, 2))
    for block in model.mesh.continuum_blocks():
        geom = kernel(block.etype).precompute(
            model.mesh.coords, block.conn, model.analysis, model.settings.gauss_order,
        )
        stress = _array(snapshot.sig[block.tag], (*geom.wdet.shape, 4), "previous stress")
        local = np.einsum("egki,egk,eg->ei", geom.B, stress, geom.wdet)
        np.add.at(force, block.conn.ravel(), local.reshape(-1, 2))
    return force


def _geometric_contact(model, total_u, active):
    """Current-active contact at the previous total geometry, not clipped old stress."""
    force = np.zeros((model.mesh.nn, 2))
    gaps = {}
    for tag in normal_contact_tags(model):
        block, spec = model.mesh.block(tag), model.interfaces[tag]
        _, _, normal, weights, _ = _geometry(model.mesh, block)
        n = block.etype.nen // 2
        first, second = block.conn[:, :n], block.conn[:, n:]
        gap = spec.initial_gap + np.einsum(
            "epi,ei->ep", total_u[second] - total_u[first], normal,
        )
        if not np.isfinite(gap).all():
            raise ValueError("Nonfinite reconstructed geometric gap")
        gaps[tag] = gap
        traction = spec.kn * np.minimum(gap, 0.0)
        contribution = (traction * weights)[..., None] * normal[:, None, :]
        selected = active[tag]
        np.add.at(force, first[selected].ravel(), -contribution[selected].reshape(-1, 2))
        np.add.at(force, second[selected].ravel(), contribution[selected].reshape(-1, 2))
    return force, gaps


def _prescribed_targets(model, definition):
    target = np.zeros((model.mesh.nn, 2))
    for item in (*model.displacements, *definition.displacements):
        for axis, value in enumerate((item.ux, item.uy)):
            if value is not None:
                if isinstance(value, (bool, np.bool_)) or not math.isfinite(value):
                    raise ValueError("Nonfinite or boolean prescribed displacement")
                target[model.mesh.nodes(item.node_set), axis] = value
    return target


def _contact_history_equilibrium(
    result, *, origin=(0.0, 0.0), force_atol=1e-8, moment_atol=1e-8,
    traction_atol=1e-8, gap_atol=1e-10, rtol=1e-8,
    support_changes=False, scope=_SCOPE,
):
    """Reconstruct physical loads AND unfinished release from accepted snapshots.

    F_i = (1-a)*F_(i-1) + a*F_target_i.
    I0_i = soil(stress_(i-1)) + contact(current activity, total_u_(i-1)).
    H_i = (1-a)*P_free*(I0_i - F_(i-1)).
    Check I_i - F_i - R_i - H_i = 0 at every node. H is excluded on prescribed
    DOFs because the recorded reactions are relative to physical F_i. Preceding
    unfinished release is retained in I0; it is not discarded on an unchanged
    subsequent stage. A failed predecessor blocks every dependent claim.
    """
    origin = moment_origin(origin)
    for value in (force_atol, moment_atol, traction_atol, gap_atol, rtol):
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not math.isfinite(value) or value <= 0):
            raise ValueError("Audit tolerances must be positive finite real values")
    options = dict(origin=origin, force_atol=force_atol, moment_atol=moment_atol,
                   traction_atol=traction_atol, rtol=rtol)
    rows, definitions, snapshots = [], [], []
    initial_status = "invalid"
    try:
        model = result.model
        if not model.stages or len(model.stages) != len(result.stages):
            raise ValueError("Require complete matching model/snapshot sequences")
        _, prescribed = _initial_reference(result, options)
        covered = np.zeros(model.mesh.nn, dtype=bool)
        for block in model.mesh.continuum_blocks():
            covered[block.conn.ravel()] = True
        if not covered.all():
            raise UnsupportedContactBudget(
                "Every node must belong to unchanged active continuum; disappearing "
                "contact-only nodes need another displacement-reference contract"
            )
        previous_u = _array(result.initial.u, (model.mesh.nn, 2), "initial displacement")
        datum = np.zeros_like(previous_u)
        previous_load = np.zeros_like(previous_u)
        previous_total = np.zeros(3)
        initial_status = "passed"
    except _ERRORS as exc:
        initial_status = "unsupported" if isinstance(exc, UnsupportedContactBudget) else "invalid"
        return {"status": "failed", "initial_status": initial_status, "reason": str(exc),
                "stage_count": len(result.stages), "scope": scope,
                "stages": [{"stage_index": i, "stage": st.name, "status": "blocked",
                            "reason": "Invalid/unsupported initial reference"}
                           for i, st in enumerate(result.stages)]}
    failed_index = None
    previous_snapshot = result.initial
    for index, (definition, snapshot) in enumerate(zip(model.stages, result.stages)):
        if failed_index is not None:
            rows.append({"stage_index": index, "stage": snapshot.name, "status": "blocked",
                         "blocked_by_stage_index": failed_index})
            continue
        try:
            alpha = _fraction(definition.load_split, "Declared load split")
            if (_fraction(snapshot.lam, "Accepted load factor") != alpha
                    or snapshot.name != definition.name):
                raise ValueError("Accepted fraction/identity differs from declared stage")
            if not isinstance(definition.reset_displacements, (bool, np.bool_)):
                raise ValueError("Reporting datum reset must be boolean")
            current = replace(definition, load_split=1.0)
            recorded = replace(snapshot, lam=1.0)
            view = _full_view(result, [*definitions, current], [*snapshots, recorded])
            # Enforce #83's full dry/topology/data contract before reading any arrays.
            _contract(view, index)
            current_prescribed = _prescribed(model, definition.displacements)
            released = prescribed & ~current_prescribed
            added = current_prescribed & ~prescribed
            if not support_changes and not np.array_equal(current_prescribed, prescribed):
                raise UnsupportedContactBudget("Prescribed-DOF membership must remain fixed")
            if definition.reset_displacements:
                datum = previous_u.copy()
            reported = _array(snapshot.u, (model.mesh.nn, 2), "reported displacement")
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                total_u = reported + datum
                target = independent_dry_applied_loads(model, definition, snapshot.active)
                actual = (1-alpha)*previous_load + alpha*target["nodal"][:, :2]
                actual_total = (1-alpha)*previous_total + alpha*target["resultant"]
                contact_start, start_gaps = _geometric_contact(model, previous_u, snapshot.active)
                start = _soil_internal(model, previous_snapshot) + contact_start
                retained = (1-alpha)*(start - previous_load)
                retained[current_prescribed] = 0.0
                effective = actual + retained
                if not np.isfinite(effective).all() or not np.isfinite(total_u).all():
                    raise ValueError("Nonfinite stage-history reconstruction")
                loads = tuple(PointLoad(i, float(fx), float(fy))
                              for i, (fx, fy) in enumerate(effective) if fx != 0 or fy != 0)
                current = replace(current, loads=loads)
                view = _full_view(result, [*definitions, current], [*snapshots, recorded])
                row = contact_stage_equilibrium(view, index, **options)
                physical = actual_total.copy()
                physical[2] += -origin[0]*physical[1] + origin[1]*physical[0]
                release_total = _resultant(model.mesh.coords, retained, origin)
                absolute = np.array([force_atol, force_atol, moment_atol])
                row["checks"]["physical_load_history_resultant"] = _criterion(
                    _resultant(model.mesh.coords, actual, origin)-physical,
                    np.abs(physical), absolute, rtol,
                )
                _, current_gaps = _geometric_contact(model, total_u, snapshot.active)
                errors, scales = [], []
                for point in contact_points(result, snapshot):
                    if point.active:
                        exact = current_gaps[point.tag][point.element, point.point]
                        errors.append(point.gap_m-exact)
                        scales.append(abs(exact))
                row["checks"]["stored_geometric_gap_m"] = _criterion(
                    errors, scales, gap_atol, rtol,
                ) if errors else {"status": "not_applicable", "reason": "Contact inactive"}
                displacement_target = _prescribed_targets(model, definition)
                prescribed_actual = (1-alpha)*previous_u + alpha*displacement_target
                row["checks"]["prescribed_displacement_history_m"] = _criterion(
                    (total_u-prescribed_actual)[current_prescribed],
                    np.abs(prescribed_actual[current_prescribed]), gap_atol, rtol,
                )
                # Label effective balance honestly; physical-only imbalance is expected
                # while a nonzero retained release is present on free DOFs.
                row["physical_external_resultant"] = physical.tolist()
                row["effective_external_resultant"] = row.pop("external_resultant")
                row["effective_global_residual"] = row.pop("global_residual")
                row["physical_global_residual"] = (
                    physical + np.asarray(row["reaction_resultant"])
                ).tolist()
                row["retained_release_resultant"] = release_total.tolist()
                for part in row["partitions"]:
                    ids = np.asarray(part["nodes"], dtype=int)
                    part["effective_applied"] = part.pop("applied")
                    part["physical_applied"] = _resultant(
                        model.mesh.coords[ids], actual[ids], origin,
                    ).tolist()
                    part["retained_release"] = _resultant(
                        model.mesh.coords[ids], retained[ids], origin,
                    ).tolist()
                node = row["worst_node"]["id"]
                row["worst_node"]["effective_applied"] = row["worst_node"].pop("applied")
                row["worst_node"]["physical_applied"] = actual[node].tolist()
                row["worst_node"]["retained_release"] = retained[node].tolist()
                row["history"] = {
                    "accepted_fraction": alpha,
                    "active_contacts": sorted(definition.active_structures),
                    "previous_physical_resultant_about_global_zero": previous_total.tolist(),
                    "target_resultant_about_global_zero": target["resultant"].tolist(),
                    "actual_physical_resultant_about_global_zero": actual_total.tolist(),
                    "start_internal_nodal": start.tolist(),
                    "actual_physical_nodal": actual.tolist(),
                    "retained_release_nodal": retained.tolist(),
                    "start_geometric_gap_m": {k: v.tolist() for k, v in start_gaps.items()},
                    "report_datum_reset": bool(definition.reset_displacements),
                }
                if support_changes:
                    # Check the newly-free imbalance against prior reactions as an
                    # INDEPENDENT check, never as the source of an applied force.
                    old_contact, _ = _geometric_contact(
                        model, previous_u, previous_snapshot.active,
                    )
                    old_reactions = _array(
                        previous_snapshot.reactions, (model.mesh.nn, 3), "previous reactions",
                    )[:, :2]
                    delta_contact = contact_start-old_contact
                    expected_start = old_reactions+delta_contact
                    row["checks"]["released_dof_start_force"] = _criterion(
                        (start-previous_load-expected_start)[released],
                        np.abs(expected_start[released]), force_atol, rtol,
                    )
                    row["support_changes"] = {
                        "released_dofs": np.argwhere(released).tolist(),
                        "added_dofs": np.argwhere(added).tolist(),
                        "prescribed_dofs": np.argwhere(current_prescribed).tolist(),
                        "released_previous_reactions": old_reactions[released].tolist(),
                        "released_contact_change": delta_contact[released].tolist(),
                        "released_retained_force": retained[released].tolist(),
                        "reaction_on_released_dofs": _criterion(
                            np.asarray(snapshot.reactions)[:, :2][released],
                            np.zeros(np.count_nonzero(released)), force_atol, rtol,
                        ),
                    }
                    # Physical-only residuals are NOT masked by the retained load.
                    physical_loads = tuple(PointLoad(i, float(fx), float(fy))
                                           for i, (fx, fy) in enumerate(actual)
                                           if fx != 0 or fy != 0)
                    physical_view = _full_view(
                        result, [*definitions, replace(current, loads=physical_loads)],
                        [*snapshots, recorded],
                    )
                    physical_row = contact_stage_equilibrium(physical_view, index, **options)
                    row["physical_equilibrium"] = {
                        "status": physical_row["status"],
                        "checks": physical_row["checks"],
                        "partitions": physical_row["partitions"],
                        "meaning": "Physical loads and current reactions ONLY; no retained release",
                    }
                row["scope"] = scope
                if any(c["status"] not in ("passed", "not_applicable")
                       for c in row["checks"].values()):
                    row["status"] = "failed"
                if row["status"] == "passed":
                    previous_load, previous_total = actual, actual_total
                    previous_u, previous_snapshot = total_u, snapshot
                    prescribed = current_prescribed
                    definitions.append(current)
                    snapshots.append(recorded)
        except _ERRORS as exc:
            row = {"stage_index": index, "stage": snapshot.name,
                   "status": "unsupported" if isinstance(exc, UnsupportedContactBudget)
                   else "invalid", "reason": str(exc)}
        rows.append(row)
        if row["status"] != "passed":
            failed_index = index
    return {"status": "passed" if rows and failed_index is None else "failed",
            "initial_status": initial_status, "stage_count": len(rows),
            "stages": rows, "scope": scope}


def contact_activation_equilibrium_by_stage(
    result, *, origin=(0.0, 0.0), force_atol=1e-8, moment_atol=1e-8,
    traction_atol=1e-8, gap_atol=1e-10, rtol=1e-8,
):
    """Original contact-switching audit; prescribed-DOF membership remains fixed."""
    return _contact_history_equilibrium(
        result, origin=origin, force_atol=force_atol, moment_atol=moment_atol,
        traction_atol=traction_atol, gap_atol=gap_atol, rtol=rtol,
    )
