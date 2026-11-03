# F7 — Local hydrostatic and effective-stress verification

This package complements the F7 total support-reaction comparisons with
**Gauss-point** validation of pore water pressure and vertical effective
stress. A global force balance can pass even when local stress fields are
incorrect.

## Independent 1D hydrostatic reference

For a homogeneous, laterally restrained, drained elastic soil column with
ground surface elevation `surface`, piezometric elevation `head`, and
Gauss-point elevation `y`:

    depth = surface - y
    dry_depth = min(depth, max(surface-head, 0))
    sat_depth = depth - dry_depth
    total_vertical_overburden =
        gamma_unsat*dry_depth + gamma_sat*sat_depth
        + gamma_w*max(head-surface, 0)
    pore_pressure = gamma_w*max(head-y, 0)
    sigma_yy_effective = -(total_vertical_overburden - pore_pressure)

Stress uses the solver's **tension-positive** convention; pore pressure
is compression-positive. The derivation uses bulk saturated weight,
not buoyant unit weight in the total force budget.

The postprocessor compares these analytical quantities with actual
FEM `StageResult.pore` and `StageResult.sig[..., 1]` at Gauss-point
coordinates, for every active element. It reports absolute maximum
and RMS errors, sample count, normalized maximum error, and
`passed`/`failed`/`unsupported` status.

## CI acceptance cases

A 2 m wide × 10 m deep column with
`gamma_unsat=17 kN/m³`, `gamma_sat=20 kN/m³`, and
`gamma_w=9.81 kN/m³` is solved for T3 and T6 with two mesh
resolutions.

The initial groundwater head is 0 m, then lowered to -4 m in a
completed stage. T6 tests require pointwise pore and effective-stress
agreement at Gauss points. Linear T3 triangles have constant strain
within each element and do not exactly reproduce a linearly varying
geostatic stress; their nonzero errors remain visible and the initial
stress error must decrease with mesh refinement. A separate deliberately
corrupted pore-pressure output must produce a **failed** status, not a
false success.

This is a genuinely local acceptance criterion, complementary to
the PR #42–44 global force budgets.

## Scope and remaining limitations

The reference is only for full rectangular, single-material,
gravity-initialized, drained elastic plane-strain columns with
horizontal piezometric lines and no added loading, structures,
excavation or undrained behavior. It is not a general geostatic
reference for layered heterogeneous models, sloping water tables,
hydraulic gradients, groundwater flow or nonlinear constitutive
return mapping.

The next F7 steps are mesh-refined local stress comparisons at
water-table cuts and staged soil–interface–pile–bolt force transfer,
with strict separation of independent physical references from
self-consistency checks.
