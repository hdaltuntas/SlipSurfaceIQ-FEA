# F7 — Exact water-table geometry clipping reference

The previous saturated-column acceptance gate accepted only horizontal
water tables coincident with element edges. That constraint is retained
as the default. This package adds a **separate, opt-in** exact geometric
reference when a water table cuts interior elements.

## Independent geometric reference

Each straight-sided T3/T6/Q4/Q8 element is clipped at `y=head`.
The clipped polygon area is calculated with the shoelace formula:

    A_sat = area(element intersection {y <= head})
    A_dry = A_element - A_sat
    W = sum(gamma_unsat*A_dry + gamma_sat*A_sat)

For a rectangular column, this is combined with any ponded-water
pressure above the surface. It is an external closed-form reference,
not an equivalent of FEM pore-pressure Gauss integration.

If the water table cuts an element, the current FEM implementation
may approximate the dry/saturated boundary with numerical quadrature.
The resulting **measured difference** must not be hidden by forcing
the reference to agree with the solver.

## Usage and acceptance

The legacy call `saturated_column_budget(model, result)` remains
strict: it raises `ValueError` for water tables that cross elements.

The opt-in call

    saturated_column_budget(model, result, exact_cut=True)

returns the independent weight and its normalized reaction discrepancy.
`exact_cut_saturated_column_budget_by_stage` classifies the result
as passed, failed, or unsupported using the existing F7 tolerance.
It does **not** automatically certify cut-element results.

For a 2 m wide, 10 m deep column with water table at -2.5 m,
gamma_unsat=17 and gamma_sat=20 kN/m3, the exact total weight is

    Ry_reference = 2*(2.5*17 + 7.5*20) = 385 kN/m.

The unit/regression suite checks polygon conservation and dry/wet
areas for T3, T6, Q4 and Q8, exact unaligned weight, and refusal
of curved quadratic sides. A curved edge cannot safely be represented
by its corner polygon.

## Remaining scope

This is a simple horizontal piezometric reference for straight-sided
rectangular soil columns. It is not a coupled seepage, general
excavation, interface water-pressure or structural reaction validation.
A small global force residual also cannot establish correct local
effective-stress profiles or mesh convergence.

The full three-resolution supported-excavation audit remains a
separate F7 acceptance requirement.
