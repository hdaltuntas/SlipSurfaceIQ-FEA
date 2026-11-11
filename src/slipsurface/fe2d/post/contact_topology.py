"""Internal geometry, evidence and force assembly for the elastic topology audit."""

from __future__ import annotations

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType
from ..fem.elements import kernel
from .contact_equilibrium import UnsupportedContactBudget, _array, _criterion, _resultant
from .contact_resultants import _geometry
from .contact_results import contact_points, normal_contact_tags

_BULK = (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8)


class _Context:
    def __init__(self, model):
        model.validate()
        self.model, self.mesh = model, model.mesh
        self.bulk = tuple(self.mesh.continuum_blocks())
        self.tags = normal_contact_tags(model)
        if (
            model.analysis is not Analysis.PLANE_STRAIN
            or not self.bulk
            or not self.tags
            or model.liners
            or model.bolts
            or len(self.tags) != len(model.interfaces)
            or any(
                b.etype not in (*_BULK, ElemType.IFACE4, ElemType.IFACE6) for b in self.mesh.blocks
            )
        ):
            raise UnsupportedContactBudget("Require plane-strain continuum and normal contact only")
        if (
            model.initial.mode != "none"
            or model.initial.gravity
            or model.initial.water.mode != "none"
            or model.settings.method != "NR"
            or any(
                m.model != "elastic" or m.drainage is not Drainage.DRAINED
                for m in model.materials.values()
            )
        ):
            raise UnsupportedContactBudget("Require dry drained elastic zero-stress NR history")
        if any(
            s.water.mode != "none" or s.seismic_kh or s.seismic_kv or s.material_override
            for s in model.stages
        ):
            raise UnsupportedContactBudget("Water, seismic and property changes are unsupported")
        self.xy = _array(self.mesh.coords, (self.mesh.nn, 2), "mesh coordinates")
        self.geom = {
            b.tag: kernel(b.etype).precompute(
                self.xy, b.conn, model.analysis, model.settings.gauss_order
            )
            for b in self.bulk
        }
        self.contacts = {tag: _geometry(self.mesh, self.mesh.block(tag)) for tag in self.tags}
        self.owners = {}
        # Unique topological edge ownership; never identify coincident opposite faces.
        for b in self.bulk:
            corners = 3 if b.etype in (ElemType.T3, ElemType.T6) else 4
            for e, conn in enumerate(b.conn):
                for j in range(corners):
                    edge = [int(conn[j]), int(conn[(j + 1) % corners])]
                    if b.etype.nodes_per_edge == 3:
                        edge.append(int(conn[corners + j]))
                    self.owners.setdefault(tuple(sorted(edge[:2])), []).append(
                        (b.tag, e, frozenset(edge))
                    )
        self.adjacency = {}
        for tag in self.tags:
            block = self.mesh.block(tag)
            n = block.etype.nen // 2
            rows = []
            for conn in block.conn:
                row = []
                for face in (conn[:n], conn[n:]):
                    matches = self.owners.get(tuple(sorted(map(int, face[:2]))), [])
                    if len(matches) > 1:
                        raise UnsupportedContactBudget("Ambiguous interface face ownership")
                    if matches and frozenset(map(int, face)) != matches[0][2]:
                        raise UnsupportedContactBudget("Nonconforming interface face nodes")
                    row.append(matches[0][:2] if matches else None)
                rows.append(row)
            self.adjacency[tag] = rows

    def activity(self, definition):
        regions = definition.active_regions
        active = {
            b.tag: np.ones(b.ne, dtype=bool)
            if regions is None
            else np.isin(b.region, tuple(regions))
            for b in self.bulk
        }
        if not any(a.any() for a in active.values()):
            raise UnsupportedContactBudget("At least one active continuum element is required")
        structures = definition.active_structures
        for tag in self.tags:
            requested = structures is None or tag in structures
            active[tag] = np.array(
                [
                    requested and all(owner is None or active[owner[0]][owner[1]] for owner in row)
                    for row in self.adjacency[tag]
                ],
                dtype=bool,
            )
        used = np.zeros(self.mesh.nn, dtype=bool)
        for block in self.mesh.blocks:
            used[block.conn[active[block.tag]].ravel()] = True
        return active, used

    def snapshot(self, result, snapshot, active, used):
        """Reject absent, malformed or contradictory evidence before any arithmetic."""
        bulk_tags, contact_tags = {b.tag for b in self.bulk}, set(self.tags)
        for name, tags in (
            ("active", {b.tag for b in self.mesh.blocks}),
            ("sig", bulk_tags),
            ("interfaces", contact_tags),
            ("contact_gap", contact_tags),
            ("contact_status", contact_tags),
        ):
            if set(getattr(snapshot, name)) != tags:
                raise ValueError(f"Missing/unexpected {name} snapshot maps")
        if set(snapshot.plastic) != bulk_tags:
            raise ValueError("Missing/unexpected elastic-flag maps")
        expected_pore = bulk_tags
        if set(snapshot.pore) != expected_pore or set(snapshot.excess_pore) - bulk_tags:
            raise ValueError("Missing/unexpected dry pore maps")
        if snapshot.beams or snapshot.bars:
            raise ValueError("Unexpected structural forces")
        for tag, expected in active.items():
            mask = _array(snapshot.active[tag], expected.shape, "activity", kind="b")
            if not np.array_equal(mask, expected):
                raise ValueError(f"{tag}: activity contradicts independently derived adjacency")
        for b in self.bulk:
            shape = self.geom[b.tag].wdet.shape
            stress = _array(snapshot.sig[b.tag], (*shape, 4), "stored stress")
            if np.any(stress[~active[b.tag]] != 0):
                raise ValueError("Removed continuum must have zero stored stress")
            flags = _array(snapshot.plastic[b.tag], shape, "elastic flags", kind="iu")
            if np.any(flags != 0):
                raise ValueError("Plastic evidence contradicts elastic audit")
            for mapping in (snapshot.pore, snapshot.excess_pore):
                if b.tag not in mapping:
                    continue
                p = np.asarray(mapping[b.tag])
                if (
                    p.shape != shape
                    or p.dtype.kind not in "fiu"
                    or not np.all(p[active[b.tag]] == 0)
                    or not np.isnan(p[~active[b.tag]]).all()
                ):
                    raise ValueError("Invalid dry pore evidence")
        for p in contact_points(result, snapshot):
            if p.active and p.availability != "available":
                raise ValueError("Missing active contact evidence")
        u = np.asarray(snapshot.u)
        if (
            u.shape != (self.mesh.nn, 2)
            or u.dtype.kind not in "fiu"
            or not np.isfinite(u[used]).all()
            or not np.isnan(u[~used]).all()
        ):
            raise ValueError(
                "Active displacement must be finite; inactive displacement must be NaN"
            )
        return u, _array(snapshot.reactions, (self.mesh.nn, 3), "reactions")

    def soil_force(self, stress, active):
        force = np.zeros((self.mesh.nn, 2))
        for b in self.bulk:
            g = self.geom[b.tag]
            local = np.einsum("egki,egk,eg->ei", g.B, stress[b.tag], g.wdet)
            mask = active[b.tag]
            np.add.at(force, b.conn[mask].ravel(), local[mask].reshape(-1, 2))
        return force

    def contact_force(self, total, active, snapshot=None):
        force = np.zeros((self.mesh.nn, 2))
        gaps = {}
        for tag in self.tags:
            b, spec = self.mesh.block(tag), self.model.interfaces[tag]
            n = b.etype.nen // 2
            first, second = b.conn[:, :n], b.conn[:, n:]
            _, _, normal, weight, _ = self.contacts[tag]
            gap = spec.initial_gap + np.einsum("epi,ei->ep", total[second] - total[first], normal)
            gaps[tag] = gap
            traction = (
                spec.kn * np.minimum(gap, 0.0)
                if snapshot is None
                else (np.asarray(snapshot.interfaces[tag])[..., 1])
            )
            mask = active[tag]
            force_at_point = (traction[mask] * weight[mask])[..., None] * normal[mask, None, :]
            np.add.at(force, first[mask].ravel(), -force_at_point.reshape(-1, 2))
            np.add.at(force, second[mask].ravel(), force_at_point.reshape(-1, 2))
        return force, gaps

    def bodies(self, active, used):
        parent = np.arange(self.mesh.nn)

        def root(i):
            while i != parent[i]:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return int(i)

        for b in self.bulk:
            for nodes in b.conn[active[b.tag]]:
                for node in nodes[1:]:
                    parent[root(int(node))] = root(int(nodes[0]))
        groups = {}
        for i in np.flatnonzero(used):
            groups.setdefault(root(int(i)), []).append(int(i))
        return tuple(np.array(ids) for ids in groups.values())

    def elastic_prediction(self, previous_stress, previous_active, active, increment):
        """Isotropic plane strain derived directly from E,nu; no material update call."""
        predicted, start = {}, {}
        for b in self.bulk:
            mask = active[b.tag] & previous_active[b.tag]
            s0 = np.where(mask[:, None, None], previous_stress[b.tag], 0.0)
            start[b.tag] = s0
            deps = np.einsum(
                "egki,ei->egk", self.geom[b.tag].B, increment[b.conn].reshape(b.ne, -1)
            )
            expected = np.zeros_like(s0)
            for region in np.unique(b.region):
                material = self.model.materials[self.model.region_material[int(region)]]
                young, nu = material.params["E"], material.params["nu"]
                mu, lam = young / (2 * (1 + nu)), young * nu / ((1 + nu) * (1 - 2 * nu))
                d = np.zeros((4, 4))
                d[:3, :3] = lam
                d[np.arange(3), np.arange(3)] += 2 * mu
                d[3, 3] = mu
                ids = (b.region == region) & active[b.tag]
                expected[ids] = s0[ids] + np.einsum("ij,egj->egi", d, deps[ids])
            predicted[b.tag] = expected
        return predicted, start


