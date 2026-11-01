# Phase 3 structural verifications

## S1 — no-slip elastic tunnel

Reference: Einstein, H.H. and Schwartz, C.W. (1979), *Simplified Analysis for Tunnel
Supports*, ASCE 105(GT4), 499–518, [DOI](https://doi.org/10.1061/AJGEB6.0000786).
The equations and parameters are also published in Itasca’s own
[verification example](https://docs.itascasoftware.com/itasca960/flac3d/zonesel/test3d/Liner/LinedCircularTunnel/LinedCircularTunnel.html).
`test_s1_lined_tunnel.py` evaluates this closed form independently of the solver code.

Plane strain, a quarter circle, radius 5 m; vertical/horizontal initial stress
600/300 kPa. Soil E=48 MPa, ν=0.34; liner E=25 GPa, ν=0.15, thickness 0.125 m.
The liner is initially force-free; it is activated in the same stage as the excavation
relaxation. Surface loads that preserve the initial stress are applied on the outer
boundary. Rotation is zero at the symmetry ends. No weight is added. The liner and the
soil share nodes: the **no-slip** condition.

The analytical compression-positive T has the opposite sign to N in the tension-positive
kernel. The direction of M is fixed by the existing orientation of the liner edges.
The comparison is not only of peak values: it is the maximum absolute difference of the
signed N and M fields around the whole perimeter; the denominators are the maximum
absolute value of the corresponding reference field. Element end forces are averaged to
the midpoint. The acceptance limit is 5% in both fields.

| Mesh (radial × circumferential) | Outer boundary | N field error | M field error |
|---|---|---|---|
| 8 × 16 | 20R | 0.391% | 1.023% |
| 16 × 32 | 20R | 0.268% | 0.157% |
| 24 × 48 | 20R | 0.234% | 0.043% |
| 40 × 80 | 40R | 0.082% | 0.723% |

Refining the mesh at 20R reduces both errors; the 40R check is also inside the tolerance.
Because the outer-boundary error and the element/thin-ring idealisation error can partly
cancel, the 40R result is not required to give a smaller moment error.
This test does not verify a full-slip liner solution or plastic liner behaviour.

## Goodman interface

`test_interfaces.py` checks, for both IFACE4 and IFACE6, force balance, rigid motion,
the element tangent by finite difference, the equal-and-opposite effect of water
pressure on the two faces, and that trial integration does not change the committed
state. On T3/T6/Q4/Q8 meshes it checks node duplication twice, separation of the liner
from the two soil faces, and that the open interface tips inside stay shared.

The traction return treats the three linear yield planes together. In every candidate
active set the plastic multipliers must be non-negative and the result must satisfy
every yield condition. The tangent is computed from the derivative of that same active
set. Additional tests:

- Finite-difference tangent for positive/negative slip, elastic, tension, and combined returns.
- Dilatant slip can return a trial that is in tension onto the shear surface in compression.
- Nearest-point comparison with an independent constrained optimisation for associated flow.
- Admissibility of 1000 random trials in each of four material states.
- The inner-tip connection of a two-sided interface is independent of left/right insertion
  order; single/double embedded tips on T3/T6/Q4/Q8, and the wall response in asymmetric elastic soil.
- ks=0, φ=0, c=0, the natural apex, closing the tension limit, and closure after opening.

The previous tension-first clip could choose the dilatant-slip return incorrectly.
A trial is no longer clipped immediately just because it is in tension. A zero tangent
in the fully open/slipped direction is not replaced by artificial stiffness; a structure
that is truly unsupported can be physically singular. Detailed fracture energy, a
permanent gap, and cyclic damage were not added to the scope of this elastic–
perfectly plastic Goodman model.

## S4 — work record closed, external comparison deferred

`test_s4_sheet_pile.py` uses two separate **structural** references. A small continuum
block that is fixed and unloaded satisfies the continuum-block requirement of the
existing mixed-element driver; it is not tied to the sheet pile and does not replace
the reference soil.

### Beam–spring reference

5 m excavation, 10 m embedment; EI=2×10⁶ kN·m²/m, GA=4×10⁶ kN/m, k=20000 kN/m³,
γ=18 kN/m³, Ka=1/3. In the exposed part q(z)=Ka·γ·z; in the embedded part there is a
Winkler reaction. Both ends of the wall are free against moment and shear. The reference
is the solution of the two-piece constant-coefficient Timoshenko differential system by
the **matrix exponential**:

- u′ = θ − V/GA
- θ′ = M/EI
- M′ = V
- V′ = q − k·u

The four fields are continuous at the excavation level; the load and the spring
coefficient change there. The linear load above is integrated exactly with two extra
states. Two unknown initial values are found from the end conditions with an independent
2×2 system; the reference does not use a finite-element mesh.

| Element count | FE maximum M (kN·m/m) | Reference maximum M, at element centres | M field error |
|---|---|---|---|
| 60 | 192.784829 | 193.134170 | 0.207% |
| 120 | 193.101793 | 193.190126 | 0.052% |

End displacement, the whole moment field, mesh convergence, total horizontal force, and
total moment balance are checked. The BAR2 springs are elastic in both directions; they
are not interpreted as a cohesionless soil model whose plasticity has been verified.

### Rankine pressure diagram

φ=25°, 30°, 35°; H=5 m, γ=18 kN/m³. Ka=tan²(45°−φ/2), Kp=1/Ka.
The net pressure q(z)=γ[Ka·z−Kp·max(z−H,0)] and an idealised single tip reaction are used.
D is found from moment balance about the toe, Ka(H+D)³=Kp·D³. The independent integral:
M(z)=γ[Ka·z³−Kp·max(z−H,0)³]/6. The location of the maximum moment is found from the
zero of the shear. The FE field, the maximum moment, the total force, and the vanishing
of the end moment are checked to within 1%. This diagram is not fitted to the Winkler
result; they are two separate boundary-value problems.

**Full S4 has not passed yet:** these checks do not compare the staged excavation +
continuum soil + two-sided interface + sheet-pile model with the user’s independent
sheet-pile tool. The remaining 10% maximum-moment criterion must be verified on that
equivalent scenario. By the 21 October 2026 user decision the S4 work record was closed
and this external comparison was deferred. The Gate 3 verification criterion is not
considered passed; Phase 4 was not started.

## Python 3.10 CI reference test

In the previous CI, SciPy 1.15.3 hit the iteration limit in an SLSQP test that used a
finite difference on the spectral maximum. The test was accepting the objective value
of a failed or infeasible optimisation as the reference. The comparison was turned into
a scaled convex QP in principal-stress space with six linear MC constraints and an
analytical gradient. Success of the optimisation and the constraint residual are
mandatory checks; production stress tolerances were not relaxed.

## Continuum sheet-pile example: legacy runs without a cut-off

The failures below belong to the old model with no Rankine flow. The explicit
Rankine-apex model completes the full excavation. The current comparison inputs, the
tip connection, the wall-field outputs, and the step/stage sensitivity are in
[s4-comparison.md](s4-comparison.md). Full S4 is still open because the external
reference is missing.

`examples/sheet_pile_staged_excavation.py` has a 10.5 m sheet pile and a 5 m excavation
in a 40×20 m sand domain. MC: E=30000 kPa, ν=0.3, c=0, φ=30°, ψ=0, γ=18 kN/m³.
Wall: E=2×10⁸ kPa, ν=0, A=0.1 m²/m, I=0.001 m⁴/m, As=0.08 m²/m. A Goodman interface
on both sides with R=1 and a virtual thickness of 0.1 m; K0=0.5 initial stress; first
the force-free wall is installed, then the 5 m soil region on the right is removed.
The bottom boundary is held in both directions; the side boundaries are held horizontally.
There is no water.

```bash
PYTHONPATH=src python examples/sheet_pile_staged_excavation.py --size 0.5
# A record is written only if the solve completes:
PYTHONPATH=src python examples/sheet_pile_staged_excavation.py --size 0.5 --output pile.ssproj
```

| Local mesh size | Nodes | Observation |
|---|---|---|
| 0.50 m | 3889 | With the local MC return guard, the default T6 excavation stops at λ=0.98698 |
| 0.25 m | 5380 | With the same guard, the default T6 excavation stops at λ=0.88966 |

The previous moment of 165.280601 kN·m/m and the λ=0.8938 record came from code that
continued a failed local return with the elastic trial stress; they are not used as a
verified result. The mixed-mesh/integration table is in [mixed-mesh.md](mixed-mesh.md);
reproduction and the effect on P4 are in [nonlinear-diagnostics.md](nonlinear-diagnostics.md).

This open failure was not covered by a success tolerance. An independent check that
separates collapse from a numerical convergence problem, and a fine-mesh solution, are
required. The example is therefore **not an S4 benchmark pass, a factor of safety, or
a mesh-independent design result**. The Rankine/Winkler tests are different
boundary-value problems; a direct 10% difference is not computed against this moment.

The first run of the example also exposed an old bug: when excavation was done without
changing the block name, the tangent cache of the old active Gauss points was reused.
The cache is now validated with the full system/active-set key. Empty DOF and stiffness
arrays were also fixed so that a separate block can be deactivated entirely.
`test_nonlinear_staging.py` compares excavation in the same and in separate blocks,
activation of equal numbers of different elements, and the MC solution of backfill on
an elastic path against an independent elastic material.
