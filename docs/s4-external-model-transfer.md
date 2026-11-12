# S4 external model transfer checklist

This note translates the locked SlipSurface S4 case into checks for an independent
RS2 or PLAXIS/PLAXIS2D model. It is not an external solution and it does not close S4.

## Locked physical inputs

Use `docs/data/s4/case.json` as the machine-readable source of truth.

| Item | Required value |
|---|---|
| Analysis | small-strain plane strain, 1 m width |
| Domain | x=-20..20 m, y=-20..0 m |
| Wall | x=0, y=-10.5..0 m |
| Excavation | right side, x=0..20 m, y=-5..0 m |
| Soil | Mohr-Coulomb, E=30000 kPa, nu=0.30, c=0, phi=30 deg, psi=0, gamma=18 kN/m3 |
| Tension treatment | zero tensile strength / Rankine cut-off equivalent |
| Initial stress | K0=0.5 with vertical geostatic stress from gamma=18 kN/m3 |
| Wall axial stiffness | EA=2.0e7 kN/m |
| Wall bending stiffness | EI=2.0e5 kN m2/m |
| Wall shear stiffness | GA=8.0e6 kN/m |
| Wall weight | zero |
| Interface normal stiffness | kn=403846.153846 kPa/m |
| Interface shear stiffness | ks=115384.615385 kPa/m |
| Interface strength | c=0, phi=30 deg, psi=0, tensile strength=0 |
| Bottom boundary | ux=uy=0 |
| Side boundaries | ux=0 |
| Water / surcharge | none |
| Wall tip | translation shared/tied to soil; rotation free |

The physical sequence is: K0 initial state, interfaces present with the initial field,
stress-free wall installation, then full removal of the right-hand 5 m excavation.
Do not reset displacements unless the external program's internal convention requires it
without changing the physical state being compared.

## RS2 mapping

Use a Structural Interface for the wall so that the support is sandwiched between a
joint on each side. Define the liner stiffness from the locked EA/EI/GA values and define
both joints manually with the locked normal/shear stiffness and Mohr-Coulomb strength.
Do not leave material-dependent or default joint stiffness enabled.

Check the structural-interface end condition carefully at y=-10.5 m. The benchmark tip
is not fixed and not a free independent wall node: its translations are tied to the soil
while rotation remains free.

RS2 joint settings must not introduce tensile capacity. Verify the field stress and
staged excavation sequence against `case.json`. If RS2 cannot reproduce the required
separate interface/wall activation history in the chosen modelling route, record that
difference and leave `input_match.stages=false`; the result is then informative only.

## PLAXIS / PLAXIS2D mapping

Use a plate for the wall with interfaces on both sides. Modern PLAXIS material scripting
supports direct interface stiffness input (`knInter` / `ksInter`) when interface
stiffness determination is Direct; use the locked kn and ks rather than an Rinter-derived
default.

Use the K0 procedure for the initial soil state and Staged construction for wall/interface
activation and excavation. Set both positive and negative interfaces consistently.
The interface virtual-thickness setting must not be allowed to change the target direct
normal/shear stiffness.

The wall-tip connectivity must reproduce the locked translation tie to the soil. If a
standard plate/interface configuration creates a different tip kinematic condition,
leave `input_match.tip_connection=false`; do not tune the SlipSurface model to match it.

## Required export

At the final excavation stage export the signed wall bending moment versus depth with
no gap larger than 1.0 m and the horizontal wall-head displacement. Convert signs before
writing `external.csv`:

- depth positive downward from wall head;
- moment converted to SlipSurface `M_up_kNm_per_m` convention;
- wall-head ux positive to the right.

Copy `external-template.csv` and `external-meta-template.json`, fill them from the
independent solution, and only set an `input_match` flag true after that item has been
checked.

Then run:

```bash
python scripts/s4_external_compare.py --require-pass \
  --json s4-external-report.json --markdown s4-external-report.md
```

The maximum-moment difference is the release criterion. The full moment field and
wall-head displacement are retained as diagnostics so an apparently acceptable scalar
peak cannot hide a sign, shape or displacement discrepancy.
