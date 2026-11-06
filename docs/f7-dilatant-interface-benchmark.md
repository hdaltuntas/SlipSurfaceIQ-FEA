# F7 — Dilatant and multisurface interface reference

This benchmark extends the nondilatant, compressive direct-shear check with
**branch-labelled analytical references**. It tests isolated straight, dry
IFACE4 and IFACE6 elements. It does not select a return branch using the
native solver, nor use its matrices, quadrature weights or traction output
to construct the analytical reference.

## Constitutive definitions

The native sign convention is tensile-positive normal traction. Write
`t = (tau, sigma)`, `f = tan(phi)`, `g = tan(psi)`, and
`K = diag(ks, kn)`. The admissible region is

```
+tau + f*sigma <= c
-tau + f*sigma <= c
sigma <= T = min(sig_t, c/f)    (f > 0)
```

The shear plastic flow direction is `(s, g)` for shear sense `s = +/-1`;
the tension flow direction is `(0, 1)`. The benchmark applies a uniform
jump that produces the specified elastic trial traction from a zero
committed state. The reference is independently derived below, rather
than reproducing the production active-set enumeration.

## Closed forms used

**One shear plane.** With strictly positive plastic multiplier,

```
lambda = (s*tau_trial + f*sigma_trial - c) / (ks + kn*f*g)
tau   = tau_trial   - s*ks*lambda
sigma = sigma_trial - kn*g*lambda

D = 1/(ks + kn*f*g) * [[ks*kn*f*g, -s*ks*kn*f],
                      [-s*ks*kn*g,      ks*kn]]
```

`D` differentiates returned traction with respect to the total jump.
For `psi != phi` it is generally nonsymmetric; the benchmark checks both
cross terms. A tensile trial can return to compressive shear without
activating the tensile cap. A case explicitly tests that distinction.

**Tension only.** The return is `(tau_trial, T)` with
`D = diag(ks, 0)` and multiplier `(sigma_trial-T)/kn`.

**Shear/tension corner below the apex.** The returned point is
`(s*(c-f*T), T)` with zero tangent in the selected branch interior.
The multipliers are

```
lambda_s = s*(tau_trial-tau)/ks
lambda_t = (sigma_trial-T)/kn - g*lambda_s
```

Both must be strictly positive. Positive and negative corners are tested.

**Apex.** For positive friction and dilation, and a tensile cap not below
`c/f`, the two-shear-plane return is `(0, c/f)` with zero tangent. Set
`S = (sigma_trial-c/f)/(kn*g)` and `Q = tau_trial/ks`; then
`lambda_plus = (S+Q)/2` and `lambda_minus = (S-Q)/2`.
Both multipliers must be positive. The benchmark also checks the native
apex state flag. Zero-dilation apex singularities are not covered by this
reference.

Each labelled reference rejects inadmissible branches, nonpositive
multipliers and branch-switching points. It is not a general-purpose
replacement return-mapping algorithm.

## Element and tangent verification

Eleven cases cover elasticity, both dilatant shear directions, a tensile
trial returning to compression, tension-only return, both shear/tension
corners, an apex, associated shear/corner cases, and the nondilatant limit.
The workflow runs them for IFACE4 and IFACE6 at 0, 37 and -63 degrees:
**66 element cases**. Parameterized tests also vary the length.

For uniform traction, independent nodal integration weights are
`L*(1/2, 1/2)` for IFACE4 and `L*(1/6, 1/6, 2/3)` for IFACE6 in the
native endpoint/endpoint/midpoint order. The reference rotates tractions
and tangents using the prescribed geometric angle and assembles equal
and opposite nodal forces and the **entire** element tangent. It does
not read `group.w`, `group.R`, `group.Brel` or `group._assemble`.

The numerical tangent is additionally checked by centered perturbations
of every element degree of freedom from the same committed state.
The committed state must remain unchanged during all trial evaluations.
The test suite injects corrupted traction, force, tangent, flags, state
mutation and nonfinite results to check that failures cannot pass.

## Error scales and workflow

Traction, force, stiffness, finite-difference stiffness and net-force
reciprocity are evaluated separately. Each normalized error divides the
maximum absolute discrepancy by `max(1, max(abs(reference)))` in that
quantity's stated units; different physical dimensions are never combined
under a single reference scale. Analytical comparisons use `1e-9` and
finite-difference comparisons `1e-6`. These are numerical verification
tolerances, not geotechnical design tolerances.

```
PYTHONPATH=src python scripts/f7_dilatant_interface_benchmark.py \
  --output f7_audit/dilatant_interface_benchmark.json
pytest -q tests/verification/test_f7_dilatant_interface_benchmark.py
```

The F7 workflow runs this check before excavation, archives the strict
JSON report with the existing evidence, and shows its status and case
count in the job summary. A failed comparison, state flag or state-purity
check causes a nonzero exit. Existing excavation/force-budget gates are
preserved. Changes to `fem/structural.py` also trigger this workflow.

## Limits

These are mathematical verification cases for the implemented local
law and element assembly. They do not validate arbitrary loading history,
crack opening/closure memory, hydraulic forces, softening, curved interfaces,
axisymmetry, or the complete soil–pile–anchor excavation. They do not
establish agreement with a separate engineering program or a physical test.

For general background on shear flow, dilation and tensile limits, see
[Itasca's Mohr contact model description](https://docs.itascacg.com/itasca900/common/contactmodel/mohr/doc/manual/cmmohr.html).
That documentation is context, not a numerical reference for these cases:
the formulas above are derived specifically for this repository's stated
sign convention and idealized yield/flow definitions.
