# F7/V5 — Adaptive Newton rollback and staged force balance

These tests are a **solver verification gate**, not evidence that every nonlinear
geotechnical excavation has converged or that published RS2/PLAXIS benchmarks
have been reproduced.

## Adaptive Newton acceptance contract

A manufactured one-degree-of-freedom problem has

    f_internal = u
    f_external = 1
    solution at load factor lambda: u = lambda

Its constitutive integrator refuses a total trial step if

    abs(delta_u_step) > 0.30

The global stage solver must then:

1. Report a rejected load increment with termination `material_return`.
2. Cut the increment and retry without changing the last committed state.
3. Commit only converged trials; accepted increments must advance monotonically.
4. Reach the exact full-load solution u=1 despite earlier rejected trials.
5. Raise `NonConvergence`, preserve the last converged load factor, and make
   **no commits at all** if even the minimum allowable increment cannot be
   integrated.

The manufactured material is intentionally simpler than Mohr-Coulomb; it
isolates the driver's commit/rollback semantics from constitutive details.

## Staged pressure, independent elastic solution

A laterally restrained plane-strain column with E=24,000 kPa, nu=0.25,
height H=6 m and width W=4 m has constrained modulus

    M = E*(1-nu)/((1+nu)*(1-2nu))

Three stages apply a top pressure of q=60 kPa with the first stage stopping
at load factor 0.4, the second reaching q, and the third raising pressure
to 2q. The exact displacement, stress and reactions are

    uy(top) = -(factor*q*H)/M
    syy = -(factor*q)
    total Ry = factor*q*W
    total Rx = 0

The tests cover T3, T6, Q4 and Q8 elements. They verify cumulative
loading, the retained unbalance after a partial stage, and the external
load/reaction sign and unit conventions.

## Not yet demonstrated

- Independently assembled excavation traction equilibrium, including water,
  structures, deactivated continuum elements, and interfaces.
- Plastic tunnel or pile-wall convergence at three mesh resolutions and
  support force-transfer under staged excavation.
- Physical validation against published field/instrumentation data or
  commercial reference results using identical inputs.
- Quantified error budget at re-entrant corners and mesh singularities.

Passing the tests is necessary for a verified stage solver, but not a
standalone engineering release approval.
