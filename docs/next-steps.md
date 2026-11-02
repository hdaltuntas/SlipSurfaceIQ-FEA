# Current status and remaining work

## 2 November 2026 review follow-up

The model/CAD workspace now has bottom stage tabs synchronized with the mesh/results
view and document viewer. **Model > Project properties** edits the number and names
of construction stages, including in unmeshed drafts. Right-clicking a region on
either canvas opens material/excavation assignment for the selected stage; applying
to following stages is optional. Existing softened/disturbed material definitions
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
These corrections do not close Phase 5 or the S4 external-validation gap.

## Release acceptance

Release instruction (22 October 2026): **The interface is not usable; the release
is not ready, withdraw the publication.** Phase 5 is open again; a new release and the
PyPI publication were stopped.
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

These automated checks do not replace user acceptance. The user’s Windows screenshot
shows menu/tool text that disappears on a light background, weak control contrast, and
a panel layout that squeezes the model area. Remaining work:

1. ~~Readable menu/tool/tab colours on Windows light/dark themes and display scales.~~
   Done (27 October 2026): light colour scheme fixed, Windows dark mode off,
   spin-box arrows and SNAP/GRID contrast corrected, WCAG AA contrast test.
2. ~~A clear arrangement of the geometry, material, boundary/load, stage, and result steps.~~
   Done: a numbered eight-step workflow, a ✓ for completion, and a “next step” hint.
3. ~~A balanced, adjustable layout of the model area, the stage list, and the solution log.~~
   Done: a full-width workflow row, a View menu, and a persistent layout.
4. Visual check on a real Windows display, and user usability acceptance.
   **Still open**: Linux offscreen images do not replace acceptance. To produce numbers,
   `scripts/phase5_cases.py` (the four-stage tunnel and, with `--sheet-pile`, the S4 wall)
   writes the log and N–V–M; this script does not close Phase 5.
5. ~~Preserving material, stage, interface, and structural definitions on remesh.~~
   Done: [detail](integrated-modeler.md#save-undo-and-remeshing).

Phase 5 will not be closed, and no new release will be published, until this acceptance is obtained.

Earlier Phase 3 measurements are kept as historical evidence under `phase3-status.md`,
`s4-comparison.md`, and `docs/data/s4/`; the test result of the new integrated branch
is reported separately in the review record.
