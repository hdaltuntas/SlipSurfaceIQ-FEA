"""Staged static analysis: initial stress + sequence of (elasto-plastic) stages.

Every stage is solved incrementally from the committed state with the Newton-Raphson
family in :mod:`.nonlinear`:

    R(u, lam) = lam f_ext + (1 - lam) f0 - f_int(sigma'(u))

* **Active set** — the mesh is fixed; continuum regions and structural blocks are switched
  on and off per stage. Whenever the active set changes the DOF map, the CSR pattern and
  the scatter indices are rebuilt (once per stage). Nodes that lose all their elements
  keep (and hide) their displacement; nodes that become active get ``u_ref = u`` so the
  reported displacement starts from zero.
* **Excavation** — deactivated elements lose their stresses; ``f0`` is evaluated on the
  remaining elements, so the unbalanced force on the new boundary is applied gradually.
  ``Stage.load_split = alpha < 1`` stops the stage at lambda = alpha; the remainder is
  carried over automatically to the next stage (support installed in between).
* **Activation** — new continuum elements start stress-free, bars start with their
  pretension; their self-weight enters ``f_ext``.
* **Water** — a piezometric line gives hydrostatic pore pressures; the internal force is
  effective, the pore-pressure terms (``int B^T m p``, joint water pressure and water
  pressure on the exposed boundary of the active mesh) are external forces, unit weights
  switch to saturated below the line. Changing the water level between stages produces
  the corresponding load increment.
* **Material change** — committed stresses are projected onto the new yield surfaces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from ..core.enums import Analysis, ElemType
from ..core.errors import ModelError
from ..core.log import get_logger
from ..core.units import GAMMA_W
from ..model.boundary import Displacement, WaterCondition
from ..model.materials import MaterialSpec
from ..model.model import Model
from ..model.stages import SolverSettings, Stage
from .assembly import DofMap, SparsePattern, element_stiffness, internal_force, strain
from .elements import kernel
from .elements.base import GeomCache
from .linsolve import factorize
from .loads import TractionFn, assemble_nodal_loads, k0_stress_field, pressure_edge_forces
from .materials import build as build_material
from .nonlinear import Problem, StageHistory, solve_stage
from .seepage import SeepageBlock, SeepageResult, solve_seepage
from .state import SolverState
from .structural import GROUP_TYPES, BarGroup, BeamGroup, InterfaceGroup

log = get_logger("static")
_M = np.array([1.0, 1.0, 1.0, 0.0])
_CONT = (ElemType.T3, ElemType.T6, ElemType.Q4, ElemType.Q8)
_WT_TOL = 1e-9  # [m] a Gauss point on the water table (round-off) counts as dry


# ================================================================== result objects
@dataclass
class StageResult:
    name: str
    u: NDArray[np.float64]  # (nn, 2) reported displacement (NaN on inactive nodes)
    sig: dict[str, NDArray[np.float64]]  # continuum tag -> (ne, ngp, 4) effective stress
    reactions: NDArray[np.float64]  # (nn, 3) reactions (fx, fy, m) at prescribed DOFs
    timings: dict[str, float] = field(default_factory=dict)
    q: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ngp, nq)
    plastic: dict[str, NDArray[np.uint8]] = field(default_factory=dict)  # (ne, ngp)
    history: StageHistory | None = None
    rotation: NDArray[np.float64] | None = None  # (nn,) beam node rotations (NaN elsewhere)
    active: dict[str, NDArray[np.bool_]] = field(default_factory=dict)
    pore: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ngp) [kPa]
    beams: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, 2, 3) N, V, M
    bars: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne,) axial force N
    interfaces: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ip, 2)
    struct_flags: dict[str, NDArray[np.uint8]] = field(default_factory=dict)
    lam: float = 1.0  # load factor reached (load split)
    head: NDArray[np.float64] | None = None  # (nn,) total head of a seepage stage [m]
    flow: dict[str, float] = field(default_factory=dict)  # seepage inflow per BC set [m3/s/m]


@dataclass
class SolveResult:
    model: Model
    geom: dict[str, GeomCache]
    initial: StageResult
    stages: list[StageResult]

    def stage(self, name_or_index: str | int) -> StageResult:
        if isinstance(name_or_index, int):
            return self.stages[name_or_index]
        for s in self.stages:
            if s.name == name_or_index:
                return s
        raise KeyError(name_or_index)

    @property
    def last(self) -> StageResult:
        return self.stages[-1] if self.stages else self.initial


# ================================================================== internals
@dataclass
class _BlockMat:
    groups: list[tuple[object, NDArray[np.int64]]]  # (constitutive model, element ids)
    De: NDArray[np.float64]  # (ne, 4, 4)
    gamma: NDArray[np.float64]  # (ne,) unsaturated unit weight
    gamma_sat: NDArray[np.float64]  # (ne,)
    k0: NDArray[np.float64]  # (ne,)
    k: NDArray[np.float64] | None = None  # (ne, 2) saturated conductivity kx, ky [m/s]
    vg: NDArray[np.float64] | None = None  # (ne, 3) van Genuchten alpha, n, kr_min


@dataclass
class _Layout:
    key: tuple
    blocks: list[_BlockMat]
    linear: bool
    symmetric: bool


@dataclass
class _ContSys:
    tag: str
    ids: NDArray[np.int64]
    geom: GeomCache
    edofs: NDArray[np.int64]
    De: NDArray[np.float64]
    groups: list[tuple[object, NDArray[np.int64]]]  # positions within ids
    gamma: NDArray[np.float64]  # (n, ngp) unit weight at Gauss points
    p: NDArray[np.float64]  # (n, ngp) pore pressure


@dataclass
class _StructSys:
    group: object
    ids: NDArray[np.int64]
    edofs: NDArray[np.int64]
    p: NDArray[np.float64] | None  # interfaces: (n, ip) joint water pressure


@dataclass
class System:
    dm: DofMap
    cont: list[_ContSys]
    struct: list[_StructSys]
    pattern: SparsePattern
    linear: bool
    symmetric: bool
    key: tuple
    water: WaterCondition
    seepage: SeepageResult | None = None  # steady flow solution of a seepage stage
    p_nodal: NDArray[np.float64] | None = None  # (nn,) pore pressure >= 0 (seepage)


@dataclass
class Trial:
    sig: dict[str, NDArray[np.float64]]
    q: dict[str, NDArray[np.float64]]
    D: dict[str, NDArray[np.float64]]
    flag: dict[str, NDArray[np.uint8]]
    st: dict[str, dict[str, NDArray[np.float64]]]
    K: dict[str, NDArray[np.float64]]
    sflag: dict[str, NDArray[np.uint8]]


@dataclass
class _Factored:
    """Factorised K_ff plus the free x prescribed coupling block."""

    fact: object
    Kfp: sp.csr_matrix

    def solve(self, rhs: NDArray[np.float64]) -> NDArray[np.float64]:
        return self.fact.solve(rhs)  # type: ignore[attr-defined, no-any-return]


@dataclass
class _StageCtx:
    """Everything that defines a stage's system (re-used by the SRF driver)."""

    stage: Stage
    override: dict[int, str]
    active: dict[str, NDArray[np.bool_]]
    water: WaterCondition
    displacements: tuple[Displacement, ...]
    with_gravity: bool


