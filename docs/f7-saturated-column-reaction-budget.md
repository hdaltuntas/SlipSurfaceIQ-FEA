# F7 — Saturated-column hydrostatic and gravity reaction benchmark

This verification adds a bounded independent resultant budget for a
rectangular, laterally confined plane-strain soil column. It is based on
dry/saturated **bulk weights** and any free-standing water above the
ground surface, rather than on the FEM pore-force assembly.

## Closed-form reference

For a horizontal groundwater head, with the water table aligned to
mesh element boundaries:

    W_dry = sum(A_e * gamma_unsat) above water table
    W_sat = sum(A_e * gamma_sat) below water table
    F_surface = gamma_water * max(head - surface, 0) * width
    Ry_expected = W_dry + W_sat + F_surface
    Rx_expected = 0

All quantities are per metre out of plane. Saturated unit weight is
**not** replaced with buoyant unit weight in the total reaction budget.
The solver's effective-stress pore contribution must be consistent with
the total weight without double counting displaced water.

The acceptance cases use a 2 m wide, 10 m deep column with
gamma_unsat=17 kN/m3, gamma_sat=20 kN/m3 and gamma_water=9.81 kN/m3.
Expected vertical support reactions:

| Water head (m) | Physical state | Ry expected (kN/m) |
|---|---|---:|
| 0 | Entire soil saturated | 400.00 |
| -4 | Upper 4 m dry; lower 6 m saturated | 376.00 |
| -10 | Entire soil dry | 340.00 |
| +3 | Saturated soil; 3 m ponded water | 458.86 |

The test also lowers water from head 0 to -4 m in a completed FEM
stage and checks that the reported reaction follows the changed total
weight. The initial and stage results are evaluated independently.

## Fail-closed restrictions

The calculation refuses axisymmetry, non-gravity initialization,
non-horizontal piezometric lines, groundwater cutting through an
element, imposed displacement, structural supports/interfaces,
excavation, partial stages, seismic or external pressure loads,
and material changes. Unsupported results carry a reason and are
not mistaken for accepted or zero-force solutions.

The default normalized reaction error tolerance is 1e-6, consistent
with the independent balance acceptance classifiers introduced in
PR #40.

## Engineering scope

This benchmark checks global resultants in a simple one-dimensional
hydrostatic setting. It does not verify local effective-stress profiles
at every Gauss point, seepage gradients, curved excavation boundaries,
joint-water forces, or coupled pile/anchor groundwater reactions.
The full three-resolution supported excavation numerical study remains
a separate F7 acceptance gate.
