"""Static stage driver: initial stress + sequence of (elasto-plastic) stages.

Every stage is solved incrementally from the committed state with the Newton-Raphson
family in :mod:`.nonlinear`:

    R(u, lam) = lam f_ext + (1 - lam) f0 - f_int(sigma(u))

Purely elastic stages take a single step and reuse the elastic factorisation across
stages. When a stage changes materials (``material_override``) the committed stresses
are first projected onto the new yield surfaces; the resulting out-of-balance force is
applied gradually through ``f0`` (same mechanism as excavation unloading).

Element activation/deactivation and structural elements arrive in Faz 3.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from numpy.typing import NDArray

from ..core.enums import Analysis
from ..core.errors import ModelError
from ..core.log import get_logger
from ..model.materials import MaterialSpec
from ..model.model import Model
from ..model.stages import SolverSettings, Stage
from .assembly import (
    DofMap,
    SparsePattern,
    element_stiffness,
    internal_force,
    scatter_vector,
    strain,
)
from .elements import kernel
from .elements.base import GeomCache
from .linsolve import factorize
from .loads import (
    TractionFn,
    assemble_nodal_loads,
    gravity_element_forces,
    k0_stress_field,
)
from .materials import build as build_material
from .nonlinear import Problem, StageHistory, solve_stage
from .state import SolverState

log = get_logger("static")


@dataclass
class StageResult:
    name: str
    u: NDArray[np.float64]  # (nn, 2) reported displacement (NaN on DOF-less nodes)
    sig: dict[str, NDArray[np.float64]]  # block tag -> (ne, ngp, 4)
    reactions: NDArray[np.float64]  # (nn, 2) nodal reactions at prescribed DOFs
    timings: dict[str, float] = field(default_factory=dict)
    q: dict[str, NDArray[np.float64]] = field(default_factory=dict)  # (ne, ngp, nq)
    plastic: dict[str, NDArray[np.uint8]] = field(default_factory=dict)  # (ne, ngp)
    history: StageHistory | None = None


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


@dataclass
class _BlockMat:
    groups: list[tuple[object, NDArray[np.int64]]]  # (constitutive model, element ids)
    De: NDArray[np.float64]  # (ne, 4, 4) elastic matrices
    gamma: NDArray[np.float64]  # (ne,)
    k0: NDArray[np.float64]  # (ne,)


@dataclass
class _Layout:
    key: tuple
    blocks: list[_BlockMat]
    linear: bool
    symmetric: bool


@dataclass
class Trial:
    sig: dict[str, NDArray[np.float64]]
    q: dict[str, NDArray[np.float64]]
    D: dict[str, NDArray[np.float64]]
    flag: dict[str, NDArray[np.uint8]]


@dataclass
class _Factored:
    """Factorised K_ff plus the free x prescribed coupling block."""

    fact: object
    Kfp: sp.csr_matrix

    def solve(self, rhs: NDArray[np.float64]) -> NDArray[np.float64]:
        return self.fact.solve(rhs)  # type: ignore[attr-defined, no-any-return]


class StaticSolver:
    def __init__(self, model: Model, extra_tractions: dict[str, tuple] | None = None) -> None:
        model.validate()
        self.model = model
        self.mesh = model.mesh
        self.blocks = model.mesh.continuum_blocks()
        if len(self.blocks) != len(model.mesh.blocks):
            raise NotImplementedError("structural element blocks are implemented in Faz 3")
        if not self.blocks:
            raise ModelError("mesh has no continuum element block")
        # extra (analytic) tractions per stage name, used by verification tests
        self.extra_tractions: dict[str, tuple[tuple[str, TractionFn], ...]] = extra_tractions or {}
        t0 = time.perf_counter()
        order = model.settings.gauss_order
        self.geom = {
            b.tag: kernel(b.etype).precompute(self.mesh.coords, b.conn, model.analysis, order)
            for b in self.blocks
        }
        self.dofmap = DofMap(self.mesh, None, None, model.fixities, model.displacements)
        self.edofs = [self.dofmap.element_dofs(b) for b in self.blocks]
        self.pattern = SparsePattern.build(self.edofs, self.dofmap.ndof)
        self._model_cache: dict[str, object] = {}
        for spec in model.materials.values():  # validates parameters early, fixes nq
            self._cm(spec)
        self._elastic_fact: dict[tuple, object] = {}
        self._base_dofmap = self.dofmap
        self.t_setup = time.perf_counter() - t0
        # mutable solution state (set in run / used by the SRF driver)
        self.state: SolverState | None = None
        self._D_committed: dict[str, NDArray[np.float64]] | None = None
        self._layout: _Layout | None = None

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
            k0 = np.empty(b.ne)
            groups = []
            for r in np.unique(b.region):
                spec = mats[rm[int(r)]]
                cm = self._cm(spec)
                ids = np.flatnonzero(b.region == r)
                k0v = (
                    self.model.initial.k0 if self.model.initial.k0 is not None else cm.k0_default()
                )  # type: ignore[attr-defined]
                De[ids] = cm.elastic_D()  # type: ignore[attr-defined]
                g[ids] = spec.gamma_unsat
                k0[ids] = k0v
                groups.append((cm, ids))
                linear &= not getattr(cm, "plastic", False)
                symmetric &= bool(getattr(cm, "symmetric", True))
            blocks.append(_BlockMat(groups, De, g, k0))
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

    # ------------------------------------------------------------- integration
    def integrate(
        self, state: SolverState, du: NDArray[np.float64], lay: _Layout
    ) -> tuple[Trial, NDArray[np.float64]]:
        sig, q, D, flag = {}, {}, {}, {}
        for b, ed, bm in zip(self.blocks, self.edofs, lay.blocks):
            geom = self.geom[b.tag]
            deps = strain(geom, du[ed])
            s_n = state.sig[b.tag]
            q_n = state.q[b.tag]
            if lay.linear:
                sig[b.tag] = s_n + np.einsum("eij,egj->egi", bm.De, deps, optimize=True)
                q[b.tag] = q_n
                D[b.tag] = bm.De
                flag[b.tag] = state.plastic[b.tag]
                continue
            ngp = geom.ngp
            s_out = np.empty_like(s_n)
            q_out = q_n.copy()
            D_out = np.empty((b.ne, ngp, 4, 4))
            f_out = np.zeros((b.ne, ngp), dtype=np.uint8)
            for cm, ids in bm.groups:
                ni = cm.n_int  # type: ignore[attr-defined]
                sg, qg, Dg, fg = cm.integrate(  # type: ignore[attr-defined]
                    s_n[ids].reshape(-1, 4),
                    deps[ids].reshape(-1, 4),
                    q_n[ids][..., : max(ni, 1)].reshape(-1, max(ni, 1)),
                )
                s_out[ids] = sg.reshape(ids.size, ngp, 4)
                if ni:
                    q_out[ids, :, :ni] = qg.reshape(ids.size, ngp, ni)
                D_out[ids] = Dg.reshape(ids.size, ngp, 4, 4)
                f_out[ids] = fg.reshape(ids.size, ngp)
            sig[b.tag], q[b.tag], D[b.tag], flag[b.tag] = s_out, q_out, D_out, f_out
        return Trial(sig, q, D, flag), self._fint(sig)

    # ------------------------------------------------------------------ helpers
    def _stiffness(self, D: dict[str, NDArray[np.float64]]) -> sp.csr_matrix:
        kes = [element_stiffness(self.geom[b.tag], D[b.tag]) for b in self.blocks]
        return self.pattern.assemble(kes)

    def _factor_free(self, K: sp.csr_matrix, symmetric: bool) -> object:
        f, p = self.dofmap.free, self.dofmap.prescribed
        Kf = K[f]
        fact = factorize(Kf[:, f], self.model.settings.linear_solver, symmetric)
        return _Factored(fact, Kf[:, p])

    def _gravity(self, lay: _Layout) -> NDArray[np.float64]:
        f = np.zeros(self.dofmap.ndof)
        for b, ed, bm in zip(self.blocks, self.edofs, lay.blocks):
            f += scatter_vector(
                ed, gravity_element_forces(self.geom[b.tag], bm.gamma), self.dofmap.ndof
            )
        return f

    def _fint(self, sig: dict[str, NDArray[np.float64]]) -> NDArray[np.float64]:
        f = np.zeros(self.dofmap.ndof)
        for b, ed in zip(self.blocks, self.edofs):
            f += scatter_vector(ed, internal_force(self.geom[b.tag], sig[b.tag]), self.dofmap.ndof)
        return f

    def _result(
        self,
        name: str,
        state: SolverState,
        f_ext: NDArray,
        timings: dict,
        history: StageHistory | None = None,
    ) -> StageResult:
        dm = self.dofmap
        r = np.zeros(dm.ndof)
        r[dm.prescribed] = (self._fint(state.sig) - f_ext)[dm.prescribed]
        return StageResult(
            name=name,
            u=dm.nodal(state.reported_u()),
            sig={k: v.copy() for k, v in state.sig.items()},
            reactions=np.nan_to_num(dm.nodal(r)),
            timings=timings,
            q={k: v.copy() for k, v in state.q.items()},
            plastic={k: v.copy() for k, v in state.plastic.items()},
            history=history,
        )

    def zero_state(self) -> SolverState:
        nq = self.nq
        z = {b.tag: np.zeros((b.ne, self.geom[b.tag].ngp, 4)) for b in self.blocks}
        return SolverState(
            u=np.zeros(self.dofmap.ndof),
            sig=z,
            q={b.tag: np.zeros((b.ne, self.geom[b.tag].ngp, nq)) for b in self.blocks},
            plastic={
                b.tag: np.zeros((b.ne, self.geom[b.tag].ngp), dtype=np.uint8) for b in self.blocks
            },
        )

    def project(self, state: SolverState, lay: _Layout) -> None:
        """Return committed stresses onto the yield surfaces of ``lay`` (du = 0)."""
        if lay.linear:
            return
        trial, _ = self.integrate(state, np.zeros(self.dofmap.ndof), lay)
        state.sig, state.q, state.plastic = trial.sig, trial.q, trial.flag
        self._D_committed = trial.D

    # ------------------------------------------------------------- stage solve
    def solve_increment(
        self,
        state: SolverState,
        lay: _Layout,
        f_ext: NDArray[np.float64],
        du_presc: NDArray[np.float64],
        settings: SolverSettings | None = None,
    ) -> tuple[SolverState, StageHistory]:
        """Solve one stage from ``state`` (updated in place; on failure it holds the last
        converged step and :class:`NonConvergence` is raised)."""
        dm = self.dofmap
        f0 = self._fint(state.sig)
        committed = state.commit()
        u_start = committed.u.copy()
        D_comm = self._D_committed

        def integrate(du: NDArray[np.float64]) -> tuple[Trial, NDArray[np.float64]]:
            return self.integrate(committed, du, lay)

        def factor(kind: str, trial: object | None) -> object:
            if kind == "elastic" or (kind == "committed" and D_comm is None):
                key = (lay.key, dm.free.size, hash(dm.free.tobytes()))
                fk = self._elastic_fact.get(key)
                if fk is None:
                    K = self._stiffness({b.tag: bm.De for b, bm in zip(self.blocks, lay.blocks)})
                    fk = self._factor_free(K, True)
                    self._elastic_fact = {key: fk}
                return fk
            Dd = trial.D if kind == "tangent" else D_comm  # type: ignore[union-attr]
            return self._factor_free(self._stiffness(Dd), lay.symmetric)  # type: ignore[arg-type]

        def commit(trial: object, du_total: NDArray[np.float64]) -> None:
            nonlocal committed, D_comm
            t: Trial = trial  # type: ignore[assignment]
            committed = SolverState(
                u=u_start + du_total,
                sig=t.sig,
                q=t.q,
                plastic=t.flag,
                u_ref=committed.u_ref,
            )
            D_comm = t.D

        prob = Problem(dm.ndof, dm.free, dm.prescribed, integrate, factor, commit)
        try:
            _, _, hist = solve_stage(
                prob, f_ext, f0, du_presc, settings or self.model.settings, lay.linear
            )
        finally:
            # on failure the state holds the last converged step (useful for mechanisms)
            self._D_committed = D_comm
            state.u, state.sig, state.q, state.plastic = (
                committed.u,
                committed.sig,
                committed.q,
                committed.plastic,
            )
        return state, hist

    def stage_external_force(self, st: Stage, lay: _Layout) -> NDArray[np.float64]:
        init = self.model.initial
        with_g = init.mode in ("gravity", "k0_field") or (init.mode == "field" and init.gravity)
        f = self._gravity(lay) if with_g else np.zeros(self.dofmap.ndof)
        return f + assemble_nodal_loads(
            self.mesh,
            self.dofmap.node_dofs,
            self.dofmap.ndof,
            st.loads,
            self.model.analysis,
            self.extra_tractions.get(st.name, ()),
        )

    def _stage_dofmap(self, st: Stage) -> DofMap:
        if not st.displacements:
            return self._base_dofmap
        return DofMap(
            self.mesh,
            None,
            None,
            self.model.fixities,
            (*self.model.displacements, *st.displacements),
        )

    # --------------------------------------------------------------------- run
    def initial_state(self) -> tuple[SolverState, StageResult]:
        model, dm = self.model, self.dofmap
        lay = self.layout({})
        self._layout = lay
        state = self.zero_state()
        mode = model.initial.mode
        timings: dict[str, float] = {"setup": self.t_setup}
        hist = None
        f_grav = self._gravity(lay) if mode in ("gravity", "k0_field") else np.zeros(dm.ndof)
        t1 = time.perf_counter()
        if mode == "gravity":
            state, hist = self.solve_increment(state, lay, f_grav, np.zeros(dm.prescribed.size))
            state.u = np.zeros(dm.ndof)  # displacements of the gravity stage are discarded
        elif mode == "k0_field":
            surf = model.initial.surface_y
            if surf is None:
                surf = float(self.mesh.coords[:, 1].max())
            yranges = []
            for b in self.blocks:
                ye = self.mesh.coords[b.conn, 1]
                yranges.append(np.column_stack([ye.min(axis=1), ye.max(axis=1)]))
            sig0 = k0_stress_field(
                [self.geom[b.tag].xg for b in self.blocks],
                yranges,
                [bm.gamma for bm in lay.blocks],
                [bm.k0 for bm in lay.blocks],
                surf,
            )
            state.sig = {b.tag: s for b, s in zip(self.blocks, sig0)}
            self.project(state, lay)
            res = self._fint(state.sig) - f_grav
            rel = np.linalg.norm(res[dm.free]) / max(np.linalg.norm(f_grav[dm.free]), 1e-30)
            if rel > 1e-3:
                log.warning(
                    "K0 field is not in equilibrium with self-weight (relative residual "
                    "%.2e); the first stage will redistribute it. Use mode='gravity' "
                    "for non-horizontal ground.",
                    rel,
                )
        elif mode == "field":
            s0 = np.asarray(model.initial.field, dtype=float)
            state.sig = {k: np.broadcast_to(s0, v.shape).copy() for k, v in state.sig.items()}
            self.project(state, lay)
        timings["solve"] = time.perf_counter() - t1
        return state, self._result("initial", state, f_grav, timings, hist)

    def run(self, stop_after: int | None = None) -> SolveResult:
        """Initial state + stages ``0..stop_after`` (all stages by default)."""
        model, dm = self.model, self.dofmap
        all_regions = self.mesh.regions()
        for st in model.stages:
            if st.active_regions is not None and frozenset(st.active_regions) != all_regions:
                raise NotImplementedError("element activation/excavation arrives in Faz 3")
            if st.active_structures:
                raise NotImplementedError("structural elements arrive in Faz 3")
            if st.water.mode != "none":
                raise NotImplementedError("groundwater coupling arrives in Faz 3-4")

        state, initial = self.initial_state()
        results = []
        current_override: dict[int, str] = {}
        lay = self._layout
        assert lay is not None
        stages = model.stages if stop_after is None else model.stages[: stop_after + 1]
        self.override = current_override
        for st in stages:
            t1 = time.perf_counter()
            if st.material_override != current_override:
                current_override = dict(st.material_override)
                lay = self.layout(current_override)
                self._D_committed = None
                self.project(state, lay)
            self.dofmap = self._stage_dofmap(st)
            dm = self.dofmap
            f_ext = self.stage_external_force(st, lay)
            # prescribed values are totals: move from the current position to them
            du_presc = dm.prescribed_values - state.u[dm.prescribed]
            if st.reset_displacements:
                state.u_ref = state.u.copy()
            state, hist = self.solve_increment(state, lay, f_ext, du_presc)
            timings = {"solve": time.perf_counter() - t1}
            results.append(self._result(st.name, state, f_ext, timings, hist))
            self.override = current_override
        self.state, self._layout = state, lay
        return SolveResult(model=model, geom=self.geom, initial=initial, stages=results)


def solve(model: Model, extra_tractions: dict[str, tuple] | None = None) -> SolveResult:
    """Solve ``model``: initial stress state followed by every stage in order."""
    return StaticSolver(model, extra_tractions).run()


__all__ = ["Analysis", "SolveResult", "StageResult", "StaticSolver", "Trial", "solve", "Stage"]
