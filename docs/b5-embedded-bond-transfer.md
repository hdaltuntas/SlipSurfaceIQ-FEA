# B5 embedded tendon–soil bond transfer

This feature integrates the independently verified scalar grout bond-slip law into the
staged finite-element solver without introducing an artificial transverse penalty spring.
It is the bonded-length transfer prerequisite for the RS2 Anchored Sheet Pile Wall B5 case.

## Kinematics

Each `BOND4` row stores

    [host_a, host_b, slip_a, slip_b]

The two host nodes retain their ordinary continuum displacement DOFs. The two colocated
`slip` nodes are internal scalar coordinates only. At each station the tendon axial
displacement is

    u_t = e · u_host + s

where `e` is the tendon axis and `s` is the scalar tendon/host axial slip. Thus transverse
embedment is imposed kinematically through the host motion; no guessed normal spring
stiffness is added.

The tendon segment extension is

    Delta = e · (u_host,b - u_host,a) + s_b - s_a

and uses the existing `BoltSpec` axial stiffness, tensile capacity, spacing and
pretension contract. The distributed grout transfer uses `BondSlipSpec` at two Gauss
points along each segment.

## Constitutive transfer

For each Gauss point,

    q_trial = q_n + k_b * Delta s
    q = clamp(q_trial, -q_max, q_max)

with stiffness and strength converted to the 2-D model by the bolt out-of-plane spacing.
The element tangent is assembled consistently from the bar axial tangent and distributed
bond tangent. Bar tensile yielding and bond yielding are recorded separately in the
structural flag columns.

## Results

`StageResult.bars[tag]` stores tendon axial force per model width. `StageResult.bonds[tag]`
stores `[slip_m, shear_kN_per_m]` at the two bond Gauss points. Internal scalar nodes are
masked from ordinary displacement output so they cannot be mistaken for physical x/y
mesh displacement.

Model and HDF5 result round-trips preserve the BOND4 block, `BondSlipSpec` and bond result
fields.

## Independent verification

Run:

    PYTHONPATH=src python scripts/b5_embedded_bond_benchmark.py --require-pass

The characterization does not use RS2 response targets. It checks:

- a one-element closed-form stiffness/reaction case;
- the classical fixed-host elastic shear-lag solution
  `F = EA * lambda * tanh(lambda L) * u0`, with `lambda = sqrt(k_b / EA)`;
- monotone mesh convergence over 4, 8, 16 and 32 bonded segments;
- local bond yielding independent of tendon axial yielding;
- model and result persistence.

The dedicated `b5-embedded-bond` workflow is the strict gate for this bounded feature.

Current CI result: **PASS**. The fixed-host shear-lag head reaction converges as follows:

- 4 segments: 32.4946445 kN/m, 1.382% from analytical;
- 8 segments: 32.1627510 kN/m, 0.3464%;
- 16 segments: 32.0794934 kN/m, 0.08667%;
- 32 segments: 32.0586610 kN/m, 0.02167%.

The analytical reference is 32.0517153 kN/m. The one-element closed-form reaction,
local bond-yield separation and persistence checks also pass.


## Deliberate limits

- plane strain only;
- straight conforming host edge chain;
- bonded tendon length only in this document;
- the unbonded/free tendon segment is delivered separately by TIE3;
- no direct groundwater/bond coupling;
- no axisymmetric formulation;
- no claim that the full RS2 B5 tutorial has been reproduced.

The unbonded length and head connection are now assembled in series with this bonded tail;
see [b5-tieback-series.md](b5-tieback-series.md). The full B5 case still requires exact
RS2 constant-force installation pretension semantics and the remaining authoritative
Material 1 properties.
