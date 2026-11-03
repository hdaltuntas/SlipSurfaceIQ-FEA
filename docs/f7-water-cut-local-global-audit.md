# F7 — Combined local and global error audit for mesh-cut water tables

This verification stage combines two **independent analytical references**
for the same simple rectangular plane-strain hydrostatic column:

1. The exact dry and saturated areas obtained by polygon clipping at the
   horizontal water table, combined with bulk unit weights, produce the
   external vertical reaction target.
2. The one-dimensional hydrostatic formulas produce exact pore pressure
   and effective vertical stress at every Gauss-point elevation.

The benchmark is a 2 m by 10 m homogeneous drained elastic column, with
gamma_unsat = 17 kN/m³, gamma_sat = 20 kN/m³ and horizontal water
head -2.37 m. The exact vertical reaction reference is **385.78 kN/m**.
The water table crosses elements in every mesh resolution.

## Reproducible calculation

    python examples/f7_water_cut_field_audit.py --rows 2 4 8 --element T3 --output f7_water_cut.json

The tool runs actual FEM column solutions at three mesh resolutions and
reports separately:

- Global reaction error relative to the exact clipped area/weight result
- Local maximum/RMS pore pressure and effective vertical stress errors
- Per-mesh independent passed/failed classifications and a combined status

The command exits nonzero when the finest mesh fails **either** gate.
A correct total reaction is not evidence of correct local effective
stresses. T3's constant-strain approximation can lead to significant
local stress error even while reactions balance exactly. The tool
preserves this failure, rather than relaxing the reference tolerance.

## CI scope

The regression suite checks error classification and reference consistency
using synthetic values, plus an actual two-resolution T3 FEM solution.
The full default three-mesh study remains an opt-in audit.

## Engineering limitations

This is not a supported excavation, seepage-flow, nonlinear material,
or multi-material benchmark. It does not validate pile, anchor or
zero-thickness interface force transfer, nor does it quantify local
stress singularities at concentrated loads. F7 acceptance still
requires a full supported excavation verification with groundwater.
