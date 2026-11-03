# F7/V5 — Dry staged excavation global gravity equilibrium

This verification adds a **restricted, independent global force budget**
for plane-strain models with gravity loading. It compares integrated weight
of the active continuum and beam elements against prescribed-support
reaction resultants at the end of each construction stage.

## Analytical balance

In the absence of water, horizontal acceleration, imposed displacements,
stage surface loads and prescribed pretension, the expected exterior
force budget per out-of-plane metre is

    W_soil = sum_active_elements (area_e * gamma_e)
    W_beam = sum_active_beams (length_e * A_e * gamma_e)
    expected Rx = 0
    expected Ry = W_soil + W_beam
    residual = (Rx, Ry - W_soil - W_beam)

Continuum areas are integrated using the final FE mesh geometry/shape
quadrature, not the solver's assembled internal-force vector.
Structural beam lengths and self-weights are calculated directly from
the mesh and liner material specifications. Active masks come from
the computed stage, so excavated elements no longer contribute weight.
Interface and bar elements have no separate self-weight in the
current solver.

The numerical acceptance tests check a 4 m wide, 6 m deep two-layer
column with unit weight gamma=18 kN/m3, before and after removal of
its upper 3 m. Expected vertical reactions are respectively

    Ry_before = 4*6*18 = 432 kN/m
    Ry_after  = 4*3*18 = 216 kN/m

T3 and T6 elements are included. A separate active-liner case verifies
that new beam self-weight contributes to the reaction budget and that
the total remains balanced.

## Reporting

The optional study

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

includes a `gravity_balance` array in the JSON output for each stage
and mesh size, and stores its detailed per-stage entry internally. If
the case is outside scope it reports `unsupported` with the reason,
never an invented zero error or a passing status.

## Explicit limitations

This first global force budget intentionally rejects:
- Water pressure or initial groundwater conditions
- Pseudo-static acceleration and stage point/edge loads
- Prescribed displacement and structural pretension
- Cumulative material changes and varying shotcrete maturity
- Axisymmetric analyses

Those effects require separately derived exterior loads and
consistent per-stage integration before extending the acceptance
claim. Also note that a near-zero resultant does not prove local
traction continuity or eliminate point-load singularities.

The next F7 gate is independently assembled **general external-load
and excavation-release equilibrium**, including hydrostatic loading,
beam and interface transfer and the difference between full model
and isolated interface reaction sums. A green CI verifies only
this restricted dry gravity-budget capability.
