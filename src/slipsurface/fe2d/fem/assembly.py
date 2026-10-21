"""Degree-of-freedom map, sparse pattern and vectorised element operations.

The CSR pattern and the scatter index are built **once per stage** (whenever the active
element set changes). Inside iterations only ``np.bincount(scatter_idx, ke.ravel())``
runs; no COO -> CSR conversion happens in a loop.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from ..core.errors import ModelError
from ..model.boundary import Displacement, Fixity
from ..model.mesh import ElementBlock, Mesh
from .elements.base import GeomCache


class DofMap:
    """Maps nodes to global DOFs and classifies DOFs as free or prescribed.

    ``node_dofs[n] = [ux, uy, theta]``; ``-1`` means the DOF does not exist (node not used by
    any active element, or no rotation on a continuum node).

    ``ties`` (m, 2) lists (master, slave) node pairs that share all their DOFs when both are
    used — e.g. the duplicated nodes of an inactive interface, which then behaves as full
    continuity. ``owner[n]`` is the node that carries the DOFs of ``n`` (itself if untied).
    """

    def __init__(
        self,
        mesh: Mesh,
        active: dict[str, NDArray[np.bool_]] | None = None,
        beam_nodes: NDArray[np.int64] | None = None,
        fixities: tuple[Fixity, ...] = (),
        displacements: tuple[Displacement, ...] = (),
        ties: NDArray[np.int64] | None = None,
    ) -> None:
        nn = mesh.nn
        self.active = {
            b.tag: (np.ones(b.ne, dtype=bool) if active is None else active[b.tag])
            for b in mesh.blocks
        }
        used = np.zeros(nn, dtype=bool)
        for b in mesh.blocks:
            used[np.unique(b.conn[self.active[b.tag]])] = True
        has_rot = np.zeros(nn, dtype=bool)
        if beam_nodes is not None and beam_nodes.size:
            has_rot[beam_nodes] = True
            has_rot &= used

        # ---- node tying (union-find on used pairs)
        rep = np.arange(nn)
        if ties is not None and len(ties):
            t = np.asarray(ties, dtype=np.int64).reshape(-1, 2)
            t = t[used[t[:, 0]] & used[t[:, 1]] & (t[:, 0] != t[:, 1])]

            def find(i: int) -> int:
                while rep[i] != i:
                    rep[i] = rep[rep[i]]
                    i = int(rep[i])
                return i

            for a, b in t.tolist():
                ra, rb = find(a), find(b)
                if ra != rb:
                    rep[max(ra, rb)] = min(ra, rb)
            rep = np.array([find(i) for i in range(nn)])
            has_rot_rep = np.zeros(nn, dtype=bool)
            has_rot_rep[rep[has_rot]] = True
            has_rot = has_rot_rep & used
        owner_mask = used & (rep == np.arange(nn))

        node_dofs = np.full((nn, 3), -1, dtype=np.int64)
        n_used = int(owner_mask.sum())
        node_dofs[owner_mask, 0] = 2 * np.arange(n_used)
        node_dofs[owner_mask, 1] = 2 * np.arange(n_used) + 1
        rot_own = has_rot & owner_mask
        n_rot = int(rot_own.sum())
        node_dofs[rot_own, 2] = 2 * n_used + np.arange(n_rot)
        tied = used & ~owner_mask
        node_dofs[tied] = node_dofs[rep[tied]]
        self.node_dofs = node_dofs
        self.ndof = 2 * n_used + n_rot
        self.used_nodes = used
        self.owner = rep
        self.owner_mask = owner_mask

        presc_val = np.full(self.ndof, np.nan)
        for fx in fixities:
            ids = mesh.nodes(fx.node_set)
            for comp, flag in ((0, fx.ux), (1, fx.uy), (2, fx.rz)):
                if flag:
                    d = node_dofs[ids, comp]
                    presc_val[d[d >= 0]] = 0.0
        for dp in displacements:
            ids = mesh.nodes(dp.node_set)
            for comp, val in ((0, dp.ux), (1, dp.uy)):
                if val is not None:
                    d = node_dofs[ids, comp]
                    presc_val[d[d >= 0]] = float(val)
        self.prescribed_mask = ~np.isnan(presc_val)
        self.prescribed = np.flatnonzero(self.prescribed_mask)
        self.prescribed_values = presc_val[self.prescribed]
        self.free = np.flatnonzero(~self.prescribed_mask)
        if self.free.size == 0:
            raise ModelError("all degrees of freedom are prescribed")

    @property
    def nfree(self) -> int:
        return int(self.free.size)

    def element_dofs(self, block: ElementBlock) -> NDArray[np.int64]:
        """Global DOFs of the *active* elements of ``block``: (ne_active, 2*nen)."""
        conn = block.conn[self.active[block.tag]]
        d = self.node_dofs[conn][:, :, :2]  # (ne, nen, 2)
        return d.reshape(conn.shape[0], -1)

    def nodal(
        self, vec: NDArray[np.float64], comps: int = 2, owners_only: bool = False
    ) -> NDArray[np.float64]:
        """Scatter a global DOF vector back to an (nn, comps) nodal array (NaN where absent).

        ``owners_only``: tied nodes get NaN (use for nodal *forces*, which must not be
        counted twice); displacements are reported on every node of a tied group.
        """
        out = np.full((self.node_dofs.shape[0], comps), np.nan)
        for c in range(comps):
            d = self.node_dofs[:, c]
            m = d >= 0
            if owners_only:
                m &= self.owner_mask
            out[m, c] = vec[d[m]]
        return out


@dataclass(frozen=True, eq=False)
class SparsePattern:
    """CSR structure for a fixed set of element DOF tables."""

    ndof: int
    indptr: NDArray[np.int64]
    indices: NDArray[np.int64]
    scatter: tuple[NDArray[np.int64], ...]  # one per element table, flattened (ne*nd*nd,)

    @classmethod
    def build(cls, edofs_list: list[NDArray[np.int64]], ndof: int) -> SparsePattern:
        keys = []
        for ed in edofs_list:
            nd = ed.shape[1]
            r = np.repeat(ed, nd, axis=1)  # (ne, nd*nd) row-major over (i, j)
            c = np.tile(ed, (1, nd))
            keys.append((r * ndof + c).ravel())
        allk = np.concatenate(keys) if keys else np.empty(0, dtype=np.int64)
        uniq, inv = np.unique(allk, return_inverse=True)
        rows = uniq // ndof
        indices = uniq % ndof
        indptr = np.zeros(ndof + 1, dtype=np.int64)
        np.cumsum(np.bincount(rows, minlength=ndof), out=indptr[1:])
        scatter = []
        start = 0
        for k in keys:
            scatter.append(inv[start : start + k.size].astype(np.int64))
            start += k.size
        return cls(ndof, indptr, indices.astype(np.int64), tuple(scatter))

    @property
    def nnz(self) -> int:
        return int(self.indices.size)

    def assemble(self, ke_list: list[NDArray[np.float64]]) -> sp.csr_matrix:
        data = np.zeros(self.nnz)
        for sc, ke in zip(self.scatter, ke_list, strict=True):
            data += np.bincount(sc, weights=ke.ravel(), minlength=self.nnz)
        return sp.csr_matrix((data, self.indices, self.indptr), shape=(self.ndof, self.ndof))


# --------------------------------------------------------------------------- element ops
def element_stiffness(geom: GeomCache, D: NDArray[np.float64]) -> NDArray[np.float64]:
    """K_e = sum_g B^T D B w detJ t.  ``D``: (4,4), (ne,4,4) or (ne,ngp,4,4)."""
    B = geom.B
    ne, ngp, _, nd = B.shape
    if D.ndim == 2:
        DB = np.matmul(D, B)
    elif D.ndim == 3:
        DB = np.matmul(D[:, None], B)
    else:
        DB = np.matmul(D, B)
    Bw = (B * geom.wdet[:, :, None, None]).reshape(ne, ngp * 4, nd)
    return np.matmul(Bw.transpose(0, 2, 1), DB.reshape(ne, ngp * 4, nd))


def internal_force(geom: GeomCache, sig: NDArray[np.float64]) -> NDArray[np.float64]:
    """f_e = sum_g B^T sigma w detJ t  ->  (ne, nd)."""
    return np.einsum("egki,egk->ei", geom.B, sig * geom.wdet[..., None], optimize=True)


def strain(geom: GeomCache, ue: NDArray[np.float64]) -> NDArray[np.float64]:
    """Gauss-point strains (ne, ngp, 4) from element displacement vectors (ne, nd)."""
    return np.einsum("egki,ei->egk", geom.B, ue, optimize=True)


def scatter_vector(
    edofs: NDArray[np.int64], fe: NDArray[np.float64], ndof: int
) -> NDArray[np.float64]:
    return np.bincount(edofs.ravel(), weights=fe.ravel(), minlength=ndof)
