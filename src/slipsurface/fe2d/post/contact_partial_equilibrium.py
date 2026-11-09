"""Independent external-load history for fixed-topology partial normal-contact stages.

The full-stage audit remains unchanged. Its force reassembly is reused on shallow
views of the original snapshots with independently reconstructed applied loads. No
solver state, native residual, reaction-derived load, or restart state is consulted.
"""

from __future__ import annotations

import math
from dataclasses import replace
from numbers import Real

import numpy as np

from ..core.errors import ModelError
from ..model.boundary import PointLoad
from ..model.stages import Stage
from .contact_equilibrium import (
    UnsupportedContactBudget,
    _array,
    _criterion,
    contact_stage_equilibrium,
)
from .contact_resultants import moment_origin
from .contact_results import contact_points, normal_contact_tags
from .dry_applied_loads import independent_dry_applied_loads

_ERRORS = (ModelError, ValueError, KeyError, IndexError, TypeError, OverflowError,
           FloatingPointError, AttributeError)
_SCOPE = (
    "Fixed continuum/contact activity and prescribed-DOF membership; dry, stress-free, "
    "zero-gravity full-Newton histories. Partial fractions interpolate previous actual "
    "external loads, not previous targets. No release forces, excavation, water, "
    "support removal, custom extra_tractions or nonlinear restart are reconstructed."
)


def _fraction(value, label):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
            or not math.isfinite(value) or not 0 < value <= 1):
        raise ValueError(f"{label}: expected a finite real fraction in (0, 1]")
    return float(value)


def _prescribed(model, displacements):
    mask = np.zeros((model.mesh.nn, 2), dtype=bool)
    for fixity in model.fixities:
        mask[model.mesh.nodes(fixity.node_set)] |= [fixity.ux, fixity.uy]
    for item in (*model.displacements, *displacements):
        mask[model.mesh.nodes(item.node_set)] |= [item.ux is not None, item.uy is not None]
    return mask


def _full_view(result, definitions, snapshots):
    """Reassembly-only view: original stored arrays are shared read-only, never solved."""
    return replace(result, model=replace(result.model, stages=definitions), stages=snapshots)


def _initial_reference(result, options):
    """Verify the declared zero-load, zero-stress start rather than assume its data."""
    model, initial = result.model, result.initial
    tags = normal_contact_tags(model)
    active = (set(tags) if model.initial.active_structures is None
              else set(model.initial.active_structures))
    if _fraction(initial.lam, "Initial snapshot load factor") != 1.0:
        raise ValueError("Initial snapshot must be complete")
    definition = Stage(initial.name, active_structures=active)
    view = _full_view(result, [definition], [replace(initial, lam=1.0)])
    row = contact_stage_equilibrium(view, 0, **options)
    if row["status"] != "passed":
        raise ValueError("Initial snapshot does not satisfy zero-load equilibrium")
    for stress in initial.sig.values():
        if np.any(stress != 0):
            raise ValueError("Initial snapshot contains stress in a stress-free history")
    if np.any(initial.reactions != 0):
        raise ValueError("Initial snapshot contains reactions in a zero-load history")
    used = np.zeros(model.mesh.nn, dtype=bool)
    for block in model.mesh.blocks:
        used[block.conn[initial.active[block.tag]].ravel()] = True
    u = np.asarray(initial.u)
    if (u.shape != (model.mesh.nn, 2) or u.dtype.kind not in "fiu"
            or not np.isfinite(u[used]).all() or np.any(u[used] != 0)):
        raise ValueError("Initial snapshot displacement is not the original stress-free reference")
    for point in contact_points(result, initial):
        if point.active and point.gap_m != model.interfaces[point.tag].initial_gap:
            raise ValueError("Initial snapshot gap differs from the explicit initial clearance")
    return active, _prescribed(model, ())


