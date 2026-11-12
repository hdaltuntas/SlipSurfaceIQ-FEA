# PLAXIS Drain / Dupuit external groundwater benchmark

This benchmark reproduces the published PLAXIS **Drain** groundwater-flow verification
with the SlipSurfaceIQ-FEA steady seepage kernel.

It is an external validation benchmark, but it is not a claim of general PLAXIS
equivalence.

## Published reference problem

PLAXIS describes a plane-strain soil block with a drain at the centre:

- block length: 50 m;
- block height: 20 m;
- vertical drain at x = 25 m;
- external phreatic level / total head: 18 m;
- drain head: 10 m;
- saturated isotropic permeability: 1 m/day;
- bottom boundary: impermeable;
- remaining outer groundwater boundary: open/seepage;
- PLAXIS Standard/Coarse unsaturated hydraulic data set.

The analytical one-side discharge from Dupuit's unconfined-flow expression is

    Q = k (H1^2 - H2^2) / (2 L) = 4.480 m3/day/m

with L = 25 m, H1 = 18 m and H2 = 10 m.

The PLAXIS 2D validation publishes approximately **4.489 m3/day/m** through one side
of the soil, corresponding to about 8.98 m3/day/m extracted by the central drain.

## SlipSurface representation

The model uses a conforming internal line from y=0 to y=10 m at x=25 m with total
head 10 m. The portions of the two vertical outer boundaries below y=18 m receive
head=18 m; the portions above the phreatic level and the top boundary are potential
seepage faces. The bottom remains impermeable.

Saturated conductivity is converted from 1 m/day to SI m/s for the solver.

The PLAXIS Standard Coarse hydraulic data set is based on the Hypres topsoil series.
SlipSurface uses the published alpha=3.83 1/m and n=1.3774 values. A preserved model
boundary is important: current SlipSurface's Mualem relative-conductivity expression
fixes the pore-connectivity exponent at 0.5, whereas PLAXIS exposes a separate Hypres
connectivity parameter. Therefore the unsaturated constitutive curves are not claimed
to be bit-for-bit identical.

The integrated discharge result is nevertheless compared independently to both the
closed-form Dupuit value and the published PLAXIS 2D value.

## Mesh study and acceptance

Three unstructured T6 mesh levels are run. The acceptance criteria were fixed after the
initial characterization:

1. finest one-side discharge within 1% of Dupuit 4.480 m3/day/m;
2. finest one-side discharge within 1% of PLAXIS 2D 4.489 m3/day/m;
3. medium-to-fine discharge change within 1%;
4. relative global flow-balance residual <= 1e-8;
5. solved total-head extrema remain 10 and 18 m.

Initial characterization:

| Mesh | Nodes | One-side Q (m3/day/m) | Difference vs Dupuit | Difference vs PLAXIS |
|---|---:|---:|---:|---:|
| coarse | 2947 | 4.47962 | 0.009% | 0.209% |
| medium | 5723 | 4.48790 | 0.176% | 0.024% |
| fine | 11455 | 4.49162 | 0.259% | 0.058% |

The medium-to-fine change is about 0.083%. The fine-mesh global flow-balance residual
is of order 1e-15 relative.

## Reproduce

Run:

    PYTHONPATH=src python scripts/plaxis_drain_benchmark.py --require-pass

The dedicated GitHub workflow writes machine-readable JSON and a Markdown summary.
The workflow must pass before this benchmark can be counted as accepted external
evidence.

## Sources

The benchmark is based on Bentley's PLAXIS “Verification: Drain” article and validation
report. The published PLAXIS result is compared to Dupuit's analytical unconfined-flow
formula. The PLAXIS model itself uses unsaturated flow above the phreatic surface, which
explains its small difference from the Dupuit approximation.
