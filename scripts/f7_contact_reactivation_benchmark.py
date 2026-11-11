"""Exact dry elastic layer removal/rebirth fixture; not a general backfill audit.

Newly active continuum is stress-free in incremental strain, while inactive nodes
retain their total positions. Contact uses the ORIGINAL geometric gap. Reporting
resets and fresh-node datums are tracked separately by the independent reference.
Only mesh construction is shared with the monotone-excavation fixture.
"""

from __future__ import annotations

import argparse
import json
import math
import runpy
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import SlipSurfaceError

_BASE = runpy.run_path(str(Path(__file__).with_name("f7_contact_excavation_benchmark.py")))
C, KN, NU, WIDTH = 2400.0, 2000.0, 0.25, 2.0
FRACTIONS = (1.0, 0.5, 0.25, 0.5, 0.5, 0.4, 1.0, 0.5, 0.25, 1.0, 0.5, 0.5, 0.4, 1.0)
REGIONS = (
    {1, 2, 3},
    {1, 2, 3},
    {1, 3},
    {1, 3},
    {1, 3},
    {3},
    {3},
    {1, 3},
    {1, 2, 3},
    {1, 2, 3},
    {1, 3},
    {1, 2, 3},
    {1, 2, 3},
    {1, 2, 3},
)
TOPS = (
    -0.012,
    -0.010,
    -0.008,
    0.004,
    0.006,
    -0.003,
    0.004,
    0.004,
    -0.006,
    -0.020,
    0.010,
    0.006,
    0.010,
    -0.018,
)
LOWER_FORCES = (-4.0, -6.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -2.0, -4.0, 0.0, 0.0, 0.0, -2.0)
UPPER_FORCES = (-12.0, -16.0, -10.0, -8.0, 4.0, -12.0, 6.0, 6.0, -8.0, -14.0, 6.0, 0.0, 6.0, -8.0)
RESETS = frozenset({2, 5, 7, 8, 11, 12})


def build_model(
    *,
    element_type="IFACE4",
    initial_gap=0.0,
    quarter_turn=False,
    mode="mixed",
    columns=2,
    reporting_resets=True,
):
    """Three one-metre layers, repeated removal/rebirth and automatic contact activity."""
    if not isinstance(reporting_resets, bool):
        raise ValueError("reporting_resets must be boolean")
    model, fixture = _BASE["build_model"](
        element_type=element_type,
        initial_gap=initial_gap,
        quarter_turn=quarter_turn,
        mode=mode,
        columns=columns,
    )
    contact = model.mesh.block("contact")
    n = contact.etype.nen // 2
    weights = np.array([0.5, 0.5] if n == 2 else [1 / 6, 1 / 6, 2 / 3])
    normal = fixture["normal"]
    stages, targets = [], []
    for i, alpha in enumerate(FRACTIONS):
        f1, f2 = (LOWER_FORCES[i], UPPER_FORCES[i]) if mode != "displacement" else (0.0, 0.0)
        top = TOPS[i] if mode != "force" else 0.0
        loads = []
        for conn in contact.conn:
            for force, face in ((f1, conn[:n]), (f2, conn[n:])):
                for node, weight in zip(face, weights):
                    if force:
                        vector = force / columns * weight * normal
                        loads.append(
                            api.PointLoad(int(node), fx=float(vector[0]), fy=float(vector[1]))
                        )
        prescribed = (
            api.Displacement("top", ux=-top) if quarter_turn else api.Displacement("top", uy=top)
        )
        stages.append(
            api.Stage(
                "rebirth" if i in (7, 8, 11) else f"stage_{i}",
                active_regions=REGIONS[i],
                active_structures={"contact"},
                loads=tuple(loads),
                displacements=(prescribed,),
                load_split=alpha,
                reset_displacements=reporting_resets and i in RESETS,
            )
        )
        targets.append((f1 / WIDTH, f2 / WIDTH, top))
    model.stages = stages
    fixture["targets"] = targets
    fixture["reporting_resets"] = reporting_resets
    return model, fixture


