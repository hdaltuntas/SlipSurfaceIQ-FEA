"""Native monotone excavation of a three-layer elastic normal-contact specimen.

This is a fixture-specific independent reference, NOT a general excavation audit.
The lower two layers share nodes; their upper face contacts a separately supported
upper layer. Removing the middle layer deletes loaded nodes and automatically disables
the interface. Remaining stresses relax through partial stages. All targets follow
scalar elasticity and the original geometry, not the native assembled residual.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle

WIDTH = 2.0
C = 2400.0  # constrained modulus for E=2000 kPa, nu=0.25
NU = 0.25
KN = 2000.0
FRACTIONS = (1.0, 0.5, 0.25, 0.5, 1.0, 0.4, 0.5, 1.0)
REGIONS = ({1, 2, 3}, {1, 2, 3}, {1, 3}, {1, 3}, {1, 3}, {3}, {3}, {3})
TOPS = (-0.012, -0.010, -0.008, 0.004, 0.006, -0.003, 0.004, 0.002)
UPPER_FORCES = (-12.0, -16.0, -10.0, -8.0, 4.0, -12.0, 6.0, 0.0)
LOWER_FORCES = (-4.0, -6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def build_model(
    *, element_type="IFACE4", initial_gap=0.0, quarter_turn=False, mode="mixed", columns=2
):
    if (
        not isinstance(quarter_turn, bool)
        or isinstance(initial_gap, bool)
        or not math.isfinite(initial_gap)
        or initial_gap < 0
    ):
        raise ValueError("Invalid frame or initial clearance")
    if (
        element_type not in ("IFACE4", "IFACE6")
        or mode not in ("force", "displacement", "mixed")
        or columns not in (1, 2, 4)
        or isinstance(columns, bool)
    ):
        raise ValueError("Unsupported fixture type, mode or mesh")
    etype = api.ElemType.Q4 if element_type == "IFACE4" else api.ElemType.Q8
    lower = rectangle(WIDTH, 2.0, columns, 2, etype=etype)
    upper = rectangle(WIDTH, 1.0, columns, 1, etype=etype)
    lc = lower.coords.copy()
    lc[:, 1] -= 2.0
    n = lower.nn
    local = np.vstack([lc, upper.coords])
    rotation = np.array([[0.0, -1.0], [1.0, 0.0]]) if quarter_turn else np.eye(2)
    shift = np.array([3.25, -2.5])
    coords = local @ rotation.T + shift
    lower_block = lower.blocks[0]
    centers = lc[lower_block.conn[:, :4], 1].mean(axis=1)
    region = np.where(centers < -1.0, 1, 2)
    low_face = lower.nodes("top")
    high_face = upper.nodes("bottom")
    low_face = low_face[np.argsort(lower.coords[low_face, 0])]
    high_face = high_face[np.argsort(upper.coords[high_face, 0])]
    partners = dict(zip(high_face, low_face))
    edges = upper.edges("bottom").copy()
    for edge in edges:
        if upper.coords[edge[1], 0] < upper.coords[edge[0], 0]:
            edge[:2] = edge[:2][::-1]
    contact = api.ElementBlock(
        api.ElemType[element_type],
        np.array([[*[partners[int(k)] for k in edge], *(edge + n)] for edge in edges]),
        np.zeros(len(edges), dtype=int),
        "contact",
    )
    blocks = (
        replace(lower_block, region=region, tag="lower"),
        replace(
            upper.blocks[0],
            conn=upper.blocks[0].conn + n,
            region=np.full(upper.blocks[0].ne, 3),
            tag="upper",
        ),
        contact,
    )
    nodes = {
        "all": np.arange(len(coords)),
        "base": lower.nodes("bottom"),
        "top": upper.nodes("top") + n,
        "lower_contact": low_face,
        "upper_contact": high_face + n,
    }
    mesh = api.Mesh(coords, blocks, nodes)
    normal = rotation @ np.array([0.0, 1.0])
    targets = []
    stages = []
    weights = np.array([0.5, 0.5] if element_type == "IFACE4" else [1 / 6, 1 / 6, 2 / 3])
    for i, alpha in enumerate(FRACTIONS):
        f1 = LOWER_FORCES[i] if mode != "displacement" else 0.0
        f2 = UPPER_FORCES[i] if mode != "displacement" else 0.0
        top = TOPS[i] if mode != "force" else 0.0
        loads = []
        for edge in edges:
            for node, weight in zip(edge, weights):
                for actual_node, force in ((int(node + n), f2), (int(partners[int(node)]), f1)):
                    if force:
                        value = force / columns * weight * normal
                        loads.append(
                            api.PointLoad(actual_node, fx=float(value[0]), fy=float(value[1]))
                        )
        disp = api.Displacement("top", ux=-top) if quarter_turn else api.Displacement("top", uy=top)
        stages.append(
            api.Stage(
                "excavation" if i in (2, 3) else f"stage_{i}",
                active_regions=REGIONS[i],
                active_structures={"contact"},
                load_split=alpha,
                loads=tuple(loads),
                displacements=(disp,),
                reset_displacements=i in (2, 3, 5),
            )
        )
        targets.append((f1 / WIDTH, f2 / WIDTH, top))
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 2000.0, NU)},
        region_material={1: "soil", 2: "soil", 3: "soil"},
        initial=api.InitialStress("none"),
        fixities=(
            api.Fixity("all", not quarter_turn, quarter_turn),
            api.Fixity("base", True, True),
            api.Fixity("top", quarter_turn, not quarter_turn),
        ),
        interfaces={
            "contact": api.InterfaceSpec.unilateral_normal("contact", KN, initial_gap=initial_gap)
        },
        settings=api.SolverSettings(
            dlam0=1.0,
            dlam_max=1.0,
            max_iter=40,
            tol_force=1e-10,
            tol_energy=1e-10,
            linear_solver="splu",
        ),
        stages=stages,
    )
    return model, {
        "local_coords": local,
        "rotation": rotation,
        "normal": normal,
        "targets": targets,
    }


def reference(initial_gap, targets):
    """Scalar layer/contact force balance, with no native solution as input.

    Positive traction is tension. Before removal: a=2*(q1+h1+t)/C,
    b=v+(q2+h2-t)/C. After removing region 2, the contact and its lower
    loaded nodes disappear; its previous load is dropped, not interpolated
    onto any surviving node. Remaining region-1 stress is retained independently.
    """
    s1 = s3 = a = b = v = q1 = q2 = 0.0
    rows = []
    for i, (alpha, (target1, target2, vt)) in enumerate(zip(FRACTIONS, targets)):
        q1prev = q1 if 2 in REGIONS[i] else 0.0
        q1 = (1 - alpha) * q1prev + alpha * target1
        q2new = (1 - alpha) * q2 + alpha * target2
        vnew = (1 - alpha) * v + alpha * vt
        on = 2 in REGIONS[i]
        t0 = KN * min(initial_gap + b - a, 0.0) if on else 0.0
        h1 = (1 - alpha) * (s1 - t0 - q1prev) if 1 in REGIONS[i] else 0.0
        h3 = (1 - alpha) * (-s3 + t0 - q2)
        if on:
            t = min(
                0.0,
                KN * (initial_gap + vnew + (q2new + h3) / C - 2 * (q1 + h1) / C) / (1 + 3 * KN / C),
            )
            s1new, s3new = q1 + h1 + t, t - q2new - h3
            a, b = 2 * s1new / C, vnew - s3new / C
        else:
            t = 0.0
            s1new = h1 if 1 in REGIONS[i] else 0.0
            s3new = -q2new - h3
            b = vnew - s3new / C
        rows.append(
            dict(
                lower_stress=s1new,
                upper_stress=s3new,
                top_u=vnew,
                upper_u=b,
                traction=t,
                gap=initial_gap + b - a if on else None,
                lower_release=WIDTH * h1,
                upper_release=WIDTH * h3,
                physical_load=WIDTH * (q1 + q2new),
                base_reaction=-WIDTH * s1new,
                top_reaction=WIDTH * s3new,
            )
        )
        s1, s3, v, q2 = s1new, s3new, vnew, q2new
    return rows


def _check(actual, expected, atol):
    actual = np.asarray(actual)
    target = np.broadcast_to(np.asarray(expected), actual.shape)
    finite = bool(np.isfinite(actual).all() and np.isfinite(target).all())
    error = (
        float(np.max(np.abs(actual.astype(float) - target.astype(float)), initial=0))
        if finite
        else None
    )
    return {
        "status": "passed" if finite and error <= atol else "failed",
        "maximum_absolute_error": error,
        "absolute_tolerance": atol,
    }


def _surface_internal(model, fixture, target, regions):
    """Exact constant-stress boundary integrals, without native kernels/weights.

    Every quadrilateral side has constant sigma*n and linear/quadratic shape
    functions. Integrals are L*(1/2,1/2) or L*(1/6,1/6,2/3). Opposite shared
    sides cancel algebraically, including on the newly exposed excavation face.
    """
    force = np.zeros((model.mesh.nn, 2))
    rotation = fixture["rotation"]
    for block in model.mesh.continuum_blocks():
        stress = target["lower_stress"] if block.tag == "lower" else target["upper_stress"]
        sigma = rotation @ np.diag([NU / (1 - NU) * stress, stress]) @ rotation.T
        for conn in block.conn[np.isin(block.region, list(regions))]:
            for j in range(4):
                edge = [conn[j], conn[(j + 1) % 4]]
                if len(conn) == 8:
                    edge.append(conn[j + 4])
                xy = model.mesh.coords[edge[:2]]
                tangent = xy[1] - xy[0]
                outward_length = np.array([tangent[1], -tangent[0]])
                resultant = sigma @ outward_length
                weights = [0.5, 0.5] if len(edge) == 2 else [1 / 6, 1 / 6, 2 / 3]
                np.add.at(force, edge, np.asarray(weights)[:, None] * resultant)
    if 2 in regions:
        block = model.mesh.block("contact")
        n = block.etype.nen // 2
        for conn in block.conn:
            length = float(np.linalg.norm(model.mesh.coords[conn[1]] - model.mesh.coords[conn[0]]))
            weights = np.array([0.5, 0.5] if n == 2 else [1 / 6, 1 / 6, 2 / 3]) * length
            contribution = weights[:, None] * target["traction"] * fixture["normal"]
            np.add.at(force, conn[:n], -contribution)
            np.add.at(force, conn[n:], contribution)
    return force


def _totals(coords, forces):
    # A separate first-moment calculation; no native moment or resultant utility.
    return np.array(
        [
            math.fsum(forces[:, 0]),
            math.fsum(forces[:, 1]),
            math.fsum(coords[:, 0] * forces[:, 1] - coords[:, 1] * forces[:, 0]),
        ]
    )


def evaluate(result, model, fixture):
    """Evaluate ONLY the generated fixture; do not expose as a general model audit."""
    if len(model.stages) != len(FRACTIONS) or len(result.stages) != len(FRACTIONS):
        raise ValueError("Incomplete or extra native stage snapshots")
    if any(
        snapshot.name != definition.name
        for definition, snapshot in zip(model.stages, result.stages)
    ):
        raise ValueError("Native stage identity mismatch")
    expected_tags = {b.tag for b in model.mesh.blocks}
    for snapshot in [result.initial, *result.stages]:
        if (
            set(snapshot.active) != expected_tags
            or set(snapshot.sig) != {"lower", "upper"}
            or any(
                set(getattr(snapshot, name)) != {"contact"}
                for name in ("interfaces", "contact_gap", "contact_status")
            )
        ):
            raise ValueError("Missing or unexpected native result maps")
        if np.asarray(snapshot.u).shape != (model.mesh.nn, 2):
            raise ValueError("Invalid displacement dimensions")
        if (
            np.asarray(snapshot.reactions).shape != (model.mesh.nn, 3)
            or not np.isfinite(snapshot.reactions).all()
        ):
            raise ValueError("Invalid reaction dimensions")
        if (
            isinstance(snapshot.lam, (bool, np.bool_))
            or not isinstance(snapshot.lam, (int, float, np.floating))
            or not math.isfinite(snapshot.lam)
        ):
            raise ValueError("Invalid accepted stage fraction")
        for block in model.mesh.blocks:
            mask = np.asarray(snapshot.active[block.tag])
            if mask.shape != (block.ne,) or mask.dtype.kind != "b":
                raise ValueError("Invalid activity dimensions/type")
            if block.tag != "contact":
                stress = np.asarray(snapshot.sig[block.tag])
                ngp = 4  # repository default 2x2 quadrature for these Q4/Q8 fixtures
                if stress.shape != (block.ne, ngp, 4):
                    raise ValueError("Invalid stored stress dimensions")
        contact = model.mesh.block("contact")
        shape = (contact.ne, contact.etype.nen // 2)
        if (
            np.asarray(snapshot.contact_gap["contact"]).shape != shape
            or np.asarray(snapshot.contact_status["contact"]).shape != shape
            or np.asarray(snapshot.interfaces["contact"]).shape != (*shape, 2)
        ):
            raise ValueError("Invalid contact result dimensions")
    expected_initial_status = 1 if model.interfaces["contact"].initial_gap == 0 else 0
    if (
        result.initial.lam != 1.0
        or np.any(result.initial.contact_status["contact"] != expected_initial_status)
        or any(not np.all(m) for m in result.initial.active.values())
        or np.any(result.initial.u != 0)
        or np.any(result.initial.reactions != 0)
        or any(np.any(s != 0) for s in result.initial.sig.values())
        or np.any(result.initial.interfaces["contact"] != 0)
        or np.any(result.initial.contact_gap["contact"] != model.interfaces["contact"].initial_gap)
    ):
        raise ValueError("Invalid stress-free initial evidence")

    exact = reference(model.interfaces["contact"].initial_gap, fixture["targets"])
    normal, rotation = fixture["normal"], fixture["rotation"]
    local = fixture["local_coords"]
    previous_u = np.zeros_like(result.initial.u)
    datum = previous_u.copy()
    rows = []
    previous_load = np.zeros_like(previous_u)
    for i, (definition, snapshot, target) in enumerate(zip(model.stages, result.stages, exact)):
        used = np.zeros(model.mesh.nn, dtype=bool)
        checks = {}
        for block in model.mesh.continuum_blocks():
            expected_active = np.isin(block.region, list(REGIONS[i]))
            used[block.conn[expected_active].ravel()] = True
            checks[block.tag + "_activity"] = _check(
                snapshot.active[block.tag], expected_active, 0.0
            )
            stress = target["lower_stress"] if block.tag == "lower" else target["upper_stress"]
            transverse = NU / (1 - NU) * stress
            tensor = rotation @ np.diag([transverse, stress]) @ rotation.T
            expected_stress = [tensor[0, 0], tensor[1, 1], transverse, tensor[0, 1]]
            checks[block.tag + "_stress_kpa"] = _check(
                snapshot.sig[block.tag][expected_active],
                expected_stress,
                1e-8,
            )
            checks[block.tag + "_removed_stress_zero"] = _check(
                snapshot.sig[block.tag][~expected_active],
                0.0,
                0.0,
            )
        checks["automatic_contact_activity"] = _check(snapshot.active["contact"], i < 2, 0.0)
        if not np.isfinite(snapshot.u[used]).all():
            raise ValueError("Nonfinite active displacement")
        checks["inactive_displacement_is_nan"] = {
            "status": "passed" if np.isnan(snapshot.u[~used]).all() else "failed",
        }
        if definition.reset_displacements:
            datum = previous_u.copy()
        total = snapshot.u + datum
        u_expected = np.zeros_like(total)
        # y=0 lower-contact nodes must be distinguished from coincident upper nodes.
        upper_ids = np.unique(model.mesh.block("upper").conn)
        lower_ids = np.setdiff1d(np.flatnonzero(used), upper_ids)
        u_expected[lower_ids] = (
            (local[lower_ids, 1] + 2)[:, None] * (target["lower_stress"] / C) * normal
        )
        u_expected[upper_ids] = (
            target["top_u"] + (local[upper_ids, 1] - 1) * target["upper_stress"] / C
        )[:, None] * normal
        checks["total_displacement_m"] = _check(total[used], u_expected[used], 1e-10)
        for label, node_set in (("base", "base"), ("top", "top")):
            checks[label + "_reaction_kn_per_m"] = _check(
                snapshot.reactions[model.mesh.nodes(node_set), :2].sum(axis=0) @ normal,
                target[label + "_reaction"],
                1e-8,
            )
        checks["inactive_reactions_zero"] = _check(snapshot.reactions[~used], 0.0, 0.0)
        expected_internal = _surface_internal(model, fixture, target, REGIONS[i])
        target_nodal = np.zeros_like(previous_load)
        for load in definition.loads:
            target_nodal[load.node] += [load.fx, load.fy]
        projected_previous = previous_load.copy()
        projected_previous[~used] = 0.0
        physical_nodal = (1 - FRACTIONS[i]) * projected_previous + FRACTIONS[i] * target_nodal
        prescribed = np.zeros_like(previous_load, dtype=bool)
        for fix in model.fixities:
            prescribed[model.mesh.nodes(fix.node_set)] |= [fix.ux, fix.uy]
        prescribed &= used[:, None]
        expected_reaction = np.where(prescribed, expected_internal - physical_nodal, 0.0)
        checks["all_nodal_reactions_kn_per_m"] = _check(
            snapshot.reactions[:, :2],
            expected_reaction,
            1e-8,
        )
        checks["rotation_reaction_zero"] = _check(snapshot.reactions[:, 2], 0.0, 0.0)
        retained_nodal = np.where(prescribed, 0.0, expected_internal - physical_nodal)
        physical_residual = expected_internal - physical_nodal - snapshot.reactions[:, :2]
        checks["projected_load_history_kn_per_m"] = _check(
            physical_nodal.sum(axis=0) @ normal,
            target["physical_load"],
            1e-8,
        )
        checks["global_force_moment"] = _check(
            _totals(model.mesh.coords, physical_nodal + retained_nodal + snapshot.reactions[:, :2]),
            np.zeros(3),
            1e-8,
        )
        previous_load = physical_nodal
        if i < 2:
            checks["gap_m"] = _check(snapshot.contact_gap["contact"], target["gap"], 1e-10)
            checks["traction_kpa"] = _check(
                snapshot.interfaces["contact"], [0, target["traction"]], 1e-8
            )
            expected_status = 2 if target["gap"] < 0 else 0 if target["gap"] > 0 else 1
            checks["contact_status"] = _check(
                snapshot.contact_status["contact"], expected_status, 0
            )
        else:
            checks["inactive_contact_evidence"] = {
                "status": "passed"
                if (
                    np.isnan(snapshot.contact_gap["contact"]).all()
                    and np.isnan(snapshot.interfaces["contact"]).all()
                    and np.all(snapshot.contact_status["contact"] == 255)
                )
                else "failed"
            }
        external = target["physical_load"]
        release = target["lower_release"] + target["upper_release"]
        reaction = float(snapshot.reactions[:, :2].sum(axis=0) @ normal)
        checks["transition_global_force_kn_per_m"] = _check(external + release + reaction, 0, 1e-8)
        checks["accepted_fraction"] = _check(snapshot.lam, FRACTIONS[i], 0.0)
        rows.append(
            {
                "stage_index": i,
                "stage": snapshot.name,
                "status": "passed"
                if all(c["status"] == "passed" for c in checks.values())
                else "failed",
                "checks": checks,
                "reference": target,
                "active_nodes": int(used.sum()),
                "inactive_nodes": int((~used).sum()),
                "physical_force_residual_kn_per_m": external + reaction,
                "physical_only_equilibrium": bool(np.max(np.abs(physical_residual)) <= 1e-8),
                "physical_nodal_residual_max": float(np.max(np.abs(physical_residual))),
                "retained_nodal_reference": retained_nodal.tolist(),
                "projected_physical_nodal_reference": physical_nodal.tolist(),
            }
        )
        previous_u[used] = total[used]
    return {
        "status": "passed"
        if len(rows) == len(FRACTIONS) and all(r["status"] == "passed" for r in rows)
        else "failed",
        "stage_count": len(rows),
        "stages": rows,
    }


def run_case(**kwargs):
    model, fixture = build_model(**kwargs)
    try:
        result = api.run(model)
        report = evaluate(result, model, fixture)
    except (ValueError, KeyError, IndexError, TypeError, OverflowError, FloatingPointError) as exc:
        report = {"status": "failed", "reason": str(exc), "stage_count": 0, "stages": []}
    return {**report, "fixture": kwargs}


def run_benchmark():
    cases = [
        run_case(element_type=e, initial_gap=g, quarter_turn=q, mode=m)
        for e in ("IFACE4", "IFACE6")
        for g in (0.0, 0.002)
        for q in (False, True)
        for m in ("force", "displacement", "mixed")
    ]
    return {
        "status": "passed" if all(c["status"] == "passed" for c in cases) else "failed",
        "native_solver": "api.run / StaticSolver",
        "case_count": len(cases),
        "stage_count": sum(c["stage_count"] for c in cases),
        "cases": cases,
        "scope": "Exact elastic layered monotone-removal fixtures only. Not a general "
        "excavation audit, nonlinear soil/beam/pile benchmark or restart.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--example", type=Path, help="Save a solved IFACE6 mixed-control project")
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.example and report["status"] == "passed":
        model, fixture = build_model(element_type="IFACE6", initial_gap=0.002, mode="mixed")
        result = api.run(model)
        if evaluate(result, model, fixture)["status"] != "passed":
            raise ValueError("Example failed independent checks")
        args.example.parent.mkdir(parents=True, exist_ok=True)
        api.save_project(model, args.example, result)
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