# ================================================================== solver
class StaticSolver:
    def __init__(self, model: Model, extra_tractions: dict[str, tuple] | None = None) -> None:
        model.validate()
        self.model = model
        self.mesh = model.mesh
        self.blocks = model.mesh.continuum_blocks()
        if not self.blocks:
            raise ModelError("mesh has no continuum element block")
        self.extra_tractions: dict[str, tuple[tuple[str, TractionFn], ...]] = extra_tractions or {}
        t0 = time.perf_counter()
        order = model.settings.gauss_order
        self.geom = {
            b.tag: kernel(b.etype).precompute(self.mesh.coords, b.conn, model.analysis, order)
            for b in self.blocks
        }
        props = {"beam": model.liners, "bar": model.bolts, "interface": model.interfaces}
        kinds = model.structure_tags()
        self.groups: list = [
            GROUP_TYPES[b.etype](b, self.mesh.coords, props[kinds[b.tag]][b.tag], model.analysis)
            for b in self.mesh.blocks
            if b.etype not in _CONT
        ]
        self._iface_adj = self._interface_adjacency()
        self._iface_face_keys = self._interface_face_keys()
        self._model_cache: dict[str, object] = {}
        for spec in model.materials.values():  # validates parameters early, fixes nq
            self._cm(spec)
        self._elastic_fact: dict[tuple, object] = {}
        self._sys_cache: dict[tuple, System] = {}
        self.t_setup = time.perf_counter() - t0
        self.state: SolverState | None = None
        self.system: System | None = None
        self._ctx: _StageCtx | None = None
        self._D_committed: tuple[dict, dict] | None = None
        # nodal external force applied at the end of the previous stage (load split)
        self._f_applied: NDArray[np.float64] | None = None

    # ------------------------------------------------------------------ materials
    def _cm(self, spec: MaterialSpec) -> object:
        key = repr((spec.model, sorted(spec.params.items())))
        if key not in self._model_cache:
            self._model_cache[key] = build_material(spec)
        return self._model_cache[key]

    def layout(
        self, override: dict[int, str], materials: dict[str, MaterialSpec] | None = None
    ) -> _Layout:
        mats = materials if materials is not None else self.model.materials
        rm = {**self.model.region_material, **override}
        blocks = []
        linear, symmetric = True, True
        for b in self.blocks:
            De = np.empty((b.ne, 4, 4))
            g = np.empty(b.ne)
            gs = np.empty(b.ne)
            k0 = np.empty(b.ne)
            kk = np.empty((b.ne, 2))
            vg = np.empty((b.ne, 3))
            groups = []
            for r in np.unique(b.region):
                spec = mats[rm[int(r)]]
                cm = self._cm(spec)
                ids = np.flatnonzero(b.region == r)
                k0v = self.model.initial.k0
                if k0v is None:
                    k0v = cm.k0_default()  # type: ignore[attr-defined]
                De[ids] = cm.elastic_D()  # type: ignore[attr-defined]
                g[ids] = spec.gamma_unsat
                gs[ids] = spec.gamma_sat
                k0[ids] = k0v
                kk[ids] = spec.k_sat
                vg[ids] = spec.vg
                groups.append((cm, ids))
                linear &= not getattr(cm, "plastic", False)
                symmetric &= bool(getattr(cm, "symmetric", True))
            blocks.append(_BlockMat(groups, De, g, gs, k0, kk, vg))
        key = tuple(sorted(rm.items())) + tuple(
            (k, repr(sorted(mats[v].params.items()))) for k, v in sorted(rm.items())
        )
        return _Layout(key, blocks, linear, symmetric)

    @property
    def nq(self) -> int:
        n = 1
        for cm in self._model_cache.values():
            n = max(n, int(getattr(cm, "n_int", 0)))
        return n

    # ------------------------------------------------------------- topology helpers
    def _edge_owner_map(self) -> dict[tuple[int, int], tuple[int, int]]:
        out: dict[tuple[int, int], tuple[int, int]] = {}
        for bi, b in enumerate(self.blocks):
            nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
            for i in range(nc):
                a, c = b.conn[:, i], b.conn[:, (i + 1) % nc]
                for e, (p, q) in enumerate(zip(a.tolist(), c.tolist())):
                    out[(min(p, q), max(p, q))] = (bi, e)
        return out

    def _interface_adjacency(self) -> dict[str, tuple[NDArray, NDArray, NDArray, NDArray]]:
        """For each interface element: continuum (block, element) owning face 1 / face 2."""
        if not any(isinstance(g, InterfaceGroup) for g in self.groups):
            return {}
        owner = self._edge_owner_map()
        out = {}
        for g in self.groups:
            if not isinstance(g, InterfaceGroup):
                continue
            res = []
            for face in (g.f1, g.f2):
                bi = np.full(g.ne, -1)
                ei = np.full(g.ne, -1)
                for k, (p, q) in enumerate(zip(face[:, 0].tolist(), face[:, 1].tolist())):
                    hit = owner.get((min(p, q), max(p, q)))
                    if hit is not None:
                        bi[k], ei[k] = hit
                res += [bi, ei]
            out[g.tag] = tuple(res)  # type: ignore[assignment]
        return out  # type: ignore[return-value]

    def _interface_face_keys(self) -> set[tuple[int, int]]:
        keys: set[tuple[int, int]] = set()
        for g in self.groups:
            if isinstance(g, InterfaceGroup):
                for face in (g.f1, g.f2):
                    for p, q in zip(face[:, 0].tolist(), face[:, 1].tolist()):
                        keys.add((min(p, q), max(p, q)))
        return keys

    def active_masks(
        self, regions: frozenset[int] | None, structures: frozenset[str] | None
    ) -> dict[str, NDArray[np.bool_]]:
        """Activity per block; ``structures=None`` means all interfaces, no beams/bars."""
        act: dict[str, NDArray[np.bool_]] = {}
        for b in self.blocks:
            act[b.tag] = (
                np.ones(b.ne, dtype=bool)
                if regions is None
                else np.isin(b.region, np.fromiter(regions, dtype=np.int64))
            )
        beam_nodes = np.zeros(self.mesh.nn, dtype=bool)
        for g in self.groups:
            if isinstance(g, BeamGroup) and structures is not None and g.tag in structures:
                beam_nodes[g.block.conn.ravel()] = True
        for g in self.groups:
            on = (isinstance(g, InterfaceGroup) and structures is None) or (
                structures is not None and g.tag in structures
            )
            m = np.full(g.ne, on)
            if on and isinstance(g, InterfaceGroup):
                # a face is supported by an active continuum element owning it or by an
                # active beam carrying all its nodes; otherwise the joint is switched off
                b1, e1, b2, e2 = self._iface_adj[g.tag]
                for face, bi, ei in ((g.f1, b1, e1), (g.f2, b2, e2)):
                    ok = beam_nodes[face].all(axis=1) | (bi < 0)
                    for k in np.flatnonzero(bi >= 0):
                        ok[k] |= bool(act[self.blocks[bi[k]].tag][ei[k]])
                    m &= ok
            act[g.tag] = m
        return act

    def _ties(self, active: dict[str, NDArray[np.bool_]]) -> NDArray[np.int64]:
        """Partner-node pairs of inactive interface elements (full continuity there).

        A pair is tied only if no *active* interface element joins the same two nodes, so a
        partially active joint keeps its relative displacement where it is active.
        """
        pairs, keep = [], []
        for g in self.groups:
            if not isinstance(g, InterfaceGroup):
                continue
            pr = np.stack([g.f1, g.f2], axis=-1).reshape(-1, 2)  # (ne*npe, 2)
            on = np.repeat(active[g.tag], g.npe)
            pairs.append(pr[~on])
            keep.append(pr[on])
        if not pairs:
            return np.empty((0, 2), np.int64)
        tie = np.vstack(pairs)
        tie = tie[tie[:, 0] != tie[:, 1]]
        act = np.vstack(keep)
        if act.size and tie.size:
            nn = self.mesh.nn
            k_t = np.minimum(tie[:, 0], tie[:, 1]) * nn + np.maximum(tie[:, 0], tie[:, 1])
            k_a = np.minimum(act[:, 0], act[:, 1]) * nn + np.maximum(act[:, 0], act[:, 1])
            tie = tie[~np.isin(k_t, k_a)]
        return np.unique(tie, axis=0) if tie.size else tie

    # ------------------------------------------------------------- system build
    def build_system(
        self,
        lay: _Layout,
        active: dict[str, NDArray[np.bool_]],
        water: WaterCondition,
        displacements: tuple[Displacement, ...],
    ) -> System:
        key = (
            lay.key,
            tuple((k, v.tobytes()) for k, v in sorted(active.items())),
            water.key(),
            displacements,
        )
        if key in self._sys_cache:
            return self._sys_cache[key]
        beam_nodes = [
            g.block.conn[active[g.tag]].ravel() for g in self.groups if isinstance(g, BeamGroup)
        ]
        bn = np.unique(np.concatenate(beam_nodes)) if beam_nodes else np.empty(0, np.int64)
        dm = DofMap(self.mesh, active, bn, self.model.fixities, displacements, self._ties(active))
        seep, p_nodal = None, None
        if water.mode == "seepage":
            seep = self._solve_seepage(lay, active, water)
            p_nodal = np.maximum(np.nan_to_num(seep.pressure, nan=0.0), 0.0)
        cont = []
        for b, bm in zip(self.blocks, lay.blocks):
            ids = np.flatnonzero(active[b.tag])
            g = self.geom[b.tag]
            if ids.size == b.ne:  # fully active block: no copies
                gs = g
            else:
                gs = GeomCache(B=g.B[ids], wdet=g.wdet[ids], N=g.N, xg=g.xg[ids])
            ed = dm.node_dofs[b.conn[ids]][:, :, :2].reshape(ids.size, -1)
            groups = []
            for cm, gids in bm.groups:
                pos = gids if ids.size == b.ne else np.flatnonzero(np.isin(ids, gids))
                if pos.size:
                    groups.append((cm, pos))
            if seep is not None:
                p = (
                    np.maximum(seep.gp_pressure(b.tag), 0.0)
                    if b.tag in seep.gp_head
                    else np.zeros(gs.xg.shape[:2])
                )
                below = p > GAMMA_W * _WT_TOL
            else:
                h = water.head(gs.xg[..., 0])
                p = GAMMA_W * np.maximum(h - gs.xg[..., 1], 0.0)
                below = h - gs.xg[..., 1] > _WT_TOL
            gam = np.where(below, bm.gamma_sat[ids][:, None], bm.gamma[ids][:, None])
            De = bm.De if ids.size == b.ne else bm.De[ids]
            cont.append(_ContSys(b.tag, ids, gs, ed, De, groups, gam, p))
        struct = []
        linear, symmetric = lay.linear, lay.symmetric
        for g in self.groups:
            ids = np.flatnonzero(active[g.tag])
            if ids.size == 0:
                continue
            p = None
            if isinstance(g, InterfaceGroup):
                xi = g.xip[ids]
                if p_nodal is not None:
                    p = p_nodal[g.f1[ids]]
                else:
                    p = GAMMA_W * np.maximum(water.head(xi[..., 0]) - xi[..., 1], 0.0)
                linear = False
                symmetric &= g.symmetric
            elif isinstance(g, BarGroup):
                linear = False
            struct.append(_StructSys(g, ids, g.edofs(dm.node_dofs, ids), p))
        pattern = SparsePattern.build([c.edofs for c in cont] + [s.edofs for s in struct], dm.ndof)
        sysm = System(dm, cont, struct, pattern, linear, symmetric, key, water, seep, p_nodal)
        self._sys_cache = {key: sysm}  # keep the latest only
        return sysm

    def _set_nodes(self, name: str) -> NDArray[np.int64]:
        if name in self.mesh.node_sets:
            return self.mesh.nodes(name)
        return np.unique(self.mesh.edges(name))

    def _solve_seepage(
        self, lay: _Layout, active: dict[str, NDArray[np.bool_]], water: WaterCondition
    ) -> SeepageResult:
        blocks = []
        for b, bm in zip(self.blocks, lay.blocks):
            ids = np.flatnonzero(active[b.tag])
            if ids.size:
                assert bm.k is not None and bm.vg is not None
                blocks.append(SeepageBlock(b.tag, b.conn[ids], b.etype, bm.k[ids], bm.vg[ids]))
        heads = [(h.node_set, self._set_nodes(h.node_set), h.head) for h in water.head_bcs]
        fluxes = [(self.mesh.edges(f.edge_set), f.q) for f in water.flux_bcs]
        faces = [(nm, self._set_nodes(nm)) for nm in water.seepage_faces]
        res = solve_seepage(self.mesh, blocks, heads, fluxes, faces, self.model.analysis)
        if not res.converged:
            log.warning("seepage did not converge; pore pressures may be inaccurate")
        return res

    # ------------------------------------------------------------- integration
    def integrate(
        self, state: SolverState, du: NDArray[np.float64], sysm: System, lay: _Layout
    ) -> tuple[Trial, NDArray[np.float64]]:
        sig, q, D, flag = {}, {}, {}, {}
        fint = np.zeros(sysm.dm.ndof)
        for c in sysm.cont:
            if c.ids.size == 0:
                continue
            deps = strain(c.geom, du[c.edofs])
            s_n = state.sig[c.tag][c.ids]
            q_n = state.q[c.tag][c.ids]
            if lay.linear:
                s_out = s_n + np.einsum("eij,egj->egi", c.De, deps, optimize=True)
                q_out, D_out, f_out = q_n, c.De, state.plastic[c.tag][c.ids]
            else:
                ngp = c.geom.ngp
                n = c.ids.size
                s_out = np.empty_like(s_n)
                q_out = q_n.copy()
                D_out = np.empty((n, ngp, 4, 4))
                f_out = np.zeros((n, ngp), dtype=np.uint8)
                for cm, pos in c.groups:
                    ni = cm.n_int  # type: ignore[attr-defined]
                    nq = max(ni, 1)
                    sg, qg, Dg, fg = cm.integrate(  # type: ignore[attr-defined]
                        s_n[pos].reshape(-1, 4),
                        deps[pos].reshape(-1, 4),
                        q_n[pos][..., :nq].reshape(-1, nq),
                    )
                    s_out[pos] = sg.reshape(pos.size, ngp, 4)
                    if ni:
                        q_out[pos, :, :ni] = qg.reshape(pos.size, ngp, ni)
                    D_out[pos] = Dg.reshape(pos.size, ngp, 4, 4)
                    f_out[pos] = fg.reshape(pos.size, ngp)
            sig[c.tag], q[c.tag], D[c.tag], flag[c.tag] = s_out, q_out, D_out, f_out
            fint += np.bincount(
                c.edofs.ravel(), internal_force(c.geom, s_out).ravel(), minlength=sysm.dm.ndof
            )
        st, K, sflag = {}, {}, {}
        for s in sysm.struct:
            g = s.group
            tst, fe, Ke, fl = g.integrate(state.struct[g.tag], s.ids, du[s.edofs], s.p)
            st[g.tag], K[g.tag], sflag[g.tag] = tst, Ke, fl
            fint += np.bincount(s.edofs.ravel(), fe.ravel(), minlength=sysm.dm.ndof)
        return Trial(sig, q, D, flag, st, K, sflag), fint

    def _fint(self, state: SolverState, sysm: System, lay: _Layout) -> NDArray[np.float64]:
        return self.integrate_committed(state, sysm, lay)[1]

    def integrate_committed(self, state: SolverState, sysm: System, lay: _Layout):
        return self.integrate(
            state, np.zeros(sysm.dm.ndof), sysm, _Layout(lay.key, lay.blocks, True, True)
        )

    # ------------------------------------------------------------------ assembly
    def _stiffness(self, sysm: System, D: dict, K: dict) -> sp.csr_matrix:
        kes = [element_stiffness(c.geom, D[c.tag]) for c in sysm.cont]
        kes += [K[s.group.tag] for s in sysm.struct]
        return sysm.pattern.assemble(kes)

    def _tangent_record(self, sysm: System, t: Trial) -> tuple[dict, dict]:
        """Committed tangents keyed by tag, with the element ids they belong to."""
        D = {c.tag: (c.ids, t.D[c.tag]) for c in sysm.cont if c.tag in t.D}
        K = {s.group.tag: (s.ids, t.K[s.group.tag]) for s in sysm.struct}
        return D, K

    def _tangent_for(self, sysm: System, rec: tuple[dict, dict]) -> tuple[dict, dict]:
        """Re-index recorded tangents to the active set of ``sysm`` (elastic elsewhere)."""
        Drec, Krec = rec
        D, K = {}, {}
        for c in sysm.cont:
            if not c.ids.size:
                continue
            ngp = c.geom.ngp
            out = np.broadcast_to(c.De[:, None], (c.ids.size, ngp, 4, 4)).copy()
            if c.tag in Drec:
                ids0, D0 = Drec[c.tag]
                if D0.ndim == 3:
                    D0 = np.broadcast_to(D0[:, None], (ids0.size, ngp, 4, 4))
                pos = np.searchsorted(ids0, c.ids)
                pos = np.clip(pos, 0, max(ids0.size - 1, 0))
                hit = ids0.size > 0
                if hit:
                    m = ids0[pos] == c.ids
                    out[m] = D0[pos[m]]
            D[c.tag] = out
        for s_ in sysm.struct:
            tag = s_.group.tag
            out = s_.group.elastic_K(s_.ids)
            if tag in Krec:
                ids0, K0 = Krec[tag]
                if ids0.size:
                    pos = np.clip(np.searchsorted(ids0, s_.ids), 0, ids0.size - 1)
                    m = ids0[pos] == s_.ids
                    out[m] = K0[pos[m]]
            K[tag] = out
        return D, K

    def _elastic_DK(self, sysm: System) -> tuple[dict, dict]:
        D = {c.tag: c.De for c in sysm.cont}
        K = {s.group.tag: s.group.elastic_K(s.ids) for s in sysm.struct}
        return D, K

    def _factor_free(self, sysm: System, Kmat: sp.csr_matrix, symmetric: bool) -> object:
        f, p = sysm.dm.free, sysm.dm.prescribed
        Kf = Kmat[f]
        fact = factorize(Kf[:, f], self.model.settings.linear_solver, symmetric)
        return _Factored(fact, Kf[:, p])

    def external_force(
        self, sysm: System, ctx: _StageCtx, stage_name: str | None = None
    ) -> NDArray[np.float64]:
        dm = sysm.dm
        nd = dm.ndof
        f = np.zeros(nd)
        if ctx.with_gravity:
            for c in sysm.cont:
                if c.ids.size == 0:
                    continue
                fe = np.zeros((c.ids.size, c.edofs.shape[1]))
                fe[:, 1::2] = -np.einsum("eg,eg,gn->en", c.gamma, c.geom.wdet, c.geom.N)
                f += np.bincount(c.edofs.ravel(), fe.ravel(), minlength=nd)
            for s in sysm.struct:
                f += np.bincount(s.edofs.ravel(), s.group.body_force(s.ids).ravel(), minlength=nd)
        if ctx.water.mode != "none":
            f += self._water_forces(sysm, ctx.water)
        loads = ctx.stage.loads
        extra = self.extra_tractions.get(stage_name or ctx.stage.name, ())
        if loads or extra:
            f += assemble_nodal_loads(
                self.mesh, dm.node_dofs, nd, loads, self.model.analysis, extra
            )
        return f

    def _water_forces(self, sysm: System, water: WaterCondition) -> NDArray[np.float64]:
        dm = sysm.dm
        nd = dm.ndof
        f = np.zeros(nd)
        # int B^T m p (moves to the external side in the effective-stress formulation)
        for c in sysm.cont:
            if c.ids.size and np.any(c.p > 0):
                fe = internal_force(c.geom, c.p[..., None] * _M)
                f += np.bincount(c.edofs.ravel(), fe.ravel(), minlength=nd)
        for s in sysm.struct:
            if s.p is not None and np.any(s.p > 0):
                f += np.bincount(
                    s.edofs.ravel(), s.group.pore_force(s.ids, s.p).ravel(), minlength=nd
                )
        # water pressure on the exposed boundary of the active continuum
        edges, inner = self._exposed_edges(sysm)
        if edges.size:
            X = self.mesh.coords
            if sysm.p_nodal is not None:
                sel = (sysm.p_nodal[edges] > 0).any(axis=1)
            else:
                hmax = water.head(X[edges[:, :2], 0]).max(axis=1)
                sel = hmax > X[edges[:, :2], 1].min(axis=1)
            if np.any(sel):

                def pfun(x: NDArray[np.float64]) -> NDArray[np.float64]:
                    return GAMMA_W * np.maximum(water.head(x[:, 0]) - x[:, 1], 0.0)

                pn = None if sysm.p_nodal is None else sysm.p_nodal[edges[sel]]
                fe = pressure_edge_forces(
                    X, edges[sel], inner[sel], pfun, self.model.analysis, p_nodal=pn
                )
                ed = dm.node_dofs[edges[sel]][:, :, :2]
                ok = ed >= 0
                fw = np.bincount(ed[ok], fe[ok], minlength=nd)
                # on prescribed DOFs the boundary water load only shifts the reaction;
                # leaving it out makes reported reactions total (effective + water)
                fw[dm.prescribed] = 0.0
                f += fw
        return f

    def _exposed_edges(self, sysm: System) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
        X = self.mesh.coords
        keys, rows, cents = [], [], []
        nn = self.mesh.nn
        for c, b in zip(sysm.cont, self.blocks):
            if c.ids.size == 0:
                continue
            conn = b.conn[c.ids]
            nc = 4 if b.etype in (ElemType.Q4, ElemType.Q8) else 3
            quad = b.etype in (ElemType.T6, ElemType.Q8)
            cen = X[conn[:, :nc]].mean(axis=1)
            for i in range(nc):
                a, e = conn[:, i], conn[:, (i + 1) % nc]
                r = np.column_stack([a, e, conn[:, nc + i]]) if quad else np.column_stack([a, e])
                keys.append(np.minimum(a, e) * nn + np.maximum(a, e))
                rows.append(r)
                cents.append(cen)
        if not keys:
            return np.empty((0, 2), np.int64), np.empty((0, 2))
        k = np.concatenate(keys)
        width = max(r.shape[1] for r in rows)
        if any(r.shape[1] != width for r in rows):
            raise ModelError("mixed linear/quadratic continuum blocks are not supported")
        R = np.vstack(rows)
        C = np.vstack(cents)
        u, inv, cnt = np.unique(k, return_inverse=True, return_counts=True)
        once = cnt[inv.ravel()] == 1
        if self._iface_face_keys:
            fk = np.array([a * nn + b for a, b in self._iface_face_keys])
            once &= ~np.isin(k, fk)
        return R[once], C[once]

    # ------------------------------------------------------------------ state
    def zero_state(self) -> SolverState:
        nq = self.nq
        return SolverState(
            u=np.zeros((self.mesh.nn, 3)),
            sig={b.tag: np.zeros((b.ne, self.geom[b.tag].ngp, 4)) for b in self.blocks},
            q={b.tag: np.zeros((b.ne, self.geom[b.tag].ngp, nq)) for b in self.blocks},
            plastic={
                b.tag: np.zeros((b.ne, self.geom[b.tag].ngp), dtype=np.uint8) for b in self.blocks
            },
            struct={g.tag: g.zero_state() for g in self.groups},
            struct_flag={g.tag: np.zeros((g.ne, 1), dtype=np.uint8) for g in self.groups},
            active={
                **{b.tag: np.zeros(b.ne, dtype=bool) for b in self.blocks},
                **{g.tag: np.zeros(g.ne, dtype=bool) for g in self.groups},
            },
            u_ref=np.zeros((self.mesh.nn, 3)),
        )

    def _gather_u(self, state: SolverState, dm: DofMap) -> NDArray[np.float64]:
        u = np.zeros(dm.ndof)
        for comp in range(3):
            d = dm.node_dofs[:, comp]
            m = d >= 0
            u[d[m]] = state.u[m, comp]
        return u

    def _scatter_u(self, du: NDArray[np.float64], dm: DofMap) -> NDArray[np.float64]:
        out = np.zeros((self.mesh.nn, 3))
        for comp in range(3):
            d = dm.node_dofs[:, comp]
            m = d >= 0
            out[m, comp] = du[d[m]]
        return out

    def apply_activation(self, state: SolverState, active: dict, dm: DofMap) -> None:
        """Reset newly (de)activated elements; datum for newly active nodes."""
        used_before = self._used_nodes(state.active)
        for b in self.blocks:
            new = active[b.tag] & ~state.active[b.tag]
            gone = ~active[b.tag] & state.active[b.tag]
            for arr in (state.sig[b.tag], state.q[b.tag]):
                arr[new | gone] = 0.0
            state.plastic[b.tag][new | gone] = 0
        for g in self.groups:
            new = np.flatnonzero(active[g.tag] & ~state.active[g.tag])
            gone = np.flatnonzero(~active[g.tag] & state.active[g.tag])
            if gone.size:
                g.activate(state.struct[g.tag], gone)
                for v in state.struct[g.tag].values():
                    v[gone] = 0.0
            if new.size:
                g.activate(state.struct[g.tag], new)
                if isinstance(g, InterfaceGroup):
                    self._interface_initial_traction(state, g, new)
        used_now = dm.used_nodes
        fresh = used_now & ~used_before
        assert state.u_ref is not None
        state.u_ref[fresh] = state.u[fresh]
        state.active = {k: v.copy() for k, v in active.items()}

    def _interface_initial_traction(
        self, state: SolverState, g: InterfaceGroup, ids: NDArray[np.int64]
    ) -> None:
        """Newly activated joints take over the traction of the adjacent (stressed) soil,
        so switching an interface on does not release the stresses across it."""
        if not any(np.any(v) for v in state.sig.values()):
            return
        from ..post.recovery import nodal_average

        live = {k: v for k, v in state.sig.items()}
        nodal = np.nan_to_num(nodal_average(self.mesh, live))
        # face-2 nodes of a new joint are copies: use the stress at the face-1 partners if
        # face 2 has no stressed element yet (e.g. first activation of a wall interface)
        f2 = nodal[g.f2[ids]]
        f1 = nodal[g.f1[ids]]
        pick = np.where((np.abs(f2).sum(axis=-1) > 0)[..., None], f2, f1)
        state.struct[g.tag]["t"][ids] = g.traction_from_stress(ids, pick)

    def _applied_force(
        self, f_ext: NDArray[np.float64], dm: DofMap, lam: float
    ) -> NDArray[np.float64]:
        """External force in equilibrium at the end of a stage that stopped at ``lam``:
        the previous stage's applied force plus ``lam`` times the change (``f0`` of the
        stage driver is an internal force and carries no net load). Also records it."""
        f_eq = f_ext
        if lam < 1.0 and self._f_applied is not None:
            prev = np.zeros(dm.ndof)
            for comp in range(3):
                d = dm.node_dofs[:, comp]
                m = d >= 0
                np.add.at(prev, d[m], self._f_applied[m, comp])
            f_eq = lam * f_ext + (1.0 - lam) * prev
        self._f_applied = np.nan_to_num(dm.nodal(f_eq, comps=3, owners_only=True))
        return f_eq

    def _used_nodes(self, active: dict) -> NDArray[np.bool_]:
        used = np.zeros(self.mesh.nn, dtype=bool)
        for b in self.mesh.blocks:
            m = active.get(b.tag)
            if m is not None and m.any():
                used[np.unique(b.conn[m])] = True
        return used

    def project(self, state: SolverState, sysm: System, lay: _Layout) -> None:
        """Return committed stresses onto the yield surfaces of ``lay`` (du = 0)."""
        if lay.linear:
            return
        trial, _ = self.integrate(state, np.zeros(sysm.dm.ndof), sysm, lay)
        self._commit_trial(state, sysm, trial)
        self._D_committed = self._tangent_record(sysm, trial)

    def _commit_trial(self, state: SolverState, sysm: System, t: Trial) -> None:
        for c in sysm.cont:
            if c.tag in t.sig:
                state.sig[c.tag][c.ids] = t.sig[c.tag]
                state.q[c.tag][c.ids] = t.q[c.tag]
                state.plastic[c.tag][c.ids] = t.flag[c.tag]
        for s in sysm.struct:
            tag = s.group.tag
            for k, v in t.st[tag].items():
                state.struct[tag][k][s.ids] = v
            fl = t.sflag[tag]
            if state.struct_flag[tag].shape[1] != fl.shape[1]:
                state.struct_flag[tag] = np.zeros((s.group.ne, fl.shape[1]), dtype=np.uint8)
            state.struct_flag[tag][s.ids] = fl

    # ------------------------------------------------------------- stage solve
    def solve_increment(
        self,
        state: SolverState,
        sysm: System,
        lay: _Layout,
        f_ext: NDArray[np.float64],
        du_presc: NDArray[np.float64],
        settings: SolverSettings | None = None,
        lam_end: float = 1.0,
    ) -> tuple[SolverState, StageHistory]:
        """Solve one stage from ``state`` (updated in place; on failure it holds the last
        converged step and :class:`NonConvergence` is raised)."""
        dm = sysm.dm
        _, f0 = self.integrate_committed(state, sysm, lay)
        base = state.commit()
        committed = base
        u_start = state.u.copy()
        D_comm = self._D_committed

        def integrate(du: NDArray[np.float64]) -> tuple[Trial, NDArray[np.float64]]:
            return self.integrate(committed, du, sysm, lay)

        def factor(kind: str, trial: object | None) -> object:
            if kind == "elastic" or (kind == "committed" and D_comm is None):
                key = (sysm.key, dm.free.size, hash(dm.free.tobytes()))
                fk = self._elastic_fact.get(key)
                if fk is None:
                    D, K = self._elastic_DK(sysm)
                    fk = self._factor_free(sysm, self._stiffness(sysm, D, K), True)
                    self._elastic_fact = {key: fk}
                return fk
            if kind == "tangent":
                t: Trial = trial  # type: ignore[assignment]
                D, K = t.D, t.K
            else:
                D, K = self._tangent_for(sysm, D_comm)  # type: ignore[arg-type]
            return self._factor_free(sysm, self._stiffness(sysm, D, K), sysm.symmetric)

        def commit(trial: object, du_total: NDArray[np.float64]) -> None:
            nonlocal committed, D_comm
            t: Trial = trial  # type: ignore[assignment]
            new = base.commit()
            new.u = u_start + self._scatter_u(du_total, dm)
            self._commit_trial(new, sysm, t)
            committed = new
            D_comm = self._tangent_record(sysm, t)

        prob = Problem(dm.ndof, dm.free, dm.prescribed, integrate, factor, commit)
        try:
            _, _, hist = solve_stage(
                prob, f_ext, f0, du_presc, settings or self.model.settings, sysm.linear, lam_end
            )
        finally:
            self._D_committed = D_comm
            for k in ("u", "sig", "q", "plastic", "struct", "struct_flag"):
                setattr(state, k, getattr(committed, k))
        return state, hist

    # ------------------------------------------------------------------ results
    def _result(
        self,
        name: str,
        state: SolverState,
        sysm: System,
        lay: _Layout,
        f_ext: NDArray,
        timings: dict,
        history: StageHistory | None = None,
        lam: float = 1.0,
    ) -> StageResult:
        dm = sysm.dm
        _, fint = self.integrate_committed(state, sysm, lay)
        r = np.zeros(dm.ndof)
        # f_ext here is the external force actually applied at the end of the stage (see
        # _applied_force for load-split stages)
        r[dm.prescribed] = (fint - f_ext)[dm.prescribed]
        used = dm.used_nodes
        u = state.reported_u()[:, :2].copy()
        u[~used] = np.nan
        rot = np.full(self.mesh.nn, np.nan)
        has_rot = dm.node_dofs[:, 2] >= 0
        rot[has_rot] = state.reported_u()[has_rot, 2]
        pore = {}
        for c in sysm.cont:
            pp = np.full(state.sig[c.tag].shape[:2], np.nan)
            pp[c.ids] = c.p
            pore[c.tag] = pp
        beams, bars, ifs = {}, {}, {}
        for g in self.groups:
            act = state.active[g.tag]
            if isinstance(g, BeamGroup):
                v = g.end_forces(state.struct[g.tag]["f"])
                v[~act] = np.nan
                beams[g.tag] = v
            elif isinstance(g, BarGroup):
                v = state.struct[g.tag]["N"].copy()
                v[~act] = np.nan
                bars[g.tag] = v
            else:
                v = state.struct[g.tag]["t"].copy()
                v[~act] = np.nan
                ifs[g.tag] = v
        return StageResult(
            name=name,
            u=u,
            sig={k: v.copy() for k, v in state.sig.items()},
            reactions=np.nan_to_num(dm.nodal(r, comps=3, owners_only=True)),
            timings=timings,
            q={k: v.copy() for k, v in state.q.items()},
            plastic={k: v.copy() for k, v in state.plastic.items()},
            history=history,
            rotation=rot,
            active={k: v.copy() for k, v in state.active.items()},
            pore=pore,
            beams=beams,
            bars=bars,
            interfaces=ifs,
            struct_flags={k: v.copy() for k, v in state.struct_flag.items()},
            lam=lam,
            head=None if sysm.seepage is None else sysm.seepage.head.copy(),
            flow={} if sysm.seepage is None else dict(sysm.seepage.inflow),
        )

    # --------------------------------------------------------------------- run
    def _with_gravity(self) -> bool:
        init = self.model.initial
        return init.mode in ("gravity", "k0_field") or (init.mode == "field" and init.gravity)

    def initial_state(self) -> tuple[SolverState, StageResult]:
        model = self.model
        init = model.initial
        lay = self.layout({})
        state = self.zero_state()
        active = self.active_masks(init.active_regions, init.active_structures)
        sysm = self.build_system(lay, active, init.water, model.displacements)
        self.apply_activation(state, active, sysm.dm)
        ctx = _StageCtx(Stage("initial"), {}, active, init.water, model.displacements,
                        init.mode in ("gravity", "k0_field"))  # fmt: skip
        timings: dict[str, float] = {"setup": self.t_setup}
        hist = None
        f_ext = (
            self.external_force(sysm, ctx)
            if init.mode in ("gravity", "k0_field")
            else np.zeros(sysm.dm.ndof)
        )
        t1 = time.perf_counter()
        if init.mode == "gravity":
            state, hist = self.solve_increment(
                state, sysm, lay, f_ext, np.zeros(sysm.dm.prescribed.size)
            )
            state.u[:] = 0.0  # displacements of the gravity stage are discarded
            state.u_ref = np.zeros_like(state.u)
        elif init.mode in ("k0_field", "field"):
            self._assign_initial_stress(state, sysm, lay, ctx)
            self.project(state, sysm, lay)
            if init.mode == "k0_field":
                _, fint = self.integrate_committed(state, sysm, lay)
                res = fint - f_ext
                fr = sysm.dm.free
                rel = np.linalg.norm(res[fr]) / max(np.linalg.norm(f_ext[fr]), 1e-30)
                if rel > 1e-3:
                    log.warning(
                        "K0 field is not in equilibrium with self-weight (relative residual "
                        "%.2e); the first stage will redistribute it. Use mode='gravity' "
                        "for non-horizontal ground.",
                        rel,
                    )
        timings["solve"] = time.perf_counter() - t1
        self.system, self._ctx, self._layout = sysm, ctx, lay
        f_ext = self._applied_force(f_ext, sysm.dm, 1.0)
        return state, self._result("initial", state, sysm, lay, f_ext, timings, hist)

    def _assign_initial_stress(
        self, state: SolverState, sysm: System, lay: _Layout, ctx: _StageCtx
    ) -> None:
        init = self.model.initial
        if init.mode == "field":
            s0 = np.asarray(init.field, dtype=float)
            for c in sysm.cont:
                state.sig[c.tag][c.ids] = s0
        else:
            surf = init.surface_y
            if surf is None:
                surf = float(self.mesh.coords[:, 1].max())
            xg, yr, gam, k0s = [], [], [], []
            for c, b in zip(sysm.cont, self.blocks):
                ye = self.mesh.coords[b.conn[c.ids], 1]
                xg.append(c.geom.xg)
                yr.append(np.column_stack([ye.min(axis=1), ye.max(axis=1)]))
                gam.append(c.gamma.mean(axis=1))  # saturated below the water line
                k0s.append(np.ones(c.ids.size))
            total = k0_stress_field(xg, yr, gam, k0s, surf)
            for c, sv, bm in zip(sysm.cont, total, lay.blocks):
                sve = sv[..., 1] + c.p  # effective vertical stress (tension +)
                s = np.zeros_like(sv)
                k0 = bm.k0[c.ids][:, None]
                s[..., 1] = sve
                s[..., 0] = s[..., 2] = k0 * sve
                state.sig[c.tag][c.ids] = s
        # interfaces start with the traction of the adjacent soil
        for s in sysm.struct:
            if isinstance(s.group, InterfaceGroup):
                self._interface_initial_traction(state, s.group, s.ids)

    def stage_context(self, st: Stage, override: dict[int, str]) -> _StageCtx:
        active = self.active_masks(st.active_regions, frozenset(st.active_structures))
        if not any(active[b.tag].any() for b in self.blocks):
            raise ModelError(f"stage '{st.name}' has no active continuum element")
        disp = (*self.model.displacements, *st.displacements)
        return _StageCtx(st, override, active, st.water, disp, self._with_gravity())

    def solve_stage_ctx(
        self,
        state: SolverState,
        ctx: _StageCtx,
        lay: _Layout,
        settings: SolverSettings | None = None,
    ) -> tuple[SolverState, System, NDArray[np.float64], StageHistory]:
        sysm = self.build_system(lay, ctx.active, ctx.water, ctx.displacements)
        self.apply_activation(state, ctx.active, sysm.dm)
        f_ext = self.external_force(sysm, ctx)
        dm = sysm.dm
        du_presc = dm.prescribed_values - self._gather_u(state, dm)[dm.prescribed]
        if ctx.stage.reset_displacements:
            state.u_ref = state.u.copy()
        state, hist = self.solve_increment(
            state, sysm, lay, f_ext, du_presc, settings, ctx.stage.load_split
        )
        return state, sysm, f_ext, hist

    def run(self, stop_after: int | None = None) -> SolveResult:
        """Initial state + stages ``0..stop_after`` (all stages by default)."""
        model = self.model
        state, initial = self.initial_state()
        results = []
        override: dict[int, str] = {}
        lay = self._layout
        assert lay is not None
        stages = model.stages if stop_after is None else model.stages[: stop_after + 1]
        for st in stages:
            t1 = time.perf_counter()
            if st.material_override != override:
                override = dict(st.material_override)
                lay = self.layout(override)
                self._D_committed = None
                prev = self._ctx
                assert prev is not None
                proj_sys = self.build_system(lay, state.active, prev.water, prev.displacements)
                self.project(state, proj_sys, lay)
            ctx = self.stage_context(st, override)
            state, sysm, f_ext, hist = self.solve_stage_ctx(state, ctx, lay)
            timings = {"solve": time.perf_counter() - t1}
            f_eq = self._applied_force(f_ext, sysm.dm, st.load_split)
            results.append(
                self._result(st.name, state, sysm, lay, f_eq, timings, hist, st.load_split)
            )
            self.system, self._ctx, self._layout = sysm, ctx, lay
        self.state = state
        return SolveResult(model=model, geom=self.geom, initial=initial, stages=results)


def solve(model: Model, extra_tractions: dict[str, tuple] | None = None) -> SolveResult:
    """Solve ``model``: initial stress state followed by every stage in order."""
    return StaticSolver(model, extra_tractions).run()


__all__ = ["Analysis", "SolveResult", "StageResult", "StaticSolver", "Trial", "solve", "Stage"]