def reference(initial_gap, targets):
    """Scalar elimination, independent of native groups, stiffness and stored results.

    levels=(u1,u2,b,v): lower shared face, lower contact, upper contact, top.
    Current-active initial stresses are old stresses for survivors, zero for rebirth.
    r=q+h; with both lower layers active s2=t+r2, s1=s2+r1, s3=t-r3.
    A=u2_old+(r1+2*r2-s1_start-s2_start)/C;
    B=b_old+(v-v_old)+(s3_start+r3)/C;
    t=min(0,kn*(g0+B-A)/(1+3*kn/C)). No matrix solve is used.
    """
    if (
        isinstance(initial_gap, bool)
        or not math.isfinite(initial_gap)
        or initial_gap < 0
        or len(targets) != len(FRACTIONS)
    ):
        raise ValueError("Invalid initial gap or target history")
    if any(len(t) != 3 or not all(math.isfinite(x) for x in t) for t in targets):
        raise ValueError("Finite three-component stage targets required")
    stress, levels, loads = np.zeros(3), np.zeros(4), np.zeros(3)
    previous_regions = {1, 2, 3}
    rows = []
    for alpha, regions, (f2, f3, vt) in zip(FRACTIONS, REGIONS, targets):
        if 2 not in regions and f2 != 0:
            raise ValueError("Targets must not load removed contact-face nodes")
        start = np.array(
            [stress[j] if j + 1 in regions & previous_regions else 0.0 for j in range(3)]
        )
        previous_load = loads.copy()
        previous_load[:2] *= [1 in regions, 2 in regions]
        loads = (1 - alpha) * previous_load + alpha * np.array([0.0, f2, f3])
        top = (1 - alpha) * levels[3] + alpha * vt
        t0 = KN * min(initial_gap + levels[2] - levels[1], 0.0) if 2 in regions else 0.0
        i0 = np.array([start[0] - start[1], start[1] - t0, -start[2] + t0])
        retained = (1 - alpha) * (i0 - previous_load)
        retained[:2] *= [1 in regions, 2 in regions]
        effective = loads + retained
        updated = levels.copy()
        b0 = levels[2] + top - levels[3] + (start[2] + effective[2]) / C
        if 2 in regions:
            a0 = levels[1] + (effective[0] + 2 * effective[1] - start[0] - start[1]) / C
            traction = min(0.0, KN * (initial_gap + b0 - a0) / (1 + 3 * KN / C))
            stress = np.array(
                [
                    traction + effective[0] + effective[1],
                    traction + effective[1],
                    traction - effective[2],
                ]
            )
            updated[0] += (stress[0] - start[0]) / C
            updated[1] += (stress[0] - start[0] + stress[1] - start[1]) / C
            updated[2] = b0 - traction / C
        else:
            traction = 0.0
            stress = np.array([effective[0] if 1 in regions else 0.0, 0.0, -effective[2]])
            if 1 in regions:
                updated[0] += (stress[0] - start[0]) / C
            updated[2] = b0
        updated[3] = top
        rows.append(
            dict(
                stress=stress.copy(),
                start_stress=start,
                old_levels=levels.copy(),
                levels=updated.copy(),
                retained=retained,
                physical=loads.copy(),
                start_traction=t0,
                traction=traction,
                gap=initial_gap + updated[2] - updated[1] if 2 in regions else None,
            )
        )
        levels, previous_regions = updated, regions
    return rows


def _check(actual, expected, tolerance):
    actual = np.asarray(actual)
    expected = np.broadcast_to(np.asarray(expected), actual.shape)
    finite = bool(np.isfinite(actual).all() and np.isfinite(expected).all())
    error = (
        float(np.max(np.abs(actual.astype(float) - expected.astype(float)), initial=0))
        if finite
        else None
    )
    return {
        "status": "passed" if finite and error <= tolerance else "failed",
        "maximum_absolute_error": error,
        "absolute_tolerance": tolerance,
    }


