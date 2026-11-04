# F7 — Supported-excavation mesh/stage coverage acceptance gate

The optional `examples/f7_excavation_mesh_audit.py` study runs a
three-stage, pile/anchor-supported excavation at three mesh targets
and writes a JSON summary. Previously, an incomplete record set could
still look plausible when individual mesh solves or stages were missing.

This package adds an explicit **report completeness gate**, independent
of how well the FEM solver converges.

## Expected coverage

For each requested mesh resolution, the report must include the same
ordered stages obtained from the canonical native demo model:

1. Pile installation
2. Excavation lift 1
3. Anchor installation and excavation lift 2

The coverage gate rejects missing or duplicate stage entries, unexpected
mesh/stage records, out-of-order stage reporting and any recorded mesh
solve exceptions. Its summary includes the exact expected vs observed
row counts and every missing mesh-stage pair.

## Force balance limitations

The existing three bounded force audits (gravity, dry load, excavation)
are counted separately for every mesh-stage row. `passed`, `failed`,
`unsupported` and missing classifications remain distinct.

`all_force_checks_passed` is true only if every classified check
passed, none failed or was unsupported, and mesh/stage coverage is
complete. It is **not** a general physical acceptance certificate:
many full supported excavation configurations remain outside the
individual dry/gravity force-budget applicability domains. An
`unsupported` result must remain visible instead of being coerced
into a success.

The existing optional audit produces the `mesh_stage_coverage` section
inside `excavation_mesh_audit.json`. A missing or failed mesh-stage
record causes a nonzero CLI exit. A force-check failure or unsupported
status is reported distinctly, rather than being mistaken for
a solver failure.

## Remaining engineering work

The existing three-resolution example has not been executed in this
change. It is still necessary to run full supported-excavation solutions
and validate soil reactions, interface effective stress and water,
pile N/V/M, anchor axial forces and stage-wise applied loads using
independent physical benchmarks. The coverage gate ensures that such
claims cannot rest on incomplete numerical evidence.