def contact_partial_equilibrium_by_stage(
    result, *, origin=(0.0, 0.0), force_atol=1e-8, moment_atol=1e-8,
    traction_atol=1e-8, rtol=1e-8,
):
    """Check a complete accepted history, failing visibly on a bad predecessor.

    A stage ending at alpha uses F_i = (1-alpha)*F_(i-1) + alpha*F_target_i.
    Under unchanged active topology and prescribed-DOF membership, no free-DOF
    release term is present. Changes to either are deliberately unsupported,
    including full stages in this history API. The existing full-stage audit
    continues to support its own activation/deactivation contract unchanged.
    """
    options = dict(origin=moment_origin(origin), force_atol=force_atol,
                   moment_atol=moment_atol, traction_atol=traction_atol, rtol=rtol)
    for value in (force_atol, moment_atol, traction_atol, rtol):
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not math.isfinite(value) or value <= 0):
            raise ValueError("Equilibrium tolerances must be finite and positive")
    rows, definitions, snapshots = [], [], []
    failure = None
    initial_status = "invalid"
    try:
        model = result.model
        if not model.stages or len(result.stages) != len(model.stages):
            raise ValueError("Require complete matching model/snapshot stage sequences")
        activity, prescribed = _initial_reference(result, options)
        initial_status = "passed"
        previous = np.zeros((model.mesh.nn, 2))
        previous_resultant = np.zeros(3)
    except UnsupportedContactBudget as exc:
        initial_status, failure = "unsupported", str(exc)
    except _ERRORS as exc:
        failure = str(exc)
    if failure is not None:
        return {"status": "failed", "initial_status": initial_status,
                "stage_count": len(result.stages), "reason": failure,
                "stages": [{"stage_index": i, "stage": st.name, "status": "blocked",
                            "reason": "Initial history unavailable: " + failure}
                           for i, st in enumerate(result.stages)], "scope": _SCOPE}
    failed_index = None
    for index, (definition, snapshot) in enumerate(zip(model.stages, result.stages)):
        if failed_index is not None:
            rows.append({"stage_index": index, "stage": snapshot.name, "status": "blocked",
                         "blocked_by_stage_index": failed_index,
                         "reason": "A previous stage failed the history audit"})
            continue
        try:
            alpha = _fraction(definition.load_split, "Declared load split")
            observed = _fraction(snapshot.lam, "Accepted snapshot load factor")
            if observed != alpha or snapshot.name != definition.name:
                raise ValueError("Snapshot identity/load factor differs from declared stage")
            if set(definition.active_structures) != activity:
                raise UnsupportedContactBudget(
                    "Contact activation/deactivation needs a retained-release reference"
                )
            if not np.array_equal(_prescribed(model, definition.displacements), prescribed):
                raise UnsupportedContactBudget(
                    "Changing prescribed-DOF membership needs a retained-release reference"
                )
            # Before using activity for load assembly, require exactly the fixed masks.
            if set(snapshot.active) != set(result.initial.active):
                raise ValueError("Missing or unexpected snapshot activity maps")
            for block in model.mesh.blocks:
                mask = _array(snapshot.active[block.tag], (block.ne,), "activity", kind="b")
                if not np.array_equal(mask, result.initial.active[block.tag]):
                    raise ValueError("Stored activity contradicts the fixed-topology history")
            target = independent_dry_applied_loads(model, definition, snapshot.active)
            with np.errstate(over="raise", invalid="raise"):
                applied = (1 - alpha) * previous + alpha * target["nodal"][:, :2]
                total = (1 - alpha) * previous_resultant + alpha * target["resultant"]
            if not np.isfinite(applied).all() or not np.isfinite(total).all():
                raise ValueError("Nonfinite applied-load history")
            loads = tuple(PointLoad(i, float(fx), float(fy))
                          for i, (fx, fy) in enumerate(applied) if fx != 0 or fy != 0)
            current = replace(definition, load_split=1.0, loads=loads)
            recorded = replace(snapshot, lam=1.0)
            view = _full_view(result, [*definitions, current], [*snapshots, recorded])
            row = contact_stage_equilibrium(view, index, **options)
            about_origin = total.copy()
            about_origin[2] += -options["origin"][0]*total[1] + options["origin"][1]*total[0]
            row["checks"]["analytical_applied_history_resultant"] = _criterion(
                np.asarray(row["external_resultant"]) - about_origin, np.abs(about_origin),
                np.array([force_atol, force_atol, moment_atol]), rtol,
            )
            row["load_history"] = {
                "accepted_fraction": observed, "declared_fraction": alpha,
                "previous_applied_resultant_about_global_zero": previous_resultant.tolist(),
                "target_resultant_about_global_zero": np.asarray(target["resultant"]).tolist(),
                "actual_applied_resultant_about_global_zero": total.tolist(),
                "previous_load_weight": 1 - alpha,
                "retained_release": "zero by fixed activity and prescribed-DOF contract",
            }
            row["scope"] = _SCOPE
            if any(c["status"] not in ("passed", "not_applicable")
                   for c in row["checks"].values()):
                row["status"] = "failed"
            if row["status"] == "passed":
                previous, previous_resultant = applied, total
                definitions.append(current)
                snapshots.append(recorded)
        except UnsupportedContactBudget as exc:
            row = {"stage_index": index, "stage": snapshot.name,
                   "status": "unsupported", "reason": str(exc)}
        except _ERRORS as exc:
            row = {"stage_index": index, "stage": snapshot.name,
                   "status": "invalid", "reason": str(exc)}
        rows.append(row)
        if row["status"] != "passed":
            failed_index = index
    return {"status": "passed" if rows and failed_index is None else "failed",
            "initial_status": initial_status, "stage_count": len(rows),
            "stages": rows, "scope": _SCOPE}
