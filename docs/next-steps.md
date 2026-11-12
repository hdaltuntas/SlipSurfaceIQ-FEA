# Current status and remaining work

## 12 November 2026 B5 tieback prerequisite

The scalar finite grout bond-slip law is now separated from element assembly and covered
by a strict characterization gate. It uses bond shear stiffness in kN/m2 and bond
strength in kN/m, with exact elastic-perfectly-plastic return mapping, unloading and
finite-difference tangent checks. [Law and scope](b5-bond-slip-law.md).

This does not close RS2 Anchored Sheet Pile Wall B5. Next numerical work is the
solver-level embedded tieback transfer formulation: independent tendon axial motion must
couple to host-continuum displacement through the verified bond law without reverting to
the existing shared-node perfect bond. The other B5 blocker remains the authoritative
Material 1 Young's modulus and friction angle from the official starting model.


## 4 November 2026 F7 local execution

The actual pile/anchor excavation completed at h=2.5, 1.8 and 1.2 m:
all nine stages were recorded, with no solver exceptions. Bounded structural
coverage, interface force/moment integrity and gravity balance passed.
[Raw evidence and reproduction](data/f7/2026-11-04/README.md).
Next numerical work is to investigate the installation-stage pile V/M mesh
sensitivity and establish the coupled soil–pile–anchor external force budget.
The [controlled installation experiments](f7-installation-weight-diagnostic.md)
now isolate the moment to the pile self-weight response: half weight halves
the moment and zero weight removes it; prior soil equilibration changes
nothing. The bending mechanism and spatial mesh sensitivity remain open.
Follow-up symmetric T6/Q8 controls now show moment peaks below 1.2e-13,
supporting a discretization asymmetry explanation. Isolated pile-node force
budgets close below 2e-11; the shared soil tip is explicitly unresolved.
The tip's continuum internal/body contributions are now included and all
eighteen diagnostic runs close at every pile node below 2e-11 kN/m.
[Updated measured tip budget](f7-installation-weight-diagnostic.md#completed-shared-tip-continuum-budget).
Next: the coupled stage-wise excavation/anchor external-force budget.
Original demo geometry and loads are retained.
The [bounded dry full-stage coupled budget](f7-coupled-dry-excavation-budget.md)
has now passed all nine real mesh/stage cases, checking both nodal transfer
and independent active-weight force/moment resultants. It is part of the
canonical audit CLI acceptance condition. Next extensions are applied boundary
loads, partial stage release and water-force accounting; independent physical
benchmarks and mesh convergence remain open.
Straight surface pressure/shear and point loads are now included in the
coupled dry budget. The [loaded three-mesh excavation](f7-coupled-dry-applied-loads.md)
passed all nine stages and matched the analytical applied force/moment
reference in every row. Next: incremental accounting for partial stage
release, then water-force accounting. Independent validation remains open.
The [incremental dry elastic budget](f7-incremental-dry-excavation-budget.md)
now separates actual applied loads from retained excavation-release forces.
Its six-stage loaded pile/anchor program passed all eighteen mesh/stage
checks. Support activation in a partial step remains unsupported; activation
is performed in full stages. Next: water-force accounting, with independent
physical benchmarks and mesh convergence still open.
The [full-stage horizontal-head water budget](f7-coupled-hydrostatic-budget.md)
now includes saturated weight, continuum/joint/boundary water terms and the
total-reaction convention. The loaded saturated excavation passed all nine
mesh/stage cases and analytical resultant checks. A horizontal water-table
intersection error in straight-edge pressure integration was also fixed.
Next: changing-water/partial wet-stage history; seepage and independent
physical validation remain outside this delivered scope.
The [incremental horizontal-head audit](f7-incremental-hydrostatic-budget.md)
now separates target pore pressures from history-blended actual water loads
and retained release forces. A ten-stage loaded excavation/drawdown/rewetting
program passed all thirty mesh/stage checks. Next: seepage-derived pressure
evidence. Partial-stage activation, independent physical benchmarks and mesh
convergence remain open.
The [full-stage prescribed-head seepage audit](f7-coupled-seepage-pressure.md)
now verifies head-to-pressure transfer, coupled force budgets and reported
boundary-flow conservation. All nine loaded three-mesh stages passed.
Next: flux/seepage-face evidence and independent hydraulic residuals, then
partial seepage history. The older simplified dry-load/excavation audits
remain unsupported for coupled cases; no independent physical
validation or release acceptance follows from this run.
The [flux/seepage-face evidence extension](f7-seepage-boundary-evidence.md)
now integrates imposed flux and checks atmospheric nodes individually, with
persisted node IDs, nodal flux and Picard diagnostics. The actual infiltration
case exposed fixed-relaxation oscillation; adaptive relaxation and an undamped
conductivity criterion corrected it without changed physical inputs or an
increased iteration limit. All nine mesh/stage budgets now pass. The original
failed run is retained. Next: independent hydraulic residual reconstruction,
including nonlinear conductivity lag; partial seepage histories remain open.

## 2 November 2026 review follow-up

The results dock now lists every region and structural object. Select a member before
choosing its N/V/M field; the plot scales to that member, preserves real force jumps,
and separates disconnected paths. Region/interface displacement selections and element
charts use the selected stage. Tunnel placement preserves the user's schedule and adds
no automatic excavation/support stages. Manual bolt patterns now require a mouse-dragged interval on a line/lining or closed
boundary, with an exact live preview and a confirmation dialog for spacing/length/side.
There is no whole-boundary automatic GUI placement, and tunnel designer placement adds
no bolts (including legacy saved designs). Split boundary rules are retained. Invalid
corner moves are caught before any drawing/history mutation; this fixes the reported
`Tunnel_Head` self-intersection traceback. See `tests/unit/test_drag_bolts.py`. See `tests/unit/test_selected_results.py` and the
[model workflow](integrated-modeler.md#selected-element-results-and-manual-bolt-patterns).

The model/CAD workspace now has bottom stage tabs synchronized with the mesh/results
view and document viewer. **Model > Project properties** edits the number and names
of construction stages, including in unmeshed drafts. Right-clicking a region on
either canvas opens material/excavation assignment for the selected stage; applying
to following stages is optional. Region context menus now contain only **Assign materials**;
the material list includes **Excavated (void)**. Material/excavation assignment now also works without a mesh and on changed geometry.
The draft material catalogue and assignments are saved in CAD JSON, previewed by stage,
and applied after mesh generation and old-model transfer. Existing meshed edits remain
authoritative on later remeshes. See `tests/unit/test_premesh_materials.py`.
Existing softened/disturbed material definitions
can be selected. These edits clear old results and survive project save/reopen and
remeshing. Regression coverage: `tests/unit/test_stage_workspace.py` (desktop CI).
See [the workflow](integrated-modeler.md#stage-tabs-and-project-properties).

The user cancelled the theme change at this stage. Theme PRs #14 and #15 were closed
without merging; the current main-branch appearance is retained.
The user also requested source-only operation: use `python main.py` after installing
`requirements.txt`. Package-build/publish workflows and the console entry point are removed.

The result-display fixes retain node IDs through beam/bar charts and deformed N–V–M
overlays, so coincident interface faces cannot substitute one another's displacement.
The plastic contour is the fraction of yielding Gauss points (0–1), not extrapolated
state codes. Query overlays break at missing samples in excavations, inactive regions
and outside the model, both before and after deformation.

Regression coverage is in `tests/unit/test_result_display_regressions.py` and
`tests/unit/test_inspection.py`. The dedicated desktop CI job includes the new cases.
These corrections do not by themselves close Phase 5. The exact custom S4
external-validation gap remains open advanced validation, but the v1 release gate now
uses the official RS2/PLAXIS benchmark suite described in
[external-benchmark-suite.md](external-benchmark-suite.md).

## Release acceptance

The 22 October 2026 withdrawal remains the historical reason the package was returned
to 0.9.0. The identified desktop contrast/layout/workflow issues were subsequently
corrected. The current state is a **0.9.0 release candidate**: numerical and external
benchmark gates are in place, while real Windows user acceptance remains open.
This repository is the Python `slipsurface.fe2d` / **SlipSurfaceIQ-FEA** project.

## What is already delivered

- Phase 4 (W1–W3, C1–C3, undrained A/B/C), the Phase 3 fixes from PR #1, and
  Phase 5.1 were merged to `main` through PR #3: `de1f12a`.
- The admissible Mohr–Coulomb return guard, the explicit Rankine-apex option, the
  embedded-tip interface fixes, the mixed mesh, and the diagnostic records were carried
  over. The full-slip liner and Winkler sheet-pile tests on the main branch are kept as well.
- Phase 4 seepage acceptance, the Hoek–Brown flow-cone check, the MCC error type, and
  the input checks were fixed. [Review record](phase4-review.md).
- **Phase 5.1 has started and runs:** native PySide6 application, background solve,
  project/material/stage operations, the active result view, and export.
  [How to run, and scope](phase5-desktop.md).
- **Phase 5.2 CAD delivery:** native region/void/line, snap, coordinate editing,
  geometry undo/redo, limited lossless DXF, an edge fixity/pressure table, a cancellable
  T6 mesh worker, and drawing/project save. [Scope and tests](phase5-cad.md).

- **Phase 5.3 delivery:** six constitutive forms and region assignments, liner/bolt
  builders, the initial state, load/water and stage material, and stage
  add/copy/delete/reorder.
  [Use and acceptance scope](phase5-model-editors.md).

## Preserved limits

- There is **no** RS2/PLAXIS comparison for S4. This is a product boundary, not a
  deferred pass. Internal Winkler/LE tests are not external verification.
  [How it would be added](s4-external.md).
- The legacy P4 without a tension cut-off is kept as a strict xfail because of the
  local return error. A local material rejection cannot be an SRF collapse upper bound.
- Numerical non-convergence by itself is not proof of physical collapse. Explicit
  Rankine-apex flow is a different constitutive option; it is not added silently to the default.
- Phase 5 functional GUI/API acceptance passed. Package and PyPI publication status
  is kept separately in the [version record](phase5-release.md). The S4/P4 exceptions are not hidden.

## Phase 5 — waiting for user acceptance

Mechanical boundary conditions, stage displacements, the interface library, the timeline,
plastic Gauss points / principal arrows, the query line, and liner N–V–M were added. The
four-stage tunnel acceptance built from an empty GUI matched the API exactly. The portable
package and wheel/sdist build workflows were removed; use `python main.py`.
Linux/Windows CI was 10/10 and the independent Windows portable test passed. Test evidence,
publication status, and the preserved exceptions are in
[phase5-release.md](phase5-release.md).

These automated checks do not replace user acceptance. The earlier Windows screenshot
identified menu/tool contrast and panel-layout problems; those defects were corrected
and remain covered by regression tests. Remaining release work:

1. ~~Readable menu/tool/tab colours on Windows light/dark themes and display scales.~~
   Done (27 October 2026): light colour scheme fixed, Windows dark mode off,
   spin-box arrows and SNAP/GRID contrast corrected, WCAG AA contrast test.
2. ~~A clear arrangement of the geometry, material, boundary/load, stage, and result steps.~~
   Done: a numbered eight-step workflow, a ✓ for completion, and a “next step” hint.
3. ~~A balanced, adjustable layout of the model area, the stage list, and the solution log.~~
   Done: a full-width workflow row, a View menu, and a persistent layout.
4. Visual check on a real Windows display, and user usability acceptance.
   **Still open**: Linux/offscreen images do not replace acceptance. Use
   `python scripts/windows_release_acceptance.py prepare --out windows-v1-acceptance`
   to generate the checklist and internal numerical references, then record acceptance
   only after the real Windows workflow is accepted.
5. ~~Preserving material, stage, interface, and structural definitions on remesh.~~
   Done: [detail](integrated-modeler.md#save-undo-and-remeshing).

Phase 5 will not be closed, and no new release will be published, until this acceptance is obtained.

Earlier Phase 3 measurements are kept as historical evidence under `phase3-status.md`,
`s4-comparison.md`, and `docs/data/s4/`; the test result of the new integrated branch
is reported separately in the review record.
