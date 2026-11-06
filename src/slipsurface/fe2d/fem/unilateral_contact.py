"""Experimental dry, frictionless normal contact; NOT registered in GROUP_TYPES.

The signed gap (metres, opening positive) is committed independently of stress.
Normal traction is kn * min(gap, 0), never an incrementally clipped old traction.
This separate kernel leaves the existing Goodman InterfaceGroup unchanged.
Only straight, paired, coincident-reference IFACE4/IFACE6 in plane strain are
supported. Geometry/normals stay fixed: no contact search or finite sliding.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np

from ..core.enums import Analysis, ElemType


class ContactStatus(IntEnum):
    """Contact states, deliberately distinct from constitutive PlasticFlag."""

    OPEN = 0
    TOUCHING = 1
    COMPRESSED = 2


def _real_array(value, name):
    raw = np.asarray(value)
    if raw.dtype.kind not in "fiu" or not np.isfinite(raw).all():
        raise ValueError(f"{name} must contain finite real numbers")
    return raw.astype(float, copy=False)


def _scalar(value, name, *, positive=False):
    array = _real_array(value, name)
    if array.ndim != 0 or (array <= 0 if positive else array < 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'nonnegative'} scalar")
    return float(array)


def normal_contact_response(gap, kn):
    """Return normal traction, generalized tangent, status and stored energy.

    Units: gap m, kn kPa/m, traction kPa, energy/area kPa*m. For gap=0,
    traction is zero and the closed-side tangent kn is selected. There is
    no unique classical derivative at that switch. No gap deadband is used.
    Finite kn permits small penetration; this is not hard Signorini contact.
    """
    stiffness = _scalar(kn, "kn", positive=True)
    g = _real_array(gap, "gap")
    overlap = np.minimum(g, 0.0)
    with np.errstate(over="raise", invalid="raise"):
        try:
            traction = stiffness * overlap
            energy = 0.5 * traction * overlap
        except FloatingPointError as exc:
            raise ValueError("Normal contact response overflow") from exc
    tangent = np.where(g <= 0.0, stiffness, 0.0)
    status = np.where(g > 0.0, ContactStatus.OPEN,
                      np.where(g < 0.0, ContactStatus.COMPRESSED, ContactStatus.TOUCHING))
    return traction, tangent, status.astype(np.uint8), energy


class UnilateralNormalContactGroup:
    """Explicit standalone element kernel, not a selectable Model.interfaces law.

    State contains ONLY geometric gap. Trial integration does not mutate it;
    accepted subset rows must be copied back by the caller. Activating a pair
    establishes a NEW reference and resets its gap to initial_gap; it is not
    a resume/reactivation operation for an old separated contact.
    """

    kind = "unilateral_normal_contact"
    symmetric = True
    linear = False

    def __init__(self, block, coords, *, kn, initial_gap=0.0,
                 analysis=Analysis.PLANE_STRAIN):
        if analysis is not Analysis.PLANE_STRAIN:
            raise ValueError("Normal contact currently supports plane strain only")
        if block.etype not in (ElemType.IFACE4, ElemType.IFACE6) or block.ne < 1:
            raise ValueError("Require a nonempty IFACE4/IFACE6 block")
        self.kn = _scalar(kn, "kn", positive=True)
        self.initial_gap = _scalar(initial_gap, "initial_gap")
        x = _real_array(coords, "coords")
        if x.ndim != 2 or x.shape[1] != 2:
            raise ValueError("coords must have shape (nn, 2)")
        conn = np.asarray(block.conn)
        if (conn.dtype.kind not in "iu" or conn.shape != (block.ne, block.etype.nen)
                or np.any(conn < 0) or np.any(conn >= len(x))):
            raise ValueError("Invalid contact connectivity")
        self.npe = 2 if block.etype is ElemType.IFACE4 else 3
        self.nd, self.ne, self.tag = 4 * self.npe, block.ne, block.tag
        # Copy connectivity and geometry-derived arrays: callers cannot change
        # the fixed contact frame by mutating their mesh after construction.
        self.conn = conn.copy()
        first, second = x[conn[:, :self.npe]], x[conn[:, self.npe:]]
        vector = first[:, 1] - first[:, 0]
        length = np.linalg.norm(vector, axis=1)
        if not np.isfinite(length).all() or np.any(length <= 0):
            raise ValueError("Degenerate contact face")
        tolerance = 1e-12 * np.maximum(length, 1.0)
        if np.any(np.max(np.abs(first - second), axis=(1, 2)) > tolerance):
            raise ValueError("Reference faces must coincide; use initial_gap for clearance")
        if self.npe == 3 and np.any(
            np.max(np.abs(first[:, 2] - first[:, :2].mean(axis=1)), axis=1) > tolerance
        ):
            raise ValueError("Only straight IFACE6 with a centred midpoint is supported")
        direction = vector / length[:, None]
        self.normal = np.column_stack([-direction[:, 1], direction[:, 0]])
        fractions = np.array([0.5, 0.5] if self.npe == 2 else [1/6, 1/6, 2/3])
        self.weights = length[:, None] * fractions
        # B maps each nodal displacement to the signed normal relative jump.
        self.B = np.zeros((self.ne, self.npe, self.nd))
        for j in range(self.npe):
            self.B[:, j, 2*j:2*j+2] = -self.normal
            self.B[:, j, 2*(self.npe+j):2*(self.npe+j)+2] = self.normal

    def zero_state(self):
        return {"gap": np.full((self.ne, self.npe), self.initial_gap, dtype=float)}

    def _ids(self, ids):
        a = np.asarray(ids)
        if (a.ndim != 1 or a.dtype.kind not in "iu" or len(np.unique(a)) != len(a)
                or np.any(a < 0) or np.any(a >= self.ne)):
            raise ValueError("Element ids must be unique valid integers")
        return a.astype(np.int64, copy=False)

    def _state(self, state):
        if not isinstance(state, dict) or set(state) != {"gap"}:
            raise ValueError("Expected geometric gap state, not Goodman traction state")
        gap = _real_array(state["gap"], "state gap")
        if gap.shape != (self.ne, self.npe):
            raise ValueError("State gap shape mismatch")
        return gap

    def activate(self, state, ids):
        """Explicitly establish new reference for selected pairs, not resume history."""
        indices = self._ids(ids)
        self._state(state)
        if not isinstance(state["gap"], np.ndarray) or state["gap"].dtype.kind != "f":
            raise ValueError("Activation requires a writable floating-point state array")
        if not state["gap"].flags.writeable:
            raise ValueError("Activation requires a writable state array")
        state["gap"][indices] = self.initial_gap

    def integrate(self, state, ids, du_e, p=None):
        """Return trial state, internal nodal forces, tangent and CONTACT statuses.

        du_e is relative to the committed nodal displacement. A water input is
        rejected, including zero arrays: hydraulic semantics are not implemented.
        """
        if p is not None:
            raise ValueError("Dry normal contact does not accept pore-pressure input")
        indices = self._ids(ids)
        gap = self._state(state)
        increment = _real_array(du_e, "displacement increment")
        if increment.shape != (len(indices), self.nd):
            raise ValueError("Displacement increment shape mismatch")
        b, w = self.B[indices], self.weights[indices]
        with np.errstate(over="raise", invalid="raise"):
            try:
                trial_gap = gap[indices] + np.einsum("epd,ed->ep", b, increment)
                traction, stiffness, status, _ = normal_contact_response(trial_gap, self.kn)
                forces = np.einsum("epd,ep->ed", b, w * traction)
                tangent = np.einsum("epd,ep,epf->edf", b, w * stiffness, b)
            except FloatingPointError as exc:
                raise ValueError("Normal contact assembly overflow") from exc
        if not np.isfinite(forces).all() or not np.isfinite(tangent).all():
            raise ValueError("Nonfinite contact force or tangent")
        return {"gap": trial_gap}, forces, tangent, status

    def stored_energy(self, state):
        """Recoverable penalty energy per element, kN*m/m out of plane."""
        gap = self._state(state)
        density = normal_contact_response(gap, self.kn)[3]
        with np.errstate(over="raise", invalid="raise"):
            try:
                energy = np.sum(self.weights * density, axis=1)
            except FloatingPointError as exc:
                raise ValueError("Normal contact energy overflow") from exc
        return energy
