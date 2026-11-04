# Local three-mesh supported-excavation evidence — 4 November 2026

The actual native pile/anchor excavation was executed locally on Linux using
Python 3.14.9, NumPy 2.5.4, SciPy 1.18.1, Numba 0.68.1, h5py 3.16.0,
PySide6 6.12.0, Shapely 2.2.0 and ezdxf 1.4.4. Base commit: `8f608fc`,
with the working-tree per-interface ledger checks and evidence-review changes.
This is a local execution record, not a completed GitHub Actions run.

Reproduction from the repository root:

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python -u examples/f7_excavation_mesh_audit.py \
  --sizes 2.5 1.8 1.2 --output-dir /tmp/f7-review-20261104
python scripts/f7_evidence_review.py /tmp/f7-review-20261104/excavation_mesh_audit.json
```

The audit exited with code 0. All nine requested mesh/stage rows completed,
with no mesh or solver exceptions. Structural output coverage, interface moment
acceptance and the strengthened interface-transfer ledger passed. Gravity force
balance passed in all nine rows. Standard output/error was empty.

Dry-load and excavation force budgets were **unsupported in all nine rows**:
structure activation and coupled structures/interfaces require a separate force
budget. These results do not establish continuum–pile–anchor global equilibrium
or independent physical validation.

The installation-stage pile peak moment was 0.0859951, 0.0531650 and 0.100404
in reported structural units across the three meshes. The finest pair differs
by 47.0487%; the absolute peaks are small, and the spatial V/M profiles also
vary strongly. This requires investigation before an engineering convergence
tolerance can be assigned; it is not a demonstrated acceptance or failure of
the physical model. See the raw JSON, force distributions and generated review
in this directory. No release or Phase 5 acceptance is inferred.

Subsequent controlled installation solves are retained in
`installation_diagnostic.json`; see the
[experiment design and interpretation](../../../f7-installation-weight-diagnostic.md).
`installation_symmetry_budget.json` retains the extended eighteen-solve run,
including six symmetric T6/Q8 controls and separate beam/interface/body
contributions at every pile node. The shared continuum tip is unresolved.
That file is retained as historical evidence.
`installation_continuum_budget.json` records a further eighteen-solve rerun
with directly integrated soil internal/body forces and nodal reactions.
Its complete pile-node force residuals are below 2e-11 kN/m, including the
shared tip. This remains a dry installation diagnostic, not an excavation
or independent physical acceptance certificate.

`coupled-dry/` retains the subsequent actual three-mesh/full-excavation rerun
with beam, bar, continuum and interface nodal transfer plus active-weight
global force/moment checks. All nine scoped coupled budgets passed.
[Contract, analytical references and limitations](../../../f7-coupled-dry-excavation-budget.md).

`loaded_excavation_audit.json` records the subsequent three-mesh excavation
with right-side surface pressure/shear and pile-head point loads. All nine
budgets and analytical applied force/moment comparisons passed.
[Reproduction and supported load geometry](../../../f7-coupled-dry-applied-loads.md).

`partial_excavation_audit.json` retains the loaded six-stage partial-release
program at all three mesh sizes. All eighteen incremental dry elastic budgets
passed, with actual external loads and retained release forces reported separately.
[Equations, reproduction and restrictions](../../../f7-incremental-dry-excavation-budget.md).

`hydrostatic_excavation_audit.json` records the loaded saturated three-mesh
excavation after the horizontal water-table edge integration fix. All nine
full-stage hydrostatic budgets and analytical resultant references passed.
[Water terms, reaction convention and limits](../../../f7-coupled-hydrostatic-budget.md).

`partial_hydrostatic_audit.json` records the subsequent ten-stage loaded wet
excavation, drawdown and rewetting history at all three mesh sizes. All thirty
incremental budgets passed, retaining target and actual applied water loads
separately.
[Equations, reproduction and limits](../../../f7-incremental-hydrostatic-budget.md).

`seepage_excavation_audit.json` records the subsequent full-stage prescribed-
head seepage transfer audit on the loaded three-mesh pile/anchor excavation.
All nine mechanical budgets, reported boundary-flow balances and analytical
weight/load references passed. Saved nodal heads and boundary inflows are
retained separately; independent Darcy validation is not inferred.
[Interpolation rules, reproduction and scope](../../../f7-coupled-seepage-pressure.md).

`seepage_boundary_fixed_damping_failure.json` preserves the initial rejected
infiltration/atmospheric-face run. `seepage_boundary_audit.json` records the
same three-mesh case after adaptive Picard relaxation: all nine budgets and
analytical imposed-flux references passed. Active/released node data, nodal
flows and solver relaxation histories are retained.
[Iteration fix, equations and limitations](../../../f7-seepage-boundary-evidence.md).
