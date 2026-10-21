"""Phase 1 static driver: initial stress + sequence of linear elastic stages.

Each stage is solved incrementally from the committed state:

    K du = f_ext(stage) - f_int(sigma_committed)      (+ prescribed-displacement terms)
    sigma += D B du

which is exact for linear elasticity and is the same out-of-balance formulation that the
nonlinear stage loop (Faz 2-3) will iterate on. Element activation/deactivation and
structural elements arrive in Faz 3; until then every stage uses the full continuum mesh.
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
from ..model.model import Model
from ..model.stages import Stage
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
from .state import SolverState

log = get_logger("static")


@dataclass
class StageResult:
    name: str
    u: NDArray[np.float64]  # (nn, 2) reported displacement (NaN on DOF-less nodes)
    sig: dict[str, NDArray[np.float64]]  # block tag -> (ne, ngp, 4)
    reactions: NDArray[np.float64]  # (nn, 2) nodal reactions at prescribed DOFs
    timings: dict[str, float] = field(default_factory=dict)


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
        self._fact = None
        self._fact_for: sp.csr_matrix | None = None
        self.t_setup = time.perf_counter() - t0

    # ------------------------------------------------------------------ helpers
    def _materials(self, override: dict[int, str]) -> list:
        """Per block: (D_e (ne,4,4), gamma_e (ne,), k0_e (ne,))."""
        rm = {**self.model.region_material, **override}
        cache: dict[str, tuple] = {}
        out = []
        for b in self.blocks:
            D = np.empty((b.ne, 4, 4))
            g = np.empty(b.ne)
            k0 = np.empty(b.ne)
            for r in np.unique(b.region):
                name = rm[int(r)]
                if name not in cache:
                    spec = self.model.materials[name]
                    cm = build_material(spec)
                    k0v = (
                        self.model.initial.k0
                        if self.model.initial.k0 is not None
                        else cm.k0_default()
                    )
                    cache[name] = (cm.elastic_D(), spec.gamma_unsat, k0v)
                m = b.region == r
                D[m], g[m], k0[m] = cache[name]
            out.append((D, g, k0))
        return out

    def _stiffness(self, mats: list) -> sp.csr_matrix:
        kes = [element_stiffness(self.geom[b.tag], D) for b, (D, _, _) in zip(self.blocks, mats)]
        return self.pattern.assemble(kes)

    def _gravity(self, mats: list) -> NDArray[np.float64]:
        f = np.zeros(self.dofmap.ndof)
        for b, ed, (_, g, _) in zip(self.blocks, self.edofs, mats):
            f += scatter_vector(ed, gravity_element_forces(self.geom[b.tag], g), self.dofmap.ndof)
        return f

    def _fint(self, sig: dict[str, NDArray[np.float64]]) -> NDArray[np.float64]:
        f = np.zeros(self.dofmap.ndof)
        for b, ed in zip(self.blocks, self.edofs):
            f += scatter_vector(ed, internal_force(self.geom[b.tag], sig[b.tag]), self.dofmap.ndof)
        return f

    def _solve_increment(
        self,
        K: sp.csr_matrix,
        R: NDArray[np.float64],
        du_presc: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        dm = self.dofmap
        free, pres = dm.free, dm.prescribed
        du = np.zeros(dm.ndof)
        du[pres] = du_presc
        rhs = R[free]
        if pres.size and np.any(du_presc != 0.0):
            rhs = rhs - K[free][:, pres] @ du_presc
        if self._fact_for is not K:  # factorise only when the stiffness changed
            Kff = K[free][:, free]
            self._fact = factorize(Kff, self.model.settings.linear_solver)
            self._fact_for = K
        du[free] = self._fact.solve(rhs)
        return du

    def _update_stress(
        self, sig: dict[str, NDArray[np.float64]], du: NDArray[np.float64], mats: list
    ) -> dict[str, NDArray[np.float64]]:
        out = {}
        for b, ed, (D, _, _) in zip(self.blocks, self.edofs, mats):
            deps = strain(self.geom[b.tag], du[ed])
            out[b.tag] = sig[b.tag] + np.einsum("eij,egj->egi", D, deps, optimize=True)
        return out

    def _result(
        self, name: str, state: SolverState, K: sp.csr_matrix, f_ext: NDArray, timings: dict
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
        )

    # --------------------------------------------------------------------- run
    def run(self) -> SolveResult:
        model, dm = self.model, self.dofmap
        all_regions = self.mesh.regions()
        for st in model.stages:
            if st.active_regions is not None and frozenset(st.active_regions) != all_regions:
                raise NotImplementedError("element activation/excavation arrives in Faz 3")
            if st.active_structures:
                raise NotImplementedError("structural elements arrive in Faz 3")
            if st.water.mode != "none":
                raise NotImplementedError("groundwater coupling arrives in Faz 3-4")

        mats = self._materials({})
        t0 = time.perf_counter()
        K = self._stiffness(mats)
        t_asm = time.perf_counter() - t0
        zero_sig = {b.tag: np.zeros((b.ne, self.geom[b.tag].ngp, 4)) for b in self.blocks}
        state = SolverState(u=np.zeros(dm.ndof), sig=zero_sig)

        # ---- initial stress
        mode = model.initial.mode
        f_grav = self._gravity(mats) if mode != "none" else np.zeros(dm.ndof)
        timings = {"setup": self.t_setup, "assemble": t_asm}
        if mode == "gravity":
            t1 = time.perf_counter()
            du = self._solve_increment(K, f_grav, np.zeros(dm.prescribed.size))
            timings["solve"] = time.perf_counter() - t1
            state.sig = self._update_stress(state.sig, du, mats)
            # displacements of the gravity stage are discarded (u stays zero)
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
                [g for (_, g, _) in mats],
                [k for (_, _, k) in mats],
                surf,
            )
            state.sig = {b.tag: s for b, s in zip(self.blocks, sig0)}
            res = self._fint(state.sig) - f_grav
            rel = np.linalg.norm(res[dm.free]) / max(np.linalg.norm(f_grav[dm.free]), 1e-30)
            if rel > 1e-3:
                log.warning(
                    "K0 field is not in equilibrium with self-weight (relative residual "
                    "%.2e); the first stage will redistribute it. Use mode='gravity' "
                    "for non-horizontal ground.",
                    rel,
                )
        initial = self._result("initial", state, K, f_grav, timings)

        # ---- user stages
        results = []
        current_override: dict[int, str] = {}
        u_presc_current = np.zeros(dm.prescribed.size)
        for st in model.stages:
            timings = {}
            if st.material_override != current_override:
                current_override = dict(st.material_override)
                mats = self._materials(current_override)
                K = self._stiffness(mats)
            f_ext = f_grav + assemble_nodal_loads(
                self.mesh,
                dm.node_dofs,
                dm.ndof,
                st.loads,
                model.analysis,
                self.extra_tractions.get(st.name, ()),
            )
            R = f_ext - self._fint(state.sig)
            du_presc = dm.prescribed_values - u_presc_current
            t1 = time.perf_counter()
            du = self._solve_increment(K, R, du_presc)
            timings["solve"] = time.perf_counter() - t1
            u_presc_current = dm.prescribed_values.copy()
            state.sig = self._update_stress(state.sig, du, mats)
            if st.reset_displacements:
                state.u_ref = state.u.copy()
            state.u = state.u + du
            results.append(self._result(st.name, state, K, f_ext, timings))
        return SolveResult(model=model, geom=self.geom, initial=initial, stages=results)


def solve(model: Model, extra_tractions: dict[str, tuple] | None = None) -> SolveResult:
    """Solve ``model``: initial stress state followed by every stage in order."""
    return StaticSolver(model, extra_tractions).run()


__all__ = ["Analysis", "SolveResult", "StageResult", "StaticSolver", "solve", "Stage"]
