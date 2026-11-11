# F7 — Desktop inspection of stored elastic-contact equilibrium

## Route and bounded meaning

Open **Inspect results → Normal contact point results… → Complete elastic history audit…**.
The same button is available in a contact table opened from the independent Interpret
window. Click **Run complete history audit**. Opening the window does not automatically
start work; the entire initial + accepted-stage history is audited, irrespective of
the parent table's interface filter. The parent snapshot index selects the corresponding
row after completion. Selecting a row never changes the parent or Interpret stage.

The underlying PR #90 `contact_topology_equilibrium_by_stage` algorithm, numerical
tolerances, material laws and solver are unchanged. This is a presentation and export
layer, NOT a new verification of nonlinear soil or physical design capacity. Supported
scope remains dry, drained, stress-free, zero-gravity elastic plane strain with normal
contact on the original mesh; no water, frictional contact, beams/anchors, remeshing,
physical deposition into a new cavity, nonlinear restart or software certification.

## Distinct states and units

The table separates **History / transition** from **Physical only**. A passed transition
can have nonzero retained-release forces, so its physical-only status is **not balanced**.
A failed/invalid/unsupported/blocked stage has **not assessed** physical status rather
than presenting an otherwise globally balanced force sum as evidence of validity.
The initial row shows only the initial-reference check, not a fabricated measured
physical-balance pass. Missing measurements are em dashes, never zero. Duplicate
stage names and fractions remain distinct ordered snapshot indices (0 is initial).

Maximum nodal residual and global Fx/Fy residual use kN/m; global Mz residual uses
kN*m/m. The retained-force column is the maximum absolute NODAL component, not the
possibly cancelling sum of both faces. Selecting a row exposes the exact numerical
report, including component checks, physical/retained loads, reasons, topology and
blocked predecessor. Initial details also expose the original audit scope/tolerances.
Changing the original-coordinate moment origin clears stale data and disables export
until a new complete audit is run. The GUI cannot relax any tolerance.

## Thread and input lifetime

Before starting, the selected accepted result is copied on the GUI thread; the audit
then runs on a separate QThread. This extra copy costs memory and may briefly take time
for very large snapshots, but concurrent model editing cannot change the input mid-run.
The numerical routine never calls `api.run` / `StaticSolver` or writes model/results.

**Discard pending result** discards the outcome; it does NOT promise immediate
interruption of the underlying numerical reconstruction, which has no cancellation
callback. No partial report is published/exported. Close/Escape hides the dialog and
defers completion safely. Workers are application-owned and kept alive even if a
parent table is deleted. On application exit, outstanding read-only work is allowed
to finish safely rather than forcibly terminating a QThread. Failed work clears the
old report and leaves the Run button usable. A new run uses a new detached copy.

## Atomic JSON and reproducibility

**Export complete audit JSON…** exports the exact completed report shown in the window,
not a re-solve or a second audit of potentially modified source data. It includes schema
identifier `slipsurface.contact_topology_audit/1`, moment origin, snapshot names, units
and the unmodified raw audit. Failed/unsupported reports are intentionally exportable
with their reasons. Nonfinite/malformed documents fail before atomic file replacement.
An unsuccessful replacement leaves a previous destination intact.

The dedicated `f7-contact-audit-desktop` workflow requires actual unskipped Qt tests,
thread/discard/close/failure tests, source-detachment checks, successful and invalid
screenshots, strict JSON and a saved solved project. It retains the unchanged
52-model / 552-stage native benchmark. New desktop tests also run in the existing
Windows/Linux desktop matrix. Existing numerical workflows and acceptance contracts
are retained; local missing-Qt skips are not successful desktop executions.