def _used_nodes(model, regions):
    used = np.zeros(model.mesh.nn, bool)
    for block in model.mesh.continuum_blocks():
        used[block.conn[np.isin(block.region, list(regions))].ravel()] = True
    return used


def _internal(model, fixture, stresses, traction, regions):
    """Independent constant-stress boundary integrals, not native FE quadrature."""
    force = np.zeros((model.mesh.nn, 2))
    rot = fixture["rotation"]
    for block in model.mesh.continuum_blocks():
        for conn, region in zip(block.conn, block.region):
            if region not in regions:
                continue
            s = stresses[region - 1]
            sigma = rot @ np.diag([NU / (1 - NU) * s, s]) @ rot.T
            for j in range(4):
                edge = [conn[j], conn[(j + 1) % 4]]
                if len(conn) == 8:
                    edge.append(conn[j + 4])
                dx = model.mesh.coords[edge[1]] - model.mesh.coords[edge[0]]
                total = sigma @ np.array([dx[1], -dx[0]])
                w = np.array([0.5, 0.5] if len(edge) == 2 else [1 / 6, 1 / 6, 2 / 3])
                np.add.at(force, edge, w[:, None] * total)
    if 2 in regions:
        _face_loads(model, fixture, force, -traction * WIDTH, traction * WIDTH)
    return force


def _face_loads(model, fixture, into, lower, upper):
    block = model.mesh.block("contact")
    n = block.etype.nen // 2
    w = np.array([0.5, 0.5] if n == 2 else [1 / 6, 1 / 6, 2 / 3]) / block.ne
    for conn in block.conn:
        for face, total in ((conn[:n], lower), (conn[n:], upper)):
            np.add.at(into, face, w[:, None] * total * fixture["normal"])


