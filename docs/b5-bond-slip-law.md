# B5 finite grout bond-slip constitutive law

This is the first numerical prerequisite for the RS2 Anchored Sheet Pile Wall B5 case.
It verifies the local axial grout bond law independently from any embedded-element
assembly or soil/tieback model.

## Contract

Project units are kN and m.

- bond shear q: kN/m of bonded length;
- relative axial slip s: m;
- bond shear stiffness k_b: kN/m2;
- bond strength q_max: kN/m.

The implemented local update is

    q_trial = q_n + k_b * Delta s
    q_{n+1} = clamp(q_trial, -q_max, q_max)

with exact algorithmic tangent k_b in the elastic branch and zero for an outward
perfect-plastic correction. Unloading from the strength surface is elastic.

This matches the RS2 documentation statement that bond strength is force per unit bond
length and bond shear stiffness is force per length per length. The current B5 tutorial
uses k_b = 10,000 kN/m2 and q_max = 5,000 kN/m, which gives an isolated local yield
slip of 0.5 m.

## Verification

Run:

    PYTHONPATH=src python scripts/b5_bond_slip_benchmark.py --require-pass

The strict characterization includes:

- a hard-coded five-increment elastic/yield/unload/reverse-yield path;
- the published RS2 B5 stiffness/strength scale;
- a centered finite-difference check of the smooth algorithmic tangent;
- invalid state/property rejection.

The dedicated b5-bond-slip workflow runs both the verification tests and the strict
characterization script.

## Deliberate boundary

This PR does not create an embedded bolt/soil transfer element. In particular it does
not yet provide the kinematic coupling needed to let an independent tendon axial field
slip relative to the host continuum while remaining embedded transversely.

Therefore this work is a constitutive prerequisite only. It does not reproduce the
RS2 tieback, does not predict the 59 kN tieback force or 71 kNm wall moment, and does
not convert B5 into an external-validation pass.
