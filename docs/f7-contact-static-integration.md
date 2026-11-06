# F7 — Explicit normal contact in the native staged solver

## What is now connected

PR #77 merged only a reproducible source-baseline workflow, not solver integration.
This implementation replaces that temporary job with actual verification and connects
PR #76's geometric-gap kernel to `api.run` / `StaticSolver`. It does not substitute a
reduced standalone Newton solve for the application's assembled FEM system.

Select the new law explicitly:

```python
from slipsurface.fe2d import api

spec = api.InterfaceSpec.unilateral_normal("contact", kn=2000.0, initial_gap=0.002)
# Equivalent:
# api.InterfaceSpec("contact", kn=2000.0, ks=0.0,
#                   law="unilateral_normal", initial_gap=0.002)
model.interfaces["contact"] = spec
```

Old JSON lacking `law` and `initial_gap` still constructs the original Goodman law.
The default remains `law="goodman"`. Direct construction of `InterfaceGroup` with a
normal-contact spec raises rather than silently using Goodman mechanics. The model
selector dispatches a separate `StagedNormalContactGroup`, not a change to the old
constitutive return mapping.

## Bounded supported contract

This first integration supports straight coincident-reference IFACE4/IFACE6,
plane strain, small displacements and fixed normals, dry drained models, an initial
stress-free state (`InitialStress("none")`), and full Newton (`method="NR"`).
`ks`, cohesion, friction, dilation and tensile strength must all be zero for this law;
`kn > 0` and `initial_gap >= 0` must be finite. Initial clearance is represented by the
scalar parameter, not a second geometric offset. Positive gap is opening. Face ordering
must encode the intended normal: left normal to the first face's directed tangent.

Wet/undrained, axisymmetric, gravity/K0/field initialization, modified/frozen Newton,
seismic loading and strength reduction with this new law are explicitly rejected.
This avoids silently importing adjacent soil tractions, losing a displacement reference
in gravity resetting, or reporting a fictitious contact-only strength factor.
These restrictions apply to the new law only; existing Goodman models are unchanged.
No frictional contact, moving-normal search, bond degradation, or hydraulic contact
semantics are introduced. GUI material authoring and remesh history transfer are not
implemented by this change. Script/model files are the supported selection route.

## State, activation and outputs

At stage transitions the adapter reconstructs
`gap = initial_gap + n dot (u_face2 - u_face1)` from **total** nodal displacements relative
to the original mesh. It does not use `reported_u` or copy soil stress. Thus stage display
resets, delayed first activation, deactivation with motion, and reactivation do not
invent a new reference configuration. Within a stage the native trial/commit/rollback
machinery advances geometric gap only on accepted increments.

Unlike inactive Goodman joints, inactive normal contact **never welds its faces**.
Partly inactive face topology follows the existing continuum/beam adjacency logic.
An active contact still permits tangential motion and has exactly zero normal stiffness
while open. Models must supply sufficient real supports; an unsupported floating
body is rejected by the native singular-system/nonconvergence path, not stabilized by
adding a fictitious spring.

`StageResult.interfaces[tag]` holds `[0, sigma_n]`. New `contact_gap[tag]` stores gap in
metres; `contact_status[tag]` stores OPEN=0, TOUCHING=1, COMPRESSED=2, INACTIVE=255.
Inactive gaps and tractions are NaN. Contact statuses are **not** written as plastic flags.
JSON model parameters and both HDF5/.ssproj snapshot APIs preserve these fields; older
snapshots missing the optional fields load with empty dictionaries. These files remain
post-processing snapshots, **not nonlinear restart checkpoints**. A re-solve of the
restored model is tested, not recovery of an interrupted Newton iteration from HDF5.

## Zero-force translation and numerical convergence

An open IFACE6/Q8 layer can translate under prescribed displacement with no physical
load or strain. Assembled cancellation then leaves tiny floating-point residuals even
though the physical force reference is zero. For models selecting normal contact,
`Problem.roundoff_force_scale` supplies a cancellation bound using
`norm(abs(K_reference) @ (abs(u_stage_start) + abs(du)))`. The existing machine-epsilon
roundoff test uses this force scale; it is not a user tolerance or a force floor.
The reference matrix is used only for the rounding bound. The actual contact residual
and Newton tangent still use the current gap, including exact zero open stiffness.
Legacy problems do not enable this callback. Soil/beam elastic or committed predictors
are preserved; contact predictors always use the current geometric derivative.

## Independent native FEM reference

`scripts/f7_contact_static_benchmark.py` constructs a laterally constrained elastic
continuum layer over a fixed base with normal contact. Q4/IFACE4 and Q8/IFACE6 are
assembled and solved through `api.run`. With height H, width L, initial clearance g0,
and `C = E(1-nu)/((1+nu)(1-2nu))`, let k=C/H.

For a prescribed top displacement v:

- Open: `u_bottom = v` when `v >= -g0`.
- Closed: `u_bottom = (k*v - kn*g0)/(k+kn)` otherwise.
- `sigma_y = k*(v-u_bottom)`; top reaction is `L*sigma_y`.

For a fixed top and total applied bottom force F:

- Open: `u_bottom = F/(L*k)` when `F/L >= -k*g0`.
- Closed: `u_bottom = (F/L-kn*g0)/(k+kn)` otherwise.
- `sigma_y = -k*u_bottom`; top reaction is `L*sigma_y`.

In both cases `gap=g0+u_bottom`, `sigma_n=kn*min(gap,0)` and the base reaction is
`-L*sigma_n`. These scalar continuum/contact equilibrium formulas do not inspect
native stiffness, native contact weights or solver returned forces to derive targets.
The benchmark spans eight models and 56 stages, with two clearances and both control
modes. It tests 6 mm -> 5 mm open reversal, closure, reopening and report-datum resets.
It checks absolute gap, pressure, zero shear, top/base reactions and global equilibrium
with separate dimensional tolerances (1e-10 m and 1e-8 kPa or kN/m).

Additional regressions cover inactive motion/reactivation, partial stages, discarded
trials, failed-step rollback/cutback, unsupported mechanisms, compatibility, model and
snapshot roundtrips, and deliberate corruption of gap/force/status evidence. The
workflow `f7-contact-integration` preserves actual JSON, JUnit, log and summary evidence.
The existing coupled F7 workflow remains in place and reruns on the native solver edits.

## Non-claims

This is native integration verified on bounded elastic continuum/contact examples, not
a validated general-purpose geotechnical contact solver, nonlinear excavated pile
benchmark, experimental material calibration, or an RS2/PLAXIS comparison. It does not
turn the historical Goodman 6 mm -> 5 mm response into a unilateral contact response;
users must select the new law explicitly.