def _validate(result, model):
    if len(result.stages) != len(FRACTIONS) or len(model.stages) != len(FRACTIONS):
        raise ValueError("Missing/extra stage snapshots")
    for i, (stage, definition) in enumerate(zip(result.stages, model.stages)):
        if (
            stage.name != definition.name
            or definition.active_regions != REGIONS[i]
            or definition.load_split != FRACTIONS[i]
        ):
            raise ValueError("Invalid stage identity or fixture definition")
    tags = {b.tag for b in model.mesh.blocks}
    block = model.mesh.block("contact")
    shape = (block.ne, block.etype.nen // 2)
    for stage in (result.initial, *result.stages):
        if set(stage.active) != tags or set(stage.sig) != {"lower", "upper"}:
            raise ValueError("Invalid continuum/activity maps")
        for name in ("interfaces", "contact_gap", "contact_status"):
            if set(getattr(stage, name)) != {"contact"}:
                raise ValueError("Missing/extra contact evidence")
        for b in model.mesh.blocks:
            m = np.asarray(stage.active[b.tag])
            if m.dtype.kind != "b" or m.shape != (b.ne,):
                raise ValueError("Invalid activity mask")
            if b.tag != "contact" and np.asarray(stage.sig[b.tag]).shape != (b.ne, 4, 4):
                raise ValueError("Invalid stress shape")
        if (
            np.asarray(stage.u).shape != (model.mesh.nn, 2)
            or np.asarray(stage.reactions).shape != (model.mesh.nn, 3)
            or not np.isfinite(stage.reactions).all()
        ):
            raise ValueError("Invalid displacement/reaction array")
        if (
            isinstance(stage.lam, (bool, np.bool_))
            or not isinstance(stage.lam, (int, float, np.floating))
            or not math.isfinite(stage.lam)
        ):
            raise ValueError("Invalid accepted fraction")
        if (
            np.asarray(stage.contact_gap["contact"]).shape != shape
            or np.asarray(stage.interfaces["contact"]).shape != (*shape, 2)
            or np.asarray(stage.contact_status["contact"]).shape != shape
            or np.asarray(stage.contact_status["contact"]).dtype.kind not in "iu"
        ):
            raise ValueError("Invalid contact array")
    initial = result.initial
    gap = model.interfaces["contact"].initial_gap
    if (
        initial.lam != 1.0
        or any(not a.all() for a in initial.active.values())
        or np.any(initial.u != 0)
        or np.any(initial.reactions != 0)
        or any(np.any(s != 0) for s in initial.sig.values())
        or np.any(initial.contact_gap["contact"] != gap)
        or np.any(initial.interfaces["contact"] != 0)
        or np.any(initial.contact_status["contact"] != (0 if gap else 1))
    ):
        raise ValueError("Invalid stress-free initial record")


def evaluate(result, model, fixture):
    """Fixture evaluator only; no inference of new general backfill support."""
    _validate(result, model)
    exact = reference(model.interfaces["contact"].initial_gap, fixture["targets"])
    normal, rot, coords = fixture["normal"], fixture["rotation"], fixture["local_coords"]
    total = np.zeros(model.mesh.nn)
    datum = total.copy()
    previous_used = np.ones(model.mesh.nn, bool)
    previous_force = np.zeros((model.mesh.nn, 2))
    rows = []
    for i, (stage, definition, target) in enumerate(zip(result.stages, model.stages, exact)):
        regions = REGIONS[i]
        used = _used_nodes(model, regions)
        fresh = used & ~previous_used
        datum[fresh] = total[fresh]
        if definition.reset_displacements:
            datum[:] = total
        old = total.copy()
        du = target["levels"] - target["old_levels"]
        for block in model.mesh.continuum_blocks():
            for region in regions:
                nodes = np.unique(block.conn[block.region == region])
                if not nodes.size:
                    continue
                if region == 1:
                    total[nodes] = old[nodes] + (coords[nodes, 1] + 2) * du[0]
                elif region == 2:
                    y = coords[nodes, 1] + 1
                    total[nodes] = old[nodes] + (1 - y) * du[0] + y * du[1]
                else:
                    y = coords[nodes, 1]
                    total[nodes] = old[nodes] + (1 - y) * du[2] + y * du[3]
        checks = {
            "fraction": _check(stage.lam, FRACTIONS[i], 0.0),
            "reported_displacement_m": _check(
                stage.u[used], ((total - datum)[:, None] * normal)[used], 1e-10
            ),
            "inactive_u_nan": {"status": "passed" if np.isnan(stage.u[~used]).all() else "failed"},
            "inactive_reaction_zero": _check(stage.reactions[~used], 0.0, 0.0),
            "rotational_reaction_zero": _check(stage.reactions[:, 2], 0.0, 0.0),
            "contact_activity": _check(stage.active["contact"], 2 in regions, 0.0),
        }
        for block in model.mesh.continuum_blocks():
            mask = np.isin(block.region, list(regions))
            checks[block.tag + "_activity"] = _check(stage.active[block.tag], mask, 0.0)
            for region in set(block.region.tolist()):
                s = target["stress"][region - 1]
                lateral = NU / (1 - NU) * s
                tensor = rot @ np.diag([lateral, s]) @ rot.T
                wanted = [tensor[0, 0], tensor[1, 1], lateral, tensor[0, 1]]
                checks[f"region_{region}_stress_kpa"] = _check(
                    stage.sig[block.tag][block.region == region], wanted, 1e-8
                )
        if 2 in regions:
            checks["gap_m"] = _check(stage.contact_gap["contact"], target["gap"], 1e-10)
            checks["traction_kpa"] = _check(
                stage.interfaces["contact"], [0.0, target["traction"]], 1e-8
            )
            state = 2 if target["gap"] < 0 else 0 if target["gap"] > 0 else 1
            checks["contact_state"] = _check(stage.contact_status["contact"], state, 0.0)
        else:
            checks["inactive_contact"] = {
                "status": "passed"
                if (
                    np.isnan(stage.contact_gap["contact"]).all()
                    and np.isnan(stage.interfaces["contact"]).all()
                    and np.all(stage.contact_status["contact"] == 255)
                )
                else "failed"
            }
        current_target = np.zeros_like(previous_force)
        f1, f2, _ = fixture["targets"][i]
        _face_loads(model, fixture, current_target, f1 * WIDTH, f2 * WIDTH)
        projected = previous_force.copy()
        projected[~used] = 0.0
        physical = (1 - FRACTIONS[i]) * projected + FRACTIONS[i] * current_target
        prescribed = np.broadcast_to(np.abs(normal) == 0, physical.shape).copy()
        prescribed[model.mesh.nodes("base")] = True
        prescribed[model.mesh.nodes("top")] = True
        prescribed &= used[:, None]
        i0 = _internal(model, fixture, target["start_stress"], target["start_traction"], regions)
        retained = np.where(prescribed, 0.0, (1 - FRACTIONS[i]) * (i0 - projected))
        internal = _internal(model, fixture, target["stress"], target["traction"], regions)
        reactions = np.where(prescribed, internal - physical, 0.0)
        checks["all_nodal_reactions_kn_per_m"] = _check(stage.reactions[:, :2], reactions, 1e-8)
        residual = internal - physical - retained - stage.reactions[:, :2]
        checks["transition_nodal_balance_kn_per_m"] = _check(residual, 0.0, 1e-8)
        checks["physical_load_kn_per_m"] = _check(
            physical.sum(axis=0) @ normal, WIDTH * target["physical"].sum(), 1e-8
        )
        checks["retained_force_kn_per_m"] = _check(
            retained.sum(axis=0) @ normal, WIDTH * target["retained"].sum(), 1e-8
        )
        external = physical + retained + stage.reactions[:, :2]
        checks["global_force_kn_per_m"] = _check(external.sum(axis=0), 0.0, 1e-8)
        moment = math.fsum(
            model.mesh.coords[:, 0] * external[:, 1] - model.mesh.coords[:, 1] * external[:, 0]
        )
        checks["global_moment_knm_per_m"] = _check(moment, 0.0, 1e-8)
        physical_error = float(np.max(np.abs(internal - physical - stage.reactions[:, :2])))
        rows.append(
            {
                "stage_index": i,
                "stage": stage.name,
                "status": "passed"
                if all(c["status"] == "passed" for c in checks.values())
                else "failed",
                "checks": checks,
                "reactivated_nodes": int(fresh.sum()),
                "inactive_nodes": int((~used).sum()),
                "start_stress_kpa": target["start_stress"].tolist(),
                "reference_stress_kpa": target["stress"].tolist(),
                "reference_gap_m": target["gap"],
                "reference_traction_kpa": target["traction"],
                "reference_levels_m": target["levels"].tolist(),
                "physical_load_kn_per_m": float(WIDTH * target["physical"].sum()),
                "retained_force_kn_per_m": (WIDTH * target["retained"]).tolist(),
                "physical_nodal_residual_max": physical_error,
                "physical_only_equilibrium": physical_error <= 1e-8,
            }
        )
        previous_force, previous_used = physical, used
    return {
        "status": "passed" if all(r["status"] == "passed" for r in rows) else "failed",
        "stage_count": len(rows),
        "stages": rows,
    }


def run_case(**parameters):
    try:
        model, fixture = build_model(**parameters)
        report = evaluate(api.run(model), model, fixture)
    except (
        SlipSurfaceError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        OverflowError,
        FloatingPointError,
    ) as exc:
        report = {"status": "failed", "stage_count": 0, "stages": [], "reason": str(exc)}
    return {**report, "fixture": parameters}


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
        "scope": "Known dry elastic layer rebirth on original small-displacement mesh only; "
        "not new backfill placement, remeshing, restart or a general excavation audit.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--example", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.example and report["status"] == "passed":
        model, fixture = build_model(element_type="IFACE6", initial_gap=0.002)
        result = api.run(model)
        if evaluate(result, model, fixture)["status"] != "passed":
            raise ValueError("Saved example failed reference")
        args.example.parent.mkdir(parents=True, exist_ok=True)
        api.save_project(model, args.example, result)
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
