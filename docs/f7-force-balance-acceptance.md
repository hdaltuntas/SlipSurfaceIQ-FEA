# F7 — Force-balance acceptance classification

The gravity, dry exterior load and newly exposed excavation face audits
previously marked every successfully *calculated* budget `checked`, even
if the reported relative force residual was large. This conflated
calculation completeness with numerical equilibrium acceptance.

## Acceptance rule

Each completed scoped budget is now evaluated against a stated default
dimensionless tolerance of `1e-6`:

- `passed`: finite nonnegative normalized resultant error at or below tolerance
- `failed`: error greater than tolerance, negative, NaN or infinite
- `unsupported`: outside the physical assumptions of that budget, with reason

A `failed` result includes the numeric error and an explanatory reason.
No result is silently marked successful because the underlying FEM solver
returned a stage solution or because the audit code completed.

The optional multi-mesh staged excavation JSON report includes a new
`force_balance_acceptance` summary by audit type with counts for passed,
failed and unsupported stages. `fully_verified` is true only when
**every reported stage** passed that audit and none are unsupported.
`all_supported_passed` means at least one stage was examined and none
of the evaluated stages failed, but unsupported stages can still exist:
it is not a complete-model engineering validation claim.

## Reproducible CI coverage

Regression tests cover threshold equality, just-above-threshold
failure, nonfinite and negative values, invalid tolerance, unsupported
model conditions, all three stage wrappers, aggregate status and
unknown-status rejection.

The existing 4 m x 6 m gravity reaction tests now require `passed`,
not merely `checked`.

## Engineering boundaries

This is a **classification and reporting** improvement, not a new
independent constitutive benchmark. The three force budgets retain
their separate restrictions. For supported pile/anchor models,
the dry active-geometry budget can report `unsupported` because
interface water, beam/bolt force and structural activation terms are
not fully assembled into one independent equilibrium reference.
In particular, `fully_verified` must not be interpreted as a product
release certificate without mesh convergence and physical benchmarks.

The optional three-mesh excavation run remains non-CI-gated.
