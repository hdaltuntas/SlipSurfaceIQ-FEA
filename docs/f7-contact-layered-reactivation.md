# F7 — Exact elastic layer removal and reactivation

## Purpose and limits

This companion to the monotone-removal fixture checks the CURRENT implementation's
stress-free continuum reactivation and original-reference normal contact together.
It is not a new backfill material, deposition process, remesh, restart checkpoint,
updated geometry formulation, or general-purpose excavation audit. No production
solver, material, contact law, GUI, tolerance, or old audit is changed.

The fixture uses the same three-layer geometry as the earlier excavation benchmark:
two shared-node lower layers, a separate supported upper body, and a straight
IFACE4/IFACE6 normal contact. All layers are elastic, dry, drained and initially
stress-free; there is no gravity. Each layer is 1 m high and 2 m wide. E=2000 kPa,
nu=0.25 gives constrained modulus C=2400 kPa. Normal penalty kn=2000 kPa/m.
The same small-displacement mesh is retained throughout.

Fourteen stages load the specimen, remove the middle layer, remove the remaining
lower layer, restore the lower layer, restore the middle layer, and repeat middle
layer removal/reactivation. The contact tag remains requested; adjacent continuum
activity must deactivate/reactivate it automatically. The surviving upper body
moves while the lower nodes are absent. Full and partial force/displacement/mixed
stages are used, with repeated stage names and displacement reporting resets.

## Three references that must not be confused

1. **Constitutive birth:** a newly active continuum element starts with zero stored
   stress. Only subsequent displacement increments create elastic strain/stress.
   A surviving element retains its previous stress. Deleted stress is not revived.
2. **Geometric contact:** total nodal positions remain relative to the original
   mesh, including last positions of temporarily inactive nodes. The normal-contact
   law uses g=g0+b-u2, not a zeroed or reported displacement. Stress-free birth does
   not redefine contact clearance or remove penalty penetration.
3. **Reported displacement:** newly active nodes receive a reporting datum equal to
   their retained displacement. Explicit reset stages set the reporting datum for
   all nodes. These operations change displayed displacement, not contact geometry.

In particular, original-coordinate displacement can be nonzero while a reborn
layer is stress-free. For Q8, previously inactive midside nodes can retain a
non-affine *total* displacement distribution after birth; the incremental strain
and stress remain checked. This is a characterization of the existing incremental
law, not a claim that it simulates placing a new physical backfill in a deformed
cavity. Loading history on disappeared nodes is dropped; it does not reappear
when those nodes become active again.

## Independent scalar reference

Let u1 be the displacement at the shared lower-layer face, u2 the lower contact
face, b the upper contact face and v the top displacement. Normal-positive
tractions are tensile. The three initial stage stresses s10,s20,s30 are the
previous stresses for surviving layers and zero for newly active layers.

Project prior actual physical loads onto the current active nodes first. Then
q=(1-alpha)*q_previous+alpha*q_target. At the three free normal faces, the
start-of-stage internal forces per unit width are

```
i0 = (s10-s20, s20-t0, -s30+t0)
t0 = kn * min(g0+b_old-u2_old, 0)   # zero when contact is inactive
h  = (1-alpha)*(i0-q_previous)      # current free/active faces only
r  = q+h
```

With both lower layers present:

```
s2 = t+r2;  s1 = s2+r1;  s3 = t-r3
A  = u2_old+(r1+2*r2-s10-s20)/C
B  = b_old+(v-v_old)+(s30+r3)/C
t  = min(0, kn*(g0+B-A)/(1+3*kn/C))
u1 = u1_old+(s1-s10)/C
u2 = A+2*t/C
b  = B-t/C
```

When the middle layer is absent, t=0, s1=r1 if the bottom layer survives, and
s3=-r3. Displacements of inactive nodes remain frozen in the reference. Active
nodal increments follow each layer's constant incremental strain, including Q8
midside nodes. Independent constant-stress boundary integrals give every nodal
force and reaction; neither native stiffness/residual nor native quadrature
helpers generate targets. Only the earlier fixture's mesh builder is reused.

Hand-rational test for the zero-clearance mixed case: before first removal,
lower stress is -389/42 kPa. After fractional relaxation and later bottom-layer
rebirth, u1=-389/537600 m while s1=0. The old lower contact position is
u2=-389/50400 m. On the first middle-layer rebirth, physical lower loading is
-0.5 kN/m (one quarter of the newly specified -2), not a resurrection of the
previously deleted -5 kN/m. Physical total loading at that stage is +2 kN/m.

## Evidence and failure behavior

Run from the repository root with the source package available:

```
python scripts/f7_contact_reactivation_benchmark.py \
  --output reactivation.json --example reactivation.ssproj
```

The script solves 24 actual `api.run / StaticSolver` models and 336 stages:
Q4/IFACE4 and Q8/IFACE6, zero/2-mm clearances, translated 0/90-degree frames,
and force/displacement/mixed control. The evaluator checks all stored Gauss
stresses, all active reported nodal displacements with independent datums,
contact activity/gap/traction/status, all nodal reactions, physical-load history,
retained-release forces and global force/moment balance. Missing/malformed data
cannot produce an overall pass. Separate dimensional tolerances are 1e-10 m
and 1e-8 kPa, kN/m or kN*m/m; no solver tolerance is relaxed.

Transition equilibrium and physical-only nodal equilibrium are separate. A
partial stage may retain h even when its global vector sum cancels. Full stages
must satisfy physical-only equilibrium. The report records actual counts rather
than labeling every successful transition as a physical-only pass.

Tests include 34 deliberate snapshot corruptions, rational checks, repeated
rebirth, mesh refinements, reset/no-reset comparisons, JSON/HDF5/.ssproj
roundtrips, nonmutation, CLI failure and unsupported-general-audit checks.
Saved results are snapshots and re-solvable input, not nonlinear restart state.

The dedicated `f7-contact-reactivation` job requires unskipped numerical tests
and complete 24-model/336-stage evidence. It also re-runs the unchanged
24-model/192-stage monotone-excavation benchmark. All preceding public audit
rejection contracts and old workflows remain unchanged. This does not validate
nonlinear soil, arbitrary rebirth topology, deposition, water, friction, piles,
anchors, capacity, experiments or independent RS2/PLAXIS/OGS results.
