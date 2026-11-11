# F7 — Desktop inspection of stored elastic-contact equilibrium

## Route and bounded meaning

Open **Inspect results → Normal contact point results… → Complete elastic history audit…**.
The same button is available in a contact table opened from the independent Interpret
window. Click **Run complete history audit**. Opening the window does not automatically
start work; the entire initial + accepted-stage history is audited, irrespective of
the parent table's interface filter. The parent snapshot index selects the corresponding
row after completion. Selecting a row never changes the parent or Interpret stage.

The underlying `contact_topology_equilibrium_by_stage` numerical equations,
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
then runs on a separate QThread. The completed copy isolates subsequent GUI model edits.
The copy is synchronous and can pause the GUI for large inputs. It is not protected
against arbitrary concurrent writers outside the application’s normal GUI ownership.
The numerical routine never calls `api.run` / `StaticSolver` or writes model/results.

**Cancel audit** now requests cooperative cancellation of the read-only audit,
not just suppression of its result. Checkpoints run before/after audit phases,
between snapshots, within block/ownership/component loops, and while collecting
contact points. An individual NumPy operation, model validation, input deepcopy,
load reconstruction or JSON serialization is not forcibly interrupted. There is
no promise of immediate cancellation or a fixed response time. The input copy
still occurs before the worker starts and costs memory.

While work runs, the progress bar shows **processed snapshots / total snapshots**
(including the initial snapshot), the current snapshot index/name, and its phase.
Blocked records count as processed, not as evaluated or passing checks. Repeated
stage names remain distinguished by index. This is neither elapsed-time prediction
nor FEM solver progress. The GUI reserves 100% until the complete document has
passed presentation validation; it never equates 100% with equilibrium success.

Cancellation raises `ContactAuditCancelled`, outside the numerical invalid-data
exception family. No partial report/status envelope is returned, displayed, saved
or exported. Failed or unsupported *completed* audits remain valid exportable
reports; cancellation does not silently become one of these verdicts. Callback
exceptions raise `ContactAuditCallbackError` instead of contaminating FEM results.
No execution events or callback settings enter the exported document schema.

Close/Escape hides the dialog and requests cancellation. Direct dialog/parent
destruction also sets the worker's thread-safe cancellation event; application-owned
threads remain alive until they finish. Application exit requests cancellation for
ALL pending workers before waiting for safe completion. It never calls `terminate`.
Late progress cannot replace a cancelled status or a subsequent run. Run is enabled
again after completion, and a fresh run uses a fresh detached input and cancel flag.

### Input-copy resource limit and cache elision

**Input array copy limit** defaults to **512 MiB per audit**, adjustable explicitly
before starting (1–65536 MiB). A Qt-free preflight walks native data containers and
array metadata WITHOUT scanning array values or allocating copied arrays. It counts
each ndarray object once; repeated references are preserved by deepcopy, while distinct
views are counted separately because each is copied. Non-contiguous arrays count their
logical `nbytes`, not the size of a potentially much larger backing allocation.

The detached audit input omits ONLY the top-level `SolveResult.geom` cache: the numerical
audit already rebuilds geometry from `model.mesh`. Model data, authoring metadata,
accepted fields, activity and all unsupported/invalid evidence remain present.
This is not a reduced-physics report or a relaxation of any numerical check. Existing
invalid/unsupported histories still produce the same verdicts. Unknown custom objects,
ndarray subclasses and object-dtype arrays are refused by the resource estimator rather
than assigned a misleading byte count; this is an input-preparation error, not a FEM
verdict or an exportable audit.

The limit is **copied NumPy array payload**, NOT total process RAM. Python objects,
allocator overhead, JSON, the source itself, other simultaneous jobs, and reconstructed
audit matrices require ADDITIONAL memory. No available-RAM or out-of-memory guarantee
is made. Above the selected limit, no deepcopy or worker run starts; the old report is
cleared and export stays disabled. An explicit higher limit can be selected after
checking available resources. A MemoryError during allocation is also an execution
failure, never a numerical failure/pass.

Successful, cancelled, pre-cancelled and failed workers drop their detached input on
exit, even when a client still retains the worker wrapper. The compact completed report
and payload count remain accessible. A worker must not be restarted directly after
completion; the dialog always creates a fresh worker, as before.

**This does not make input preparation asynchronous or cancellable.** Preflight and
copying still run on the GUI thread without pumping its event loop. Cache elision
reduces unnecessary array copies; it does not promise a fixed preparation time or
remove pauses for very large retained histories. Numerical cancellation starts after
the detached input is prepared. Resource settings never enter the JSON report or
change audit tolerances.

### Optional Qt-free API hooks

`contact_topology_equilibrium_by_stage(result, progress=callback, cancelled=predicate)`
and `prepare_contact_audit` accept optional keyword-only execution hooks. The
predicate returns an actual `bool`; the progress callback receives a frozen
`ContactAuditProgress(completed_snapshots, total_snapshots, snapshot_index,
stage_name, phase)` value synchronously on the calling thread. GUI clients must
marshal callbacks to their GUI thread. Callbacks must not mutate their input
result or launch another solver. Omitting the hooks preserves the previous report,
tolerances and audit/rejection semantics. Completed observed and unobserved reports
are compared for equality in regression tests.

## Atomic JSON and reproducibility

**Export complete audit JSON…** exports the exact completed report shown in the window,
not a re-solve or a second audit of potentially modified source data. It includes schema
identifier `slipsurface.contact_topology_audit/1`, moment origin, snapshot names, units
and the unmodified raw audit. Failed/unsupported reports are intentionally exportable
with their reasons. Nonfinite/malformed documents fail before atomic file replacement.
An unsuccessful replacement leaves a previous destination intact.

The dedicated `f7-contact-audit-desktop` workflow requires actual unskipped Qt tests,
thread/cancel/close/destruction/shutdown tests, source-detachment checks, successful,
invalid, running and cancelled screenshots, strict JSON and a saved solved project.
A real reconstruction paused in its third stage is cancelled at its next actual
checkpoint: only two stage reconstructions may complete and no later stage runs.
The evidence file records this separately from suppression of a late result. It retains the unchanged
52-model / 552-stage native benchmark. New desktop tests also run in the existing
Windows/Linux desktop matrix. Existing numerical workflows and acceptance contracts
are retained; local missing-Qt skips are not successful desktop executions.
