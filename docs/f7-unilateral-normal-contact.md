# F7 — Separate unilateral normal-contact kernel

## Motivation and integration boundary

PR #75 deliberately left the legacy Goodman interface unchanged. Its tensile-capped
elastoplastic law develops compression on reversal from 6 mm to 5 mm opening,
although the absolute opening remains positive. That law is not an initially
coincident, unbonded unilateral contact law.

This change **implements a separate normal-contact kernel**, not merely another
comparison of the old law. `UnilateralNormalContactGroup` lives in
`src/slipsurface/fe2d/fem/unilateral_contact.py`. It is explicitly instantiated
by the benchmark; it is **not registered in `GROUP_TYPES`**, not an
`InterfaceSpec` option, and not available in Model/JSON authoring or the GUI.
The production Goodman interface, its historical results, and every existing
coupled F7 gate remain unchanged. No existing excavation automatically acquires
this contact behavior after merging the PR.

## Physical contract and units

Opening is positive. Each contact integration point stores its signed gap `g`
[m], not a capped stress. With fixed reference normals:

```
g_trial = g_committed + n dot (delta_u_face2 - delta_u_face1)
sigma_n = kn * min(g_trial, 0)
tau = 0
energy_per_area = 0.5 * kn * min(g_trial, 0)^2
```

`kn` has units kPa/m; normal traction is kPa, integrated nodal force is kN/m
out of plane, and total recoverable energy is kN*m/m. Positive initial clearance
is supplied once as `initial_gap >= 0`; reference face coordinates must coincide
so clearance cannot be counted twice. The model is frictionless, nonadhesive,
quasi-static and dry. No normal plastic offset accumulates. Reopening eliminates
normal force, and partial reversal while the gap remains positive does not
create compression.

This is a **finite penalty** law. Negative gap is allowed and produces compressive
traction. It is not exact nonpenetration/Signorini complementarity. At `g=0` the
force is zero and the closed-side generalized tangent `kn` is selected. The
classical derivative is not unique there; tests use one-sided derivatives at
the switch and centered differences only away from it. No gap tolerance or
artificial stiffness floor is used to create a false active contact.

This absolute-gap normal spring is consistent with the absolute update mode
of Itasca's unbonded linear contact model (equation 5); its incremental update
mode is a distinct choice. That is a definition reference, **not a numerical
comparison with Itasca/PFC**. Their point-contact stiffness and this distributed
interface stiffness have different units before integration.

Primary reference: Itasca, *Linear Model*, force-displacement law and activity
criteria, https://docs.itascacg.com/itasca910/common/contactmodel/linear/doc/manual/cmlinear.html

## Element assembly and state handling

Straight IFACE4 and IFACE6 reference faces are supported in plane strain. The
IFACE6 midpoint must be centered. Curved faces, noncoincident reference faces,
invalid connectivity and axisymmetric analysis are rejected. Normals remain
fixed; the kernel does not search for new contact partners or support finite
sliding/rotation.

At each paired station, `B` maps nodal increments to the normal relative jump.
The standalone assembly forms `f = sum(w B.T sigma_n)` and
`K = sum(w B.T D_n B)`. Nodal trapezoidal weights (IFACE4) and Simpson weights
(IFACE6) match the repository's interface convention. For mixed open/closed
stations this is a **nodal contact discretization**, not an exact integration
of an unresolved contact boundary inside an element. Mesh studies remain
necessary for that boundary.

`integrate` returns a new gap state for selected elements and never commits it.
An accepting caller must copy `trial['gap']` into the corresponding committed
rows. Discarded/repeated trials must leave the old state unchanged. `activate`
resets selected pairs to `initial_gap` and establishes a **new reference**; it
must not be used to resume an old separated contact. Automatic deactivation,
reactivation and remesh history transfer are not implemented here.

Contact statuses are `OPEN`, `TOUCHING`, `COMPRESSED`; they are not
`PlasticFlag` values. The legacy traction-only state is explicitly rejected.
Water inputs are rejected, including zero-valued arrays. Open contacts have
zero stiffness, and all tangential directions are free. A future global solver
must handle unconstrained mechanisms and active-contact changes; this PR does
not stabilize them by secretly adding stiffness.

## Verification actually exercised

The dedicated benchmark uses total prescribed geometric displacements for its
reference; it does not advance the reference using the computed gap or stress.

* 12 histories: 2 element types × 3 orientations × 2 initial clearances, with
  108 committed increments, opening, partial reversal, compression and reopening.
* Every smooth history step checks independent full nodal forces, full tangent,
  all-DOF finite differences, recoverable energy, contact statuses, action/reaction,
  discarded/repeated trials and committed-state immutability.
* 12 additional reduced force-controlled spring/contact systems, 84 accepted
  load steps. A parallel spring constrains the open normal mode. Actual assembled
  forces/tangents drive Newton iterations and are checked against
  `k_s*u + L*kn*min(g0+u,0) = P`. This is **not `StaticSolver` or `api.run`**.
* Regression tests additionally cover mixed open/closed stations, initial gap,
  exact-switch one-sided derivatives, path subdivision, subset activation,
  invalid data, overflow and deliberate result/state corruption.

Numerical errors are normalized within matching units with unit floors, not by
mixing stiffness, stress and force. Analytical tolerance is `1e-9`; smooth-region
finite-difference tolerance is `1e-6`. The benchmark exits nonzero on any failed
history or force-controlled comparison. Strict JSON evidence is retained at
`f7_contact/unilateral_contact_benchmark.json`.

The separate `f7-unilateral-contact` workflow runs these checks. The ordinary CI
matrix also collects the new tests. The existing expensive coupled F7 workflow
is not rewritten or falsely reported as a validation of this unregistered law.

## Remaining work before application use

An explicit model-law selector, serialization/migration rules, geometric
activation reference, contact-state persistence/remeshing, initialization under
prestress and result export still need integration with the full solver.
Only then should an opt-in continuum/contact equilibrium test and an excavation
model use this behavior. Friction, cohesion, dilation, tensile bonds, fluid
pressures, moving normals and coupled soil-pile-anchor validation are excluded.
