# F7/V5 — Support forces and staged liner equilibrium

This package verifies structural response and extends the existing staged
excavation mesh audit. It does not claim an RS2/PLAXIS comparison or field
validation of a reinforced excavation.

## Independent beam acceptance

An isolated six-metre Timoshenko cantilever is loaded at its free end
with downward force P, then 2P in a second stage. With lining E, I, G
and shear area As, the independent analytical relationships are:

    uy(L) = -P*L**3/(3*E*I) - P*L/(G*As)
    |M(root)| = P*L
    Ry(root) = P
    |reaction moment| = P*L

A dummy fully restrained continuum is inactive in the beam stage so
the case isolates structural force-transfer and staged cumulative
loading from any soil or interface stiffness.

Tests inspect the actual beam section forces, not merely the nodal
displacement. The second-stage response must be twice the first for
the linear model.

## Staged pile/anchor mesh audit

Existing tool: `examples/f7_excavation_mesh_audit.py`.

The audit now retains support identity by structure tag for each
stage and mesh resolution. Its JSON report includes per-stage
`beam_moments` and `bar_axial_forces` keyed by tag, and a separate
`excavation_support_comparison.csv` records consecutive mesh
differences. If a support tag appears at one mesh resolution but
is missing at the next, the report uses status `missing`, **not**
a fabricated zero force.

Run the optional (potentially expensive) audit:

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

An engineering review must compare local liner moments and bolt
forces together with ground displacement, plasticity and structural
activation order; maximum-only values cannot establish force
distribution or design capacity.

## Remaining F7 acceptance gates

1. Independently balance released soil forces at each excavation stage,
   including any piezometric boundary and activated structures.
2. Compare **distributions** of beam moments/axial forces rather than only
   peak values across three conforming mesh resolutions.
3. Audit singularities near point supports and excavation corners.
4. Benchmark plastic liner/bolt interaction against an external
   documented solution with identical initial stresses and units.
5. Confirm the optional three-mesh audit runs to completion and inspect
   any failures before treating its outputs as accepted.

This is a verification increment, not full geotechnical product validation.
