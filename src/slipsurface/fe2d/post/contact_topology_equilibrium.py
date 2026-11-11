"""Read-only elastic contact audit with changing continuum topology.

Reconstruct activity, displacement datums, physical loads and retained release
from Model + accepted snapshots. Never consult StaticSolver, its private state,
contact groups, native residuals or fixture-specific layer formulas. Continuum
shape derivatives/quadrature ARE shared with the library (not a second solver).
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np

from ..core.errors import MeshError
from .contact_activation_equilibrium import _prescribed_targets
from .contact_equilibrium import UnsupportedContactBudget, _criterion, _resultant
from .contact_partial_equilibrium import _ERRORS, _fraction, _prescribed
from .contact_resultants import moment_origin
from .contact_results import contact_points
from .contact_topology import _balance, _Context
from .dry_applied_loads import independent_dry_applied_loads

_AUDIT_ERRORS = (*_ERRORS, MeshError)
_SCOPE = (
    "Snapshot-derived dry elastic plane-strain normal-contact audit on the original mesh. "
    "Stress-free zero-gravity initialization; element removal/rebirth and axis-aligned "
    "temporary restraints allowed. Physical loads and retained release remain separate. "
    "No nonlinear soil, deposition/remeshing, water, friction, beams/bars, restart, "
    "capacity or independent software certification. Continuum quadrature is shared."
)


def contact_topology_equilibrium_by_stage(
    result,
    *,
    origin=(0.0, 0.0),
    force_atol=1e-8,
    moment_atol=1e-8,
    traction_atol=1e-8,
    gap_atol=1e-10,
    rtol=1e-8,
):
    """Check a COMPLETE accepted elastic history, including birth/removal and release.

    Original APIs retain their rejection of topology changes. This separate API
    fails closed on invalid, unsupported or failed predecessor records. Passing
    transition balance is NOT passing physical-only balance or engineering safety.
    """
    origin = moment_origin(origin)
    for tolerance in (force_atol, moment_atol, traction_atol, gap_atol, rtol):
        if (
            isinstance(tolerance, (bool, np.bool_))
            or not isinstance(tolerance, Real)
            or not math.isfinite(tolerance)
            or tolerance <= 0
        ):
            raise ValueError("Tolerances must be positive finite real values")
    rows, failed = [], None
    initial_status = "invalid"
    try:
        model = result.model
        if not model.stages or len(model.stages) != len(result.stages):
            raise ValueError("Complete matching stage history required")
        ctx = _Context(model)
        previous_active, previous_used = ctx.activity(model.initial)
        u0, r0 = ctx.snapshot(result, result.initial, previous_active, previous_used)
        if (
            _fraction(result.initial.lam, "Initial load factor") != 1
            or np.any(r0 != 0)
            or np.any(u0[previous_used] != 0)
            or any(np.any(s != 0) for s in result.initial.sig.values())
        ):
            raise ValueError("Initial evidence must have zero displacement, stress and reaction")
        for p in contact_points(result, result.initial):
            if p.active and (
                p.gap_m != model.interfaces[p.tag].initial_gap or p.normal_traction_kpa != 0
            ):
                raise ValueError("Initial contact differs from original unloaded geometry")
        total = np.zeros((ctx.mesh.nn, 2))
        datum, physical = np.zeros_like(total), np.zeros_like(total)
        previous = result.initial
        initial_status = "passed"
    except _AUDIT_ERRORS as exc:
        status = "unsupported" if isinstance(exc, UnsupportedContactBudget) else "invalid"
        return {
            "status": "failed",
            "initial_status": status,
            "reason": str(exc),
            "scope": _SCOPE,
            "stage_count": len(result.stages),
            "stages": [
                {
                    "stage_index": i,
                    "stage": st.name,
                    "status": "blocked",
                    "reason": "Invalid/unsupported initial reference",
                }
                for i, st in enumerate(result.stages)
            ],
        }
    for i, (definition, snapshot) in enumerate(zip(model.stages, result.stages)):
        if failed is not None:
            rows.append(
                {
                    "stage_index": i,
                    "stage": snapshot.name,
                    "status": "blocked",
                    "blocked_by_stage_index": failed,
                }
            )
            continue
        try:
            alpha = _fraction(definition.load_split, "Declared fraction")
            if (
                _fraction(snapshot.lam, "Accepted fraction") != alpha
                or definition.name != snapshot.name
            ):
                raise ValueError("Stage identity/fraction mismatch")
            if not isinstance(definition.reset_displacements, (bool, np.bool_)):
                raise ValueError("Reporting reset must be boolean")
            active, used = ctx.activity(definition)
            reported, reaction = ctx.snapshot(result, snapshot, active, used)
            fresh, removed = used & ~previous_used, previous_used & ~used
            current_datum = datum.copy()
            current_datum[fresh] = total[fresh]
            if definition.reset_displacements:
                current_datum[:] = total
            current = total.copy()
            current[used] = reported[used] + current_datum[used]
            prescribed = _prescribed(model, definition.displacements) & used[:, None]
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                predicted, start_stress = ctx.elastic_prediction(
                    previous.sig, previous_active, active, current - total
                )
                soil_start = ctx.soil_force(start_stress, active)
                contact_start, _ = ctx.contact_force(total, active)
                projected = physical.copy()
                projected[~used] = 0.0
                target = independent_dry_applied_loads(model, definition, active)
                actual = (1 - alpha) * projected + alpha * target["nodal"][:, :2]
                retained = (1 - alpha) * (soil_start + contact_start - projected)
                retained[prescribed | ~used[:, None]] = 0.0
                soil = ctx.soil_force(snapshot.sig, active)
                contact, gaps = ctx.contact_force(current, active, snapshot)
                effective = _balance(
                    ctx,
                    soil,
                    contact,
                    actual + retained,
                    reaction[:, :2],
                    active,
                    used,
                    origin,
                    force_atol,
                    moment_atol,
                    rtol,
                )
                physical_row = _balance(
                    ctx,
                    soil,
                    contact,
                    actual,
                    reaction[:, :2],
                    active,
                    used,
                    origin,
                    force_atol,
                    moment_atol,
                    rtol,
                )
                checks = {
                    "no_free_or_removed_reaction": _criterion(
                        reaction[:, :2][~prescribed],
                        np.zeros(np.count_nonzero(~prescribed)),
                        force_atol,
                        rtol,
                    ),
                    "no_rotational_reaction": _criterion(
                        reaction[:, 2], np.zeros(ctx.mesh.nn), moment_atol, rtol
                    ),
                    "prescribed_displacement_history": _criterion(
                        (
                            current
                            - ((1 - alpha) * total + alpha * _prescribed_targets(model, definition))
                        )[prescribed],
                        np.abs(current[prescribed]),
                        gap_atol,
                        rtol,
                    ),
                }
                for b in ctx.bulk:
                    checks[f"elastic_stress_history:{b.tag}"] = _criterion(
                        snapshot.sig[b.tag] - predicted[b.tag],
                        np.abs(predicted[b.tag]),
                        traction_atol,
                        rtol,
                    )
                gap_error, gap_scale, traction_error, traction_scale = [], [], [], []
                for p in contact_points(result, snapshot):
                    if p.active:
                        gap = gaps[p.tag][p.element, p.point]
                        traction = model.interfaces[p.tag].kn * min(gap, 0.0)
                        gap_error.append(p.gap_m - gap)
                        gap_scale.append(abs(gap))
                        traction_error.append(p.normal_traction_kpa - traction)
                        traction_scale.append(abs(traction))
                checks["original_reference_gap"] = _criterion(gap_error, gap_scale, gap_atol, rtol)
                checks["geometric_contact_pressure"] = _criterion(
                    traction_error, traction_scale, traction_atol, rtol
                )
                if not gap_error:
                    checks["original_reference_gap"] = {
                        "status": "not_applicable",
                        "reason": "All contact elements inactive",
                    }
                    checks["geometric_contact_pressure"] = {
                        "status": "not_applicable",
                        "reason": "All contact elements inactive",
                    }
                target_total = np.array(target["resultant"], dtype=float)
                target_total[2] += -origin[0] * target_total[1] + origin[1] * target_total[0]
                expected_total = (1 - alpha) * (
                    _resultant(ctx.xy, physical, origin)
                    - _resultant(ctx.xy[removed], physical[removed], origin)
                )
                expected_total += alpha * target_total
                checks["physical_load_history_resultant"] = _criterion(
                    _resultant(ctx.xy, actual, origin) - expected_total,
                    np.abs(expected_total),
                    [force_atol, force_atol, moment_atol],
                    rtol,
                )
                passed = effective["status"] == "passed" and all(
                    c["status"] in ("passed", "not_applicable") for c in checks.values()
                )
                row = {
                    "stage_index": i,
                    "stage": snapshot.name,
                    "accepted_fraction": alpha,
                    "status": "passed" if passed else "failed",
                    "checks": checks,
                    "transition_equilibrium": effective,
                    "physical_equilibrium": physical_row,
                    "topology": {
                        "removed_nodes": np.flatnonzero(removed).tolist(),
                        "reactivated_nodes": np.flatnonzero(fresh).tolist(),
                        "active_elements": {k: int(v.sum()) for k, v in active.items()},
                    },
                    "history": {
                        "physical_nodal": actual.tolist(),
                        "retained_release_nodal": retained.tolist(),
                        "dropped_previous_load_resultant": _resultant(
                            ctx.xy[removed], physical[removed], origin
                        ).tolist(),
                        "retained_release_resultant": _resultant(ctx.xy, retained, origin).tolist(),
                    },
                }
                if passed:
                    physical, total, datum = actual, current, current_datum
                    previous_active, previous_used, previous = active, used, snapshot
        except _AUDIT_ERRORS as exc:
            row = {
                "stage_index": i,
                "stage": snapshot.name,
                "status": "unsupported" if isinstance(exc, UnsupportedContactBudget) else "invalid",
                "reason": str(exc),
            }
        rows.append(row)
        if row["status"] != "passed":
            failed = i
    return {
        "status": "passed" if failed is None else "failed",
        "initial_status": initial_status,
        "stage_count": len(rows),
        "stages": rows,
        "scope": _SCOPE,
        "tolerances": {
            "force_atol": force_atol,
            "moment_atol": moment_atol,
            "traction_atol": traction_atol,
            "gap_atol": gap_atol,
            "rtol": rtol,
        },
    }
