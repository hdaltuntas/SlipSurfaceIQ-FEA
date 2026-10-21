"""Structural element groups: Timoshenko beam, bar (bolt/anchor) and zero-thickness
interface. All groups work on arrays of (active) elements; the solver treats them through
the same small protocol as the continuum blocks:

* ``edofs(dm, ids)``                    global DOFs of elements ``ids`` (n, nd)
* ``zero_state()``                      committed state arrays (full block size)
* ``activate(state, ids)``              reset / initialise newly activated elements
* ``integrate(state, ids, du_e, p)``    trial state (subset), f_int (n, nd), K_t (n, nd, nd)
* ``elastic_K(ids)``                    elastic stiffness (n, nd, nd)
* ``body_force(ids)``                   self-weight nodal forces (n, nd)
* ``pore_force(ids, p)``                (interfaces) joint water pressure as external force

Beam (BEAM2, DOFs ux, uy, theta per node; plane strain, per metre): two-node Timoshenko
element with the exact (interdependent interpolation) stiffness — exact for nodal loads
with any number of elements, no shear locking; E' = E / (1 - nu^2). Elastic (liner
plasticity is a v2 item). Self-weight is lumped to the end nodes.
Element end forces are reported as N (tension +), V, M in the local frame.

Bar (BAR2): axial spring EA/s with yield |N| <= T_yield/s (elastic-perfectly plastic) and
pretension T0/s introduced as an initial axial force when the bar is activated.

Interface (IFACE4/IFACE6): Goodman joint with diagonal stiffness (ks, kn), nodal
(Newton-Cotes: trapezoidal / Simpson) integration, Mohr-Coulomb slip
``|tau| + sigma_n tan(phi) - c <= 0`` with dilatancy psi and tension cut-off
``sigma_n <= sigma_t`` (gap). Tractions are effective; the joint water pressure enters
as an external force (``pore_force``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..core.enums import Analysis, ElemType, PlasticFlag
from ..model.materials import BoltSpec, InterfaceSpec, LinerSpec
from ..model.mesh import ElementBlock

Arr = NDArray[np.float64]
_SMALL = 1e-8


# ============================================================================== beam
class BeamGroup:
    kind = "beam"
    nd = 6

    def __init__(self, block: ElementBlock, coords: Arr, spec: LinerSpec, analysis: Analysis):
        if analysis is Analysis.AXISYMMETRIC:
            raise NotImplementedError("beam elements in axisymmetry are not available yet")
        self.block, self.tag, self.spec = block, block.tag, spec
        X = coords[block.conn]  # (ne, 2, 2)
        d = X[:, 1] - X[:, 0]
        L = np.linalg.norm(d, axis=1)
        if np.any(L <= 0):
            raise ValueError(f"beam '{self.tag}': zero-length element")
        self.L, self.c, self.s = L, d[:, 0] / L, d[:, 1] / L
        Ep = spec.E / (1.0 - spec.nu**2)
        G = spec.E / (2.0 * (1.0 + spec.nu))
        EA, EI, GA = Ep * spec.A, Ep * spec.I, G * spec.As
        ne = L.size
        Kl = np.zeros((ne, 6, 6))
        ka = EA / L
        for i, j, v in ((0, 0, 1), (0, 3, -1), (3, 0, -1), (3, 3, 1)):
            Kl[:, i, j] += v * ka
        # bending + shear: exact two-node Timoshenko stiffness (interdependent
        # interpolation; Przemieniecki 1968) on [w1, th1, w2, th2] = local dofs 1, 2, 4, 5,
        # theta = dw/dx - gamma counter-clockwise; As = 0 gives Euler-Bernoulli
        phi = 12.0 * EI / (GA * L**2) if GA > 0 else np.zeros(ne)
        c0 = EI / ((1.0 + phi) * L**3)
        kbs = np.empty((ne, 4, 4))
        L2 = L * L
        rows = (
            (12.0, 6.0 * L, -12.0, 6.0 * L),
            (6.0 * L, (4.0 + phi) * L2, -6.0 * L, (2.0 - phi) * L2),
            (-12.0, -6.0 * L, 12.0, -6.0 * L),
            (6.0 * L, (2.0 - phi) * L2, -6.0 * L, (4.0 + phi) * L2),
        )
        for a in range(4):
            for b in range(4):
                kbs[:, a, b] = c0 * rows[a][b]
        idx = [1, 2, 4, 5]
        for a in range(4):
            for b in range(4):
                Kl[:, idx[a], idx[b]] += kbs[:, a, b]
        T = np.zeros((ne, 6, 6))
        for o in (0, 3):
            T[:, o, o] = self.c
            T[:, o, o + 1] = self.s
            T[:, o + 1, o] = -self.s
            T[:, o + 1, o + 1] = self.c
            T[:, o + 2, o + 2] = 1.0
        self.T = T
        self.Kl = Kl
        self.Kg = np.einsum("eji,ejk,ekl->eil", T, Kl, T)  # T^T K T

    @property
    def ne(self) -> int:
        return self.block.ne

    def nodes(self, ids: NDArray[np.int64]) -> NDArray[np.int64]:
        return self.block.conn[ids]

    def edofs(self, node_dofs: NDArray[np.int64], ids: NDArray[np.int64]) -> NDArray[np.int64]:
        return node_dofs[self.block.conn[ids]].reshape(ids.size, 6)

    def zero_state(self) -> dict[str, Arr]:
        return {"f": np.zeros((self.ne, 6))}  # global end forces on the element

    def activate(self, state: dict[str, Arr], ids: NDArray[np.int64]) -> None:
        state["f"][ids] = 0.0

    def integrate(self, state: dict[str, Arr], ids: NDArray[np.int64], du_e: Arr, p: Arr | None):
        K = self.Kg[ids]
        f = state["f"][ids] + np.einsum("eij,ej->ei", K, du_e)
        return {"f": f}, f, K, np.zeros((ids.size, 1), dtype=np.uint8)

    def elastic_K(self, ids: NDArray[np.int64]) -> Arr:
        return self.Kg[ids]

    def body_force(self, ids: NDArray[np.int64]) -> Arr:
        w = self.spec.unit_weight * self.spec.A * self.L[ids]
        fe = np.zeros((ids.size, 6))
        fe[:, 1] = fe[:, 4] = -0.5 * w
        return fe

    def end_forces(self, f: Arr) -> Arr:
        """(ne, 2, 3) local [N, V, M] at both ends (N tension +, beam sign convention)."""
        fl = np.einsum("eij,ej->ei", self.T, f)
        out = np.empty((f.shape[0], 2, 3))
        out[:, 0] = -fl[:, 0:3]
        out[:, 1] = fl[:, 3:6]
        return out


# =============================================================================== bar
class BarGroup:
    kind = "bar"
    nd = 4

    def __init__(self, block: ElementBlock, coords: Arr, spec: BoltSpec, analysis: Analysis):
        self.block, self.tag, self.spec = block, block.tag, spec
        X = coords[block.conn]
        d = X[:, 1] - X[:, 0]
        L = np.linalg.norm(d, axis=1)
        if np.any(L <= 0):
            raise ValueError(f"bar '{self.tag}': zero-length element")
        self.L = L
        self.e = d / L[:, None]
        s = spec.spacing_out_of_plane  # 2D equivalence EA/s, T/s
        self.k = spec.EA / s / L
        self.Ny = spec.T_yield / s
        self.N0 = spec.pretension / s
        b = np.concatenate([-self.e, self.e], axis=1)  # (ne, 4)
        self.b = b

    @property
    def ne(self) -> int:
        return self.block.ne

    def edofs(self, node_dofs: NDArray[np.int64], ids: NDArray[np.int64]) -> NDArray[np.int64]:
        return node_dofs[self.block.conn[ids]][:, :, :2].reshape(ids.size, 4)

    def zero_state(self) -> dict[str, Arr]:
        return {"N": np.zeros(self.ne)}

    def activate(self, state: dict[str, Arr], ids: NDArray[np.int64]) -> None:
        state["N"][ids] = self.N0

    def integrate(self, state: dict[str, Arr], ids: NDArray[np.int64], du_e: Arr, p: Arr | None):
        b, k = self.b[ids], self.k[ids]
        N = state["N"][ids] + k * np.einsum("ei,ei->e", b, du_e)
        y = np.abs(N) > self.Ny
        N = np.where(y, np.sign(N) * self.Ny, N)
        kt = np.where(y, _SMALL * k, k)
        f = N[:, None] * b
        K = kt[:, None, None] * np.einsum("ei,ej->eij", b, b)
        return {"N": N}, f, K, y.astype(np.uint8)[:, None]

    def elastic_K(self, ids: NDArray[np.int64]) -> Arr:
        b = self.b[ids]
        return self.k[ids][:, None, None] * np.einsum("ei,ej->eij", b, b)

    def body_force(self, ids: NDArray[np.int64]) -> Arr:
        return np.zeros((ids.size, 4))


# ========================================================================= interface
@dataclass(frozen=True)
class _IfaceRule:
    xi: Arr  # IP positions along the face (= nodes)
    w: Arr  # Newton-Cotes weights on [-1, 1]


_RULES = {
    2: _IfaceRule(np.array([-1.0, 1.0]), np.array([1.0, 1.0])),
    3: _IfaceRule(np.array([-1.0, 1.0, 0.0]), np.array([1 / 3, 1 / 3, 4 / 3])),  # [a, b, mid]
}


def interface_return(
    t_tr: Arr, ks: float, kn: float, c: float, tphi: float, tpsi: float, st: float
) -> tuple[Arr, Arr, NDArray[np.uint8]]:
    """Return mapping for traction trials (m, 2) = [tau, sigma_n]; returns t, D (m,2,2), flag."""
    m = t_tr.shape[0]
    t = t_tr.copy()
    D = np.zeros((m, 2, 2))
    D[:, 0, 0], D[:, 1, 1] = ks, kn
    flag = np.zeros(m, dtype=np.uint8)
    tau, sn = t_tr[:, 0], t_tr[:, 1]
    # --- tension / gap
    gap = sn > st
    if np.any(gap):
        lim = max(c - st * tphi, 0.0)
        t[gap, 1] = st
        t[gap, 0] = np.clip(tau[gap], -lim, lim)
        D[gap] = _SMALL * np.array([[ks, 0.0], [0.0, kn]])
        D[gap, 0, 0] = np.where(np.abs(tau[gap]) < lim, ks, _SMALL * ks)
        flag[gap] = PlasticFlag.TENSION
    # --- slip
    fs = np.abs(tau) + sn * tphi - c
    tol = 1e-12 * (abs(c) + np.abs(sn) + np.abs(tau) + 1e-30)
    sl = (~gap) & (fs > tol)
    if np.any(sl):
        sg = np.sign(tau[sl])
        sg[sg == 0] = 1.0
        dl = fs[sl] / (ks + kn * tphi * tpsi)
        tau_n = tau[sl] - ks * dl * sg
        sn_n = sn[sl] - kn * tpsi * dl
        # past the apex (shear reverses) or into tension: put on the apex / gap
        bad = (tau_n * sg < 0) | (sn_n > st)
        t[sl, 0] = np.where(bad, 0.0, tau_n)
        t[sl, 1] = np.where(bad, min(st, c / tphi if tphi > 0 else st), sn_n)
        a = np.stack([sg, np.full(sg.size, tphi)], axis=1)
        bvec = np.stack([sg, np.full(sg.size, tpsi)], axis=1)
        K = np.array([ks, kn])
        Kb, aK = K * bvec, a * K
        den = (aK * bvec).sum(axis=1)
        Dsl = np.diag(K)[None] - np.einsum("mi,mj->mij", Kb, aK) / den[:, None, None]
        Dsl[bad] = _SMALL * np.diag(K)
        D[sl] = Dsl
        flag[sl] = np.where(bad, PlasticFlag.APEX, PlasticFlag.SHEAR)
    return t, D, flag


class InterfaceGroup:
    kind = "interface"

    def __init__(
        self, block: ElementBlock, coords: Arr, spec: InterfaceSpec, analysis: Analysis
    ) -> None:
        self.block, self.tag, self.spec = block, block.tag, spec
        npe = 2 if block.etype is ElemType.IFACE4 else 3
        self.npe = npe
        self.nd = 4 * npe
        conn = block.conn
        self.f1, self.f2 = conn[:, :npe], conn[:, npe:]
        X1 = coords[self.f1]  # (ne, npe, 2) face-1 geometry
        rule = _RULES[npe]
        xi = rule.xi
        if npe == 2:
            dN = np.array([[-0.5, 0.5], [-0.5, 0.5]])  # (ip, node)
        else:  # nodes [a, b, mid]
            dN = np.stack([xi - 0.5, xi + 0.5, -2 * xi], axis=1)
        Tg = np.einsum("pn,enj->epj", dN, X1)  # dx/dxi at IPs (ne, ip, 2)
        J = np.linalg.norm(Tg, axis=2)
        if np.any(J <= 0):
            raise ValueError(f"interface '{self.tag}': degenerate face")
        s = Tg / J[..., None]
        n = np.stack([-s[..., 1], s[..., 0]], axis=-1)  # left normal
        self.R = np.stack([s, n], axis=-1)  # (ne, ip, 2, 2): columns s, n
        w = J * rule.w[None, :]
        self.xip = X1  # IP = node positions of face 1 (ip order = node order)
        if analysis is Analysis.AXISYMMETRIC:
            w = w * X1[..., 0]
        self.w = w
        self.ks, self.kn = spec.ks, spec.kn
        self.set_strength_factor(1.0)
        # element matrix of relative displacement at IP k: du_rel(k) = u2_k - u1_k
        nd = self.nd
        self.Brel = np.zeros((npe, 2, nd))
        for k in range(npe):
            for j in range(2):
                self.Brel[k, j, 2 * k + j] = -1.0
                self.Brel[k, j, 2 * (npe + k) + j] = 1.0

    def set_strength_factor(self, F: float) -> None:
        """Strength reduction (SRF): c/F, tan(phi)/F, psi -> min(psi, phi_F)."""
        sp = self.spec
        self.c = sp.c / F
        self.tphi = math.tan(math.radians(sp.phi)) / F
        self.tpsi = min(math.tan(math.radians(sp.psi)), self.tphi)
        self.symmetric = abs(self.tphi - self.tpsi) < 1e-14

    @property
    def ne(self) -> int:
        return self.block.ne

    def edofs(self, node_dofs: NDArray[np.int64], ids: NDArray[np.int64]) -> NDArray[np.int64]:
        return node_dofs[self.block.conn[ids]][:, :, :2].reshape(ids.size, self.nd)

    def zero_state(self) -> dict[str, Arr]:
        return {"t": np.zeros((self.ne, self.npe, 2))}

    def activate(self, state: dict[str, Arr], ids: NDArray[np.int64]) -> None:
        state["t"][ids] = 0.0

    def _local_jump(self, ids: NDArray[np.int64], du_e: Arr) -> Arr:
        dg = np.einsum("pjd,ed->epj", self.Brel, du_e)  # global jump (n, ip, 2)
        return np.einsum("epji,epj->epi", self.R[ids], dg)  # local [s, n]

    def _assemble(self, ids: NDArray[np.int64], t: Arr, D: Arr) -> tuple[Arr, Arr]:
        R, w = self.R[ids], self.w[ids]
        tg = np.einsum("epij,epj->epi", R, t) * w[..., None]  # global traction x weight
        f = np.einsum("pjd,epj->ed", self.Brel, tg)
        Dg = np.einsum("epij,epjk,eplk->epil", R, D, R) * w[..., None, None]
        K = np.einsum("pid,epil,plf->edf", self.Brel, Dg, self.Brel)
        return f, K

    def integrate(self, state: dict[str, Arr], ids: NDArray[np.int64], du_e: Arr, p: Arr | None):
        dloc = self._local_jump(ids, du_e)
        t_tr = state["t"][ids] + dloc * np.array([self.ks, self.kn])
        t, D, fl = interface_return(t_tr.reshape(-1, 2), self.ks, self.kn, self.c, self.tphi,
                                    self.tpsi, self.spec.sig_t)  # fmt: skip
        t = t.reshape(t_tr.shape)
        D = D.reshape(*t_tr.shape[:2], 2, 2)
        f, K = self._assemble(ids, t, D)
        return {"t": t}, f, K, fl.reshape(t_tr.shape[:2])

    def elastic_K(self, ids: NDArray[np.int64]) -> Arr:
        D = np.zeros((ids.size, self.npe, 2, 2))
        D[..., 0, 0], D[..., 1, 1] = self.ks, self.kn
        return self._assemble(ids, np.zeros((ids.size, self.npe, 2)), D)[1]

    def body_force(self, ids: NDArray[np.int64]) -> Arr:
        return np.zeros((ids.size, self.nd))

    def pore_force(self, ids: NDArray[np.int64], p: Arr) -> Arr:
        """Joint water pressure p (n, ip) pushing face 2 along +n and face 1 along -n."""
        n = self.R[ids][..., :, 1]  # (n, ip, 2)
        tg = p[..., None] * n * self.w[ids][..., None]
        return np.einsum("pjd,epj->ed", self.Brel, tg)

    def initial_traction(self, ids: NDArray[np.int64], sig_nodes: Arr) -> Arr:
        """Tractions (tau, sigma_n) from nodal continuum stresses at face-2 nodes."""
        return self.traction_from_stress(ids, sig_nodes[self.f2[ids]])

    def traction_from_stress(self, ids: NDArray[np.int64], s: Arr) -> Arr:
        """Local tractions (tau, sigma_n) of stresses ``s`` (n, ip, 4) at the IPs."""
        Sxy = np.zeros((*s.shape[:2], 2, 2))
        Sxy[..., 0, 0], Sxy[..., 1, 1] = s[..., 0], s[..., 1]
        Sxy[..., 0, 1] = Sxy[..., 1, 0] = s[..., 3]
        R = self.R[ids]
        n = R[..., :, 1]
        tr = np.einsum("epij,epj->epi", Sxy, n)  # traction on a face with normal n
        return np.einsum("epji,epj->epi", R, tr)


GROUP_TYPES = {ElemType.BEAM2: BeamGroup, ElemType.BAR2: BarGroup,
               ElemType.IFACE4: InterfaceGroup, ElemType.IFACE6: InterfaceGroup}  # fmt: skip