def _balance(ctx, soil, contact, applied, reactions, active, used, origin, atol, matol, rtol):
    nodal = soil + contact - applied - reactions
    scale = np.maximum.reduce([np.abs(v) for v in (soil, contact, applied, reactions)])
    checks = {"nodal_force": _criterion(nodal, scale, atol, rtol)}
    total_load, total_reaction = (_resultant(ctx.xy, v, origin) for v in (applied, reactions))
    global_residual = total_load + total_reaction
    checks["global_force"] = _criterion(
        global_residual[:2], np.maximum(abs(total_load[:2]), abs(total_reaction[:2])), atol, rtol
    )
    checks["global_moment"] = _criterion(
        global_residual[2:], np.maximum(abs(total_load[2:]), abs(total_reaction[2:])), matol, rtol
    )
    bodies = []
    for ids in ctx.bodies(active, used):
        terms = {
            key: _resultant(ctx.xy[ids], value[ids], origin)
            for key, value in (
                ("applied", applied),
                ("reaction", reactions),
                ("contact_action", -contact),
            )
        }
        residual = sum(terms.values())
        verdict = _criterion(
            residual, np.maximum.reduce([abs(v) for v in terms.values()]), [atol, atol, matol], rtol
        )
        bodies.append(
            {
                "nodes": ids.tolist(),
                **{k: v.tolist() for k, v in terms.items()},
                "residual": residual.tolist(),
                **verdict,
            }
        )
    return {
        "status": "passed"
        if all(c["status"] == "passed" for c in checks.values())
        and all(b["status"] == "passed" for b in bodies)
        else "failed",
        "checks": checks,
        "partitions": bodies,
        "global_residual": global_residual.tolist(),
        "external_resultant": total_load.tolist(),
        "reaction_resultant": total_reaction.tolist(),
    }
