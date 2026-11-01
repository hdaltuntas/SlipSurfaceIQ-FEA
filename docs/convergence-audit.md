# Convergence diagnostics: geometry, the matrix, and Newton options

This study examines, with separate checks, the suggestions of singularity, locking,
softening, element quality, and solution method on the sheet-pile example. The method,
the tolerances, and the material rules of the production solver were not changed by
this diagnostic study.

A later independent replay of the local-rejection inputs showed, for both the sheet
pile and P4, that the ψ=0 choice with no Rankine flow cannot bring the mean stress
down to the apex on some trial increments. The records, the trace-balance argument,
and the substep table:
[nonlinear-diagnostics.md](nonlinear-diagnostics.md#independent-replay-of-the-local-inputs).
This result is not proof of the stability of the whole mesh/element, or of the absence
of global equilibrium.

## Current model and methods

The sheet-pile numerical records in this document were taken before the embedded-tip
connection of the two-sided interface was fixed. The old model split the tip on the
second side that was added; the current code keeps the tip shared on both sides. The
old values are diagnostic history; the current model and the replays are in the
[S4 protocol](s4-comparison.md).

- Soil ν=0.30, c=0, φ=30°, ψ=0; ideal elastoplastic MC. No strength drop that depends
  on an internal variable. No point external load; supports are on the bottom and side edge sets.
- The excavation corner (0, −5), the sheet-pile tip (0, −10.5), and the top of the wall
  (0, 0) are diagnostic points. These are known locations specific to this example; a
  general automatic corner detector was not added.
- Default NR + line search; the alternatives `mNR`, `hybrid`, and `initial` already existed.
  `initial` is the elastic stiffness of the current stage/active set; it does not hold one
  global matrix from before excavation fixed across every active-set change.
- A step that does not converge is rolled back and Δλ is halved; after a fast acceptance
  it grows by a factor of 1.5. Residual stall can cut some steps before max_iter is reached.

Elastic locking from ν≈0.5 is not the primary finding for this model; that does not
mean plastic locking is excluded on every load path. Q4 has B-bar; Q8 has default 2×2
and high 3×3 integration. A T3+Q4/T6+Q8 mixed mesh is not a u–p mixed formulation;
there is no separate pressure unknown yet. A u–p choice for incompressibility needs a
stable element pair/formulation
([MoFEM primary documentation](https://mofem.eng.gla.ac.uk/elasticity_mixed_formulation.html)).

The absence of a softening parameter does not strictly exclude mesh dependence:
structural softening and loss of ellipticity can also appear with ideal plasticity
under non-associated flow.
[Sabet–de Borst (2019), the authors’ institutional archive](https://eprints.whiterose.ac.uk/id/eprint/148931/).
No acoustic-tensor/ellipticity analysis was done on this model; no localisation diagnosis was made.

## Method comparison at the same load level

T6+Q8, h=0.50 m, high, explicit σt=0, excavation λ=0.05; the same force/energy
tolerances, line search, and max_iter=30. The iterations below are for the excavation
stage only; they include rejected trials.

| Method | Iterations | Accepted / rejected steps | Final normalised force residual |
|---|---:|---:|---:|
| NR | 6 | 1 / 0 | 1.15e-5 |
| hybrid | 6 | 1 / 0 | 3.47e-6 |
| mNR | 129 | 4 / 3 | 9.08e-5 |
| initial | 172 | 4 / 3 | 9.96e-5 |

All four runs complete the target λ=0.05. For mNR/initial the reason of the three cuts
is the iteration limit; in this example NR/hybrid finished in fewer iterations. This is
not a claim that the full excavation was verified with every method, or that NR is
better on every model.
`test_nonlinear_diagnostics.py` also checks that, after a local error, the first 0.5
step is cut twice and accepted at 0.125, and that the next fast step grows to 0.1875.

Modified Newton iterates with one step’s matrix
([OpenSees](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/algorithm/ModifiedNewton.html)).
That operation by itself does not guarantee that positive-definiteness or singularity
errors disappear. The initial elastic matrix is also singular if a support is missing
or a DOF is disconnected. For non-associated MC, unsymmetric LU is already used; an SPD
condition is not required.

## Corner and mesh quality on the elastic reference

For diagnosis only, the soil was made elastic with the same geometry and elastic
constants; the interface kn/ks values were kept, and slip/opening was suppressed with
a strength of 1e20 (φ=ψ=0). This different reference model is not used in place of the
real MC/interface solution. All three meshes were compared at the same full-excavation
λ=1 state. The stress measure is the 3D tensor Frobenius norm at the Gauss points; the
shear component is counted twice in the norm.

| h (m) | Largest cond₂(J) | Smallest scaled J | GP closest to the corner (m) | Peak norm for r≤0.75 m at the corner (kPa) | Weighted mean for 0.5≤r≤1 m (kPa) |
|---|---:|---:|---:|---:|---:|
| 0.50 | 4.706 | 0.4736 | 0.05036 | 349.87 | 100.96 |
| 0.25 | 4.190 | 0.4721 | 0.02333 | 485.66 | 100.75 |
| 0.125 | 4.148 | 0.4707 | 0.00996 | 907.60 | 100.95 |

Every sampled detJ is positive. The smallest corner angle is 28.08–28.27°, and the
largest existing aspect measure is 4.73–4.98. The shape conditioning of J does not
worsen as the mesh is refined. detJ shrinking with h² is not, by itself, a bad element.
T6/Q8 midside nodes are included in the J calculation. Gauss sampling does not guarantee
positive J at every point of a curved cell.

The peak growing as the Gauss point approaches the corner, while the field at a fixed
distance stays stable, is **consistent with** an elastic corner singularity; three meshes
do not prove that mathematically. An elastic stress singularity does not mean that the
plastic material produces infinite stress in every case, or that Newton can never converge
([COMSOL geometry documentation](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_geometry.23.003.html)).
If there is a physical corner radius it should be used in a sensitivity study; the
geometry must not be rounded silently in order to obtain numerical success.

## Conditioning of the stiffness matrix

For the free-DOF matrix K_ff, a deterministic one-norm condition-number lower estimate
at t=1 is reported, both raw and with the scaling S K_ff S (S_ii=1/sqrt(|K_ii|)).
These estimates are not an SPD test, an exact condition number, or a collapse measure.
The raw values are affected by the units of rotation and translation DOFs. The global
NumPy RNG state is not changed.

| Elastic reference h (m) | Raw κ₁ estimate | Scaled κ₁ estimate | LU U growth |
|---|---:|---:|---:|
| 0.50 | 3.120e7 | 4.680e6 | 1.000 |
| 0.25 | 7.646e7 | 1.664e7 | 1.000 |
| 0.125 | 3.418e8 | 6.603e7 | 1.000 |

The global condition number increases as the mesh is refined; in all three runs LU
factorisation and the equilibrium solve completed. The increase is therefore not counted
directly as a sliver/zero-pivot diagnosis. In the uncut mixed/high h=0.50 m failed run,
at the last accepted λ=0.14826255: the last accepted tangent has κ₁≈3.288e7,
scaled≈6.195e6, and LU succeeded. The last rejection reason is `material_return`, not
`singular_tangent`. This matrix belongs to the **last accepted state**; it is not claimed
that the spectrum of every rejected iteration was examined.

## Arc-length status and the verification limit

Arc-length was not added in this change. It is a separate continuation method for
following past a limit point with a load/displacement scale and an extra path equation
([OpenSees](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/integrator/ArcLength.html)).
To demonstrate snap-through/snap-back, direction choice on an analytical equilibrium
curve, decrease of the load, residual equilibrium, and the path-constraint error must
be tested independently, and then rollback of the history variables and the FEM bridge.
Arc-length does not by itself remove inadmissibility of the local return, a corner
singularity, or mesh dependence. The present diagnosis does not prove a physical limit
point. P4 and the independent S4 remain open.

## Reproduction

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --soil-tension 0 --excavation-factor 0.05 --method mNR --audit --output /tmp/pile-mnr.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.125 --mixed --gauss-order high --elastic-soil --elastic-interfaces --audit --output /tmp/pile-elastic.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --audit --output /tmp/pile-failed.json
```

In the first command the method is changed among NR/hybrid/mNR/initial; in the second,
the size is changed among 0.5/0.25/0.125. The exit code of the third command is 1; this
expected open failure is not hidden. `--audit` does extra LU factorisations; it is not
used for performance timing. The diagnostic data is JSON; it is not a solver restart file.

## Algorithmic tangent and regularisation proposals

Local finite-difference tests already exist for the MC principal-stress return/tangent
and for the Goodman return. `test_newton_convergence.py` checks an asymptotic
log-residual slope >1.6 for associated Tresca and non-associated MC, and a lower slope
for mNR. Classical quadratic convergence needs regularity and a non-singular tangent;
it is not guaranteed for every iteration at a corner/active-set change. Using an
elastic/inconsistent tangent instead of the algorithmic derivative can spoil convergence;
that distinction is also made explicitly in the
[MOOSE primary documentation](https://mooseframework.inl.gov/moose/source/materials/ComputeMultipleInelasticStress.html).

Additional global check: `test_global_algorithmic_tangent.py` runs eight cases,
T3+Q4 and T6+Q8, default/high, slip/opening. MC, the beam, and a two-sided interface
with dilatancy are assembled; in three free-DOF directions, at two perturbation sizes,

    K_ff v ≈ [f_int(du+h v) − f_int(du−h v)]_free / (2h)

is compared. The relative error is <2e-6; the elastoplastic and interface flags do not
change under the perturbation; the input stress/history arrays are preserved. The
unsymmetric part of the tangent that comes from non-associated flow is also preserved.
These are algebraic derivative tests at a non-zero trial increment; they are not a model
equilibrium benchmark or proof of every possible corner path. Flags staying the same
does not by itself prove that every MC sub-active set stayed the same; agreement of the
derivative at the two h values is therefore checked as well.

**Dynamic relaxation:** explicit time integration may not need a global K factorisation;
it does not create a static equilibrium that does not exist. The artificial mass,
damping, and critical time-step choice must be verified with force-residual, velocity,
and kinetic-energy criteria. Critical damping is not a single number for every mode.
In ongoing collapse the force residual and the motion may not damp out;
[Itasca’s equilibrium documentation](https://docs.itascacg.com/itasca900/flac3d/docproject/source/modeling/problemsolving/equilibrium.html)
discusses that distinction. It has not been added yet.

**Perzyna / Duvaut–Lions:** this needs a separate, time-dependent material definition.
Its own stress update and algorithmic derivative must be derived; sensitivity to
viscosity/relaxation time, Δt, and loading rate, dissipation, and a suitable
rate-independent reference must be checked. A single small-viscosity run is not
verification of the η→0 limit; it must also be shown that the limit gives a
mesh-independent/non-singular solution. Allowed overstress in a new model is not the
same thing as accepting the `255` return error of the existing rate-independent model.
[Wang–Sluys–de Borst (1997), primary source](https://pure.tue.nl/ws/portalfiles/portal/4389528/605201.pdf).
A viscoplastic model was not added in this change; no artificial viscosity was put into
the production behaviour.

**Non-local / gradient / Cosserat:** these need an internal length and material
calibration; averaging the output plastic strain afterwards with neighbouring Gauss
points is not enough. The derivative of a non-local internal variable also couples
neighbouring element DOFs; the current local CSR pattern/assembly must be extended
accordingly. Boundary weights and h/internal-length sensitivity must be verified.
Cosserat also contains an independent rotation and a couple stress; it is not the same
formulation as a scalar Gauss-point average. These methods target localisation/mesh
objectivity; that is a separate subject from the u–p volumetric-locking solution.
A primary example of the need for regularisation even in ideal, non-associated plasticity:
[Sabet–de Borst (2019)](https://eprints.whiterose.ac.uk/id/eprint/148931/).
These formulations have not been implemented yet.

Priority: with a verified local update/tangent and an independent P4/S4 reference kept,
equilibrium-path tracking and new material models that contain a rate or a length
should be developed as separate options. Instead of turning on several artificial
mechanisms at once and counting convergence as success, each new option should be
verified with its own equilibrium, time, and mesh tests.
