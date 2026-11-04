"""Independent prescribed-flux integrals and saved seepage-face complementarity."""

from __future__ import annotations

import numpy as np

from .dry_load_balance import _boundary_edge_map


def _nodes(mesh, name):
    return (mesh.nodes(name) if name in mesh.node_sets else np.unique(mesh.edges(name)))


def seepage_boundary_evidence(mesh, stage, water, used, head):
    names = [bc.node_set for bc in water.head_bcs] + list(water.seepage_faces)
    if len(set(names)) != len(names) or not names or set(stage.flow) != set(names):
        raise ValueError("Missing, duplicate or unexpected boundary-flow evidence")
    flows = np.array([stage.flow[name] for name in names], dtype=float)
    if not np.isfinite(flows).all():
        raise ValueError("Nonfinite reported seepage inflows")
    head_error, head_scale = 0., max(1., float(np.max(np.abs(head[used]))))
    head_owner = {}
    for bc in water.head_bcs:
        nodes = _nodes(mesh, bc.node_set)
        nodes = nodes[used[nodes]]
        head_error = max(head_error, float(np.max(np.abs(head[nodes] - bc.head), initial=0.)))
        head_scale = max(head_scale, abs(bc.head))
        head_owner.update((int(node), bc.node_set) for node in nodes)

    # q>0 is inflow. Straight-edge integrals are q*length, independent of node order.
    neighbors = _boundary_edge_map(mesh, stage.active)
    flux_total, flux_absolute, skipped = 0., 0., 0
    for bc in water.flux_bcs:
        if not np.isfinite(bc.q):
            raise ValueError("Nonfinite prescribed hydraulic flux")
        for edge in mesh.edges(bc.edge_set):
            if not used[edge].all():
                skipped += 1
                continue
            xy = mesh.coords[edge]
            length = np.linalg.norm(xy[1] - xy[0])
            if not np.isfinite(length) or length <= 0 or len(edge) not in (2, 3):
                raise ValueError("Invalid flux-loaded edge")
            if len(edge) == 3 and not np.allclose(xy[2], xy[:2].mean(axis=0),
                                                 rtol=0., atol=1e-10 * max(1., length)):
                raise ValueError("Curved/noncentral hydraulic flux edges unsupported")
            if len(neighbors.get(tuple(sorted(map(int, edge[:2]))), [])) != 1:
                raise ValueError("Hydraulic flux needs one active external continuum owner")
            flux_total += bc.q * length
            flux_absolute += abs(bc.q) * length
    residual = float(flows.sum() + flux_total)
    flow_scale = max(float(np.abs(flows).sum()) + flux_absolute, 1e-12)
    flow_ratio = abs(residual) / flow_scale

    faces = {}
    face_members = set()
    for name in water.seepage_faces:
        nodes = _nodes(mesh, name)
        nodes = set(nodes[used[nodes]].tolist()) - set(head_owner)
        if nodes & face_members:
            raise ValueError("Overlapping seepage faces need an explicit flow-ownership rule")
        face_members.update(nodes)
        faces[name] = nodes

    nodal_flux = getattr(stage, "seepage_nodal_flux", None)
    active_nodes = getattr(stage, "seepage_nodes", None)
    if water.seepage_faces and (nodal_flux is None or active_nodes is None):
        raise ValueError("Seepage faces require saved nodal flux and active-node evidence")
    if (nodal_flux is None) != (active_nodes is None):
        raise ValueError("Incomplete nodal hydraulic boundary evidence")
    checks = []
    nodal_error = face_inflow = active_head_error = released_head_error = 0.
    active = set()
    if nodal_flux is not None:
        nodal_flux = np.asarray(nodal_flux, dtype=float)
        active_nodes = np.asarray(active_nodes)
        if nodal_flux.shape != (mesh.nn,) or not np.isfinite(nodal_flux).all():
            raise ValueError("Invalid saved nodal hydraulic flux")
        if (active_nodes.ndim != 1 or not np.issubdtype(active_nodes.dtype, np.integer)
                or len(np.unique(active_nodes)) != len(active_nodes)
                or np.any(active_nodes < 0) or np.any(active_nodes >= mesh.nn)):
            raise ValueError("Invalid active seepage-node IDs")
        active = set(active_nodes.tolist())
        if not active <= face_members:
            raise ValueError("Active seepage nodes disagree with declared free faces")
        for bc in water.head_bcs:
            owned = [node for node, name in head_owner.items() if name == bc.node_set]
            nodal_error = max(nodal_error, abs(float(nodal_flux[owned].sum())
                                               - stage.flow[bc.node_set]))
        for name, nodes in faces.items():
            on, off = sorted(nodes & active), sorted(nodes - active)
            psi = head - mesh.coords[:, 1]
            e_active = float(np.max(np.abs(psi[on]), initial=0.))
            e_released = float(np.max(np.maximum(psi[off], 0.), initial=0.))
            inflow = float(np.max(np.maximum(nodal_flux[on], 0.), initial=0.))
            active_head_error = max(active_head_error, e_active)
            released_head_error = max(released_head_error, e_released)
            face_inflow = max(face_inflow, inflow)
            nodal_error = max(nodal_error, abs(float(nodal_flux[on].sum()) - stage.flow[name]))
            checks.append({
                "name": name, "candidate_nodes": len(nodes), "active_nodes": len(on),
                "released_nodes": len(off), "max_active_pressure_head_error_m": e_active,
                "max_released_positive_pressure_head_m": e_released,
                "max_active_inflow_m2_per_s": inflow,
            })
        constrained = set(head_owner) | active
        other = np.array(sorted(set(range(mesh.nn)) - constrained), dtype=int)
        nodal_error = max(nodal_error, float(np.max(np.abs(nodal_flux[other]), initial=0.)))
    ratio = max(head_error / head_scale, flow_ratio, nodal_error / flow_scale,
                face_inflow / flow_scale, active_head_error / head_scale,
                released_head_error / head_scale)
    return {
        "relative_residual": ratio,
        "annotations": {
            "head_boundary_max_error_m": head_error,
            "reported_net_inflow_m2_per_s": float(flows.sum()),
            "prescribed_flux_inflow_m2_per_s": float(flux_total),
            "flow_balance_residual_m2_per_s": residual,
            "relative_reported_flow_imbalance": flow_ratio,
            "reported_flow_scale_floor_m2_per_s": 1e-12,
            "skipped_inactive_flux_edges": skipped,
            "max_boundary_nodal_flow_error_m2_per_s": nodal_error,
            "active_seepage_node_ids": sorted(active),
            "seepage_face_checks": checks,
            "flow_reference": "independent_applied_flux_and_saved_boundary_evidence",
        },
    }
