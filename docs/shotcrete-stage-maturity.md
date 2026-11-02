# Shotcrete capacity by construction stage

The lining designer accepts **28-day reference** elastic modulus (E28), compression strength (fc28),
tensile strength (ft28), and an **initial capacity percentage** p in (0, 100].

- On the first **active user-defined stage** for a composite liner, the shotcrete contribution to
  axial EA and bending EI is multiplied by p/100. The next stage uses 100%.
- Wire-mesh and steel-set contributions remain at 100% in both stages and are not reduced by p.
- The out-of-plane equivalent BEAM2 section is recomputed on stage transition. Previously
  committed beam forces are retained; the maturity change affects **subsequent incremental
  elastic stiffness**, not an instantaneous relaxation or redistribution of existing force.
- The 28-day strength references fc28 and ft28 and their p-scaled values are stored and shown
  by the designer. **They are not currently enforced as beam compressive/tensile/flexural
  failure criteria**: the BEAM2 liner remains elastic.
- Poisson's ratio and unit weight are not artificially reduced with age.
- Existing projects without shotcrete component metadata retain their original beam properties
  and are not automatically subject to a maturity reduction.
- When supports are already active in the Initial state, the first user-defined activation
  transition is not treated as a new shotcrete installation event. Model the installation
  in a construction stage to apply the initial percentage.

Engineering caution: a single percentage for E28, fc28 and ft28 is a user-specified
approximation, not a validated hydration/maturity law. Concrete age, curing, temperature,
strength class and sprayed concrete mix must be established for production analyses.
