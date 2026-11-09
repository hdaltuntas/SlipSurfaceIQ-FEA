"""Native two-body normal-contact switching with independent layer equilibrium.

Both faces belong to always-active continuum. Contact is removed and reintroduced
inside partial load steps, while top/bottom supports stay fixed. Uniform cases
have a scalar closed-form equilibrium; eccentric cases check equilibrium only.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.post.contact_activation_equilibrium import (
    contact_activation_equilibrium_by_stage,
)

WIDTH, HEIGHT = 2.0, 1.0
YOUNG, POISSON, KN = 2000.0, 0.25, 2000.0
K = YOUNG*(1-POISSON)/((1+POISSON)*(1-2*POISSON))/HEIGHT
FRACTIONS = (1.0, 0.25, 0.5, 0.4, 0.6, 1.0, 0.5, 0.35, 1.0)
ACTIVE = (True, False, False, True, True, True, False, True, True)
FORCES = (-16.0, -20.0, -12.0, -18.0, -24.0, 10.0, -12.0, -20.0, -18.0)
TOPS = (-0.008, -0.007, -0.006, -0.008, -0.009, 0.006, -0.005, -0.008, -0.007)
SHIFT = np.array([3.25, -2.5])


def build_model(*, element_type="IFACE4", initial_gap=0.0, mode="mixed",
                quarter_turn=False, eccentric=False):
    """Two independently supported continuum bodies; no stabilizing springs."""
    if element_type not in ("IFACE4", "IFACE6") or mode not in (
        "force", "displacement", "mixed"
    ):
        raise ValueError("Unsupported fixture type or control mode")
    etype = api.ElemType.Q4 if element_type == "IFACE4" else api.ElemType.Q8
    source = rectangle(WIDTH, HEIGHT, 2, 1, etype=etype)
    nn = source.nn
    lower = source.coords.copy()
    lower[:, 1] -= HEIGHT
    local_coords = np.vstack([lower, source.coords])
    rotation = np.array([[0.0, -1.0], [1.0, 0.0]]) if quarter_turn else np.eye(2)
    coords = local_coords @ rotation.T + SHIFT
    bottom_edges = source.edges("bottom").copy()
    for edge in bottom_edges:
        if source.coords[edge[1], 0] < source.coords[edge[0], 0]:
            edge[:2] = edge[:2][::-1]
    upper_nodes = source.nodes("bottom")
    lower_nodes = source.nodes("top")
    lower_nodes = lower_nodes[np.argsort(source.coords[lower_nodes, 0])]
    upper_nodes = upper_nodes[np.argsort(source.coords[upper_nodes, 0])]
    partners = dict(zip(upper_nodes, lower_nodes))
    contact = api.ElementBlock(
        api.ElemType[element_type],
        np.array([[*[partners[int(n)] for n in edge], *(edge+nn)] for edge in bottom_edges]),
        np.zeros(len(bottom_edges), dtype=int), "contact",
    )
    blocks = (
        replace(source.blocks[0], tag="lower"),
        replace(source.blocks[0], conn=source.blocks[0].conn+nn, tag="upper"),
        contact,
    )
    nodes = {"all": np.arange(2*nn), "bottom": source.nodes("bottom"),
             "top": source.nodes("top")+nn, "lower_contact": lower_nodes,
             "upper_contact": upper_nodes+nn}
    mesh = api.Mesh(coords, blocks, nodes, {"loaded": bottom_edges+nn})
    normal = rotation @ np.array([0.0, 1.0])
    tangent = rotation @ np.array([1.0, 0.0])
    left = int(upper_nodes[0]+nn)
    fractions = np.array([0.5, 0.5] if element_type == "IFACE4" else [1/6, 1/6, 2/3])
    stages, force_targets, top_targets, analytical_targets = [], [], [], []
    for i, (alpha, on) in enumerate(zip(FRACTIONS, ACTIVE)):
        force = FORCES[i] if mode != "displacement" else 0.0
        top = TOPS[i] if mode != "force" else 0.0
        force_targets.append(force)
        top_targets.append(top)
        if eccentric:
            # Known uniform edge resultant plus a known point action at the left end.
            shear = (1 if i % 2 == 0 else -1)*1.5
            point_normal = 0.30*force
            point = point_normal*normal + 2.0*tangent
            loads = (api.EdgeLoad("loaded", qn=0.70*force/WIDTH, qt=shear),
                     api.PointLoad(left, fx=float(point[0]), fy=float(point[1])))
            edge_force = 0.70*force*normal + WIDTH*shear*tangent
            edge_point = SHIFT + rotation @ np.array([WIDTH/2, 0.0])
            moment = (edge_point[0]*edge_force[1]-edge_point[1]*edge_force[0]
                      + coords[left, 0]*point[1]-coords[left, 1]*point[0])
            total = edge_force+point
        else:
            loads_list = []
            for edge in bottom_edges:
                length = source.coords[edge[1], 0]-source.coords[edge[0], 0]
                for node, weight in zip(edge+nn, fractions):
                    f = normal * (force/WIDTH*length*weight)
                    loads_list.append(api.PointLoad(int(node), fx=float(f[0]), fy=float(f[1])))
            loads = tuple(loads_list)
            total = force*normal
            center = SHIFT + rotation @ np.array([WIDTH/2, 0.0])
            moment = center[0]*total[1]-center[1]*total[0]
        analytical_targets.append([float(total[0]), float(total[1]), float(moment)])
        disp = api.Displacement("top", ux=-top) if quarter_turn else api.Displacement("top", uy=top)
        stages.append(api.Stage(
            "switch" if i in (1, 2) else f"stage_{i}",
            active_structures={"contact"} if on else set(),
            loads=loads, displacements=(disp,), load_split=alpha,
            reset_displacements=i in (2, 4, 7),
        ))
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN, mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", YOUNG, POISSON)},
        region_material={1: "soil"}, initial=api.InitialStress("none", active_structures=set()),
        fixities=(api.Fixity("all", not quarter_turn, quarter_turn),
                  api.Fixity("bottom", True, True),
                  api.Fixity("top", quarter_turn, not quarter_turn)),
        interfaces={"contact": api.InterfaceSpec.unilateral_normal(
            "contact", KN, initial_gap=initial_gap)},
        stages=stages,
        settings=api.SolverSettings(dlam0=1.0, dlam_max=1.0, max_iter=40,
                                    tol_force=1e-10, tol_energy=1e-10, linear_solver="splu"),
    )
    return model, dict(force_targets=force_targets, top_targets=top_targets,
                      analytical_targets=analytical_targets, normal=normal)


def uniform_reference(initial_gap, force_targets, top_targets):
    """Two independent elastic layers, scalar contact law and unfinished-release terms.

    k*a-t=q_lower; k*(b-v)+t=q_upper. With contact on,
    t=min(0, kn*(g0+v+q_upper/k-q_lower/k)/(1+2*kn/k)).
    Never read a native result or call an audit routine to form the targets.
    """
    a = b = v = physical = 0.0
    out = []
    for fraction, active, force_target, top_target in zip(
        FRACTIONS, ACTIVE, force_targets, top_targets,
    ):
        t_start = KN*min(initial_gap+b-a, 0.0) if active else 0.0
        release_lower = (1-fraction)*(K*a-t_start)
        release_upper = (1-fraction)*(K*(b-v)+t_start-physical)
        physical = (1-fraction)*physical + fraction*force_target/WIDTH
        v = (1-fraction)*v + fraction*top_target
        q1, q2 = release_lower, physical+release_upper
        t = min(0.0, KN*(initial_gap+v+q2/K-q1/K)/(1+2*KN/K)) if active else 0.0
        a, b = (q1+t)/K, v+(q2-t)/K
        out.append(dict(lower_u=a, upper_u=b, top_u=v, gap=initial_gap+b-a, traction=t,
                        lower_reaction=-WIDTH*K*a, top_reaction=WIDTH*K*(v-b),
                        applied=WIDTH*physical, release_lower=WIDTH*release_lower,
                        release_upper=WIDTH*release_upper))
    return out


def _error(actual, expected, tolerance):
    array = np.asarray(actual)
    finite = bool(np.isfinite(array).all()) and bool(np.isfinite(expected).all())
    error = float(np.max(np.abs(array-expected), initial=0)) if finite else None
    return {"status": "passed" if finite and error <= tolerance else "failed",
            "maximum_absolute_error": error, "tolerance": tolerance}


def run_case(**kwargs):
    model, fixture = build_model(**kwargs)
    result = api.run(model)
    origin = (1.25, -0.75)
    report = contact_activation_equilibrium_by_stage(result, origin=origin)
    normal = fixture["normal"]
    reference = uniform_reference(model.interfaces["contact"].initial_gap,
                                  fixture["force_targets"], fixture["top_targets"])
    checks = []
    previous_u = np.zeros_like(result.initial.u)
    datum = previous_u.copy()
    for i, (definition, st, row, exact) in enumerate(zip(
        model.stages, result.stages, report["stages"], reference,
    )):
        current = {}
        # Direct sum of products, not the audit's recursive applied-force calculation.
        target = sum(np.asarray(fixture["analytical_targets"][j])*FRACTIONS[j]
                     *np.prod([1-f for f in FRACTIONS[j+1:i+1]]) for j in range(i+1))
        target[2] += -origin[0]*target[1] + origin[1]*target[0]
        current["physical_applied_resultant"] = _error(
            row.get("physical_external_resultant", [np.nan]*3), target, 1e-8,
        )
        if not kwargs.get("eccentric", False):
            if definition.reset_displacements:
                datum = previous_u.copy()
            total_u = st.u+datum
            current["lower_contact_u_m"] = _error(
                total_u[model.mesh.nodes("lower_contact")] @ normal, exact["lower_u"], 1e-10,
            )
            current["upper_contact_u_m"] = _error(
                total_u[model.mesh.nodes("upper_contact")] @ normal, exact["upper_u"], 1e-10,
            )
            for key, value in (("bottom", "lower_reaction"), ("top", "top_reaction")):
                current[key+"_reaction"] = _error(
                    st.reactions[model.mesh.nodes(key), :2].sum(axis=0) @ normal,
                    exact[value], 1e-8,
                )
            retained = np.asarray(row.get("history", {}).get(
                "retained_release_nodal", np.full_like(st.u, np.nan),
            ))
            for key in ("lower", "upper"):
                current[key+"_release"] = _error(
                    retained[model.mesh.nodes(key+"_contact")].sum(axis=0) @ normal,
                    exact["release_"+key], 1e-8,
                )
            if ACTIVE[i]:
                current["gap_m"] = _error(st.contact_gap["contact"], exact["gap"], 1e-10)
                current["traction_kpa"] = _error(
                    st.interfaces["contact"][..., 1], exact["traction"], 1e-8,
                )
            else:
                current["inactive_evidence"] = {"status": "passed" if (
                    np.isnan(st.contact_gap["contact"]).all()
                    and np.isnan(st.interfaces["contact"]).all()
                    and np.all(st.contact_status["contact"] == 255)) else "failed"}
            previous_u = total_u
        checks.append({"stage_index": i, "status": "passed" if all(
            x["status"] == "passed" for x in current.values()) else "failed", "checks": current})
    if not all(x["status"] == "passed" for x in checks):
        report["status"] = "failed"
    return {**report, "fixture": kwargs, "independent_reference_checks": checks}


def run_benchmark():
    cases = [run_case(element_type=etype, initial_gap=gap, mode=mode, quarter_turn=rot)
             for etype in ("IFACE4", "IFACE6") for gap in (0.0, 0.002)
             for mode in ("force", "displacement", "mixed") for rot in (False, True)]
    cases += [run_case(element_type=etype, initial_gap=gap, mode="mixed", quarter_turn=rot,
                       eccentric=True)
              for etype in ("IFACE4", "IFACE6") for gap in (0.0, 0.002) for rot in (False, True)]
    return {"status": "passed" if all(c["status"] == "passed" for c in cases) else "failed",
            "native_solver": "api.run / StaticSolver", "case_count": len(cases),
            "stage_count": sum(c["stage_count"] for c in cases), "cases": cases,
            "scope": "Two supported continuum bodies, partial contact on/off; uniform cases "
                     "have an independent scalar solution. Eccentric cases check equilibrium, "
                     "not an exact contact patch. No excavation/support removal/water."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark()
    payload = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
