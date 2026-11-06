# F7 — Execute the real three-mesh pile/anchor excavation

## Local execution evidence (4 November 2026)

The full three-mesh problem completed locally: nine stage rows, no solver
exceptions, and passing bounded structural/interface integrity checks.
[Environment, reproduction, measured limitations and raw artifacts](data/f7/2026-11-04/README.md).
The coupled force budgets remain unsupported; independent validation is open.
The evidence review now includes structural coverage, interface moments and
the interface-transfer ledger, explicitly marking absent evidence as missing.

## Workflow background

The audit now also requires the bounded
[coupled dry full-stage force/moment budget](f7-coupled-dry-excavation-budget.md)
to pass for every row. The subsequent local rerun passed all nine cases;
water, applied loads and partial stages remain outside this new contract.

The optional supported-excavation script has accumulated strict data
integrity and assembly checks (PRs #54–#58), but green unit tests do
**not** mean that the complete staged FEM problem was actually solved
at three resolutions.

This change adds a separate GitHub Actions workflow,
`.github/workflows/f7-supported-excavation.yml`, to run the **real**
native excavation model with the existing independent mesh builds at
`h = 2.5, 1.8, 1.2 m`. The actual model has a pile, skin interfaces,
an anchor and two excavation lifts; no synthetic force rows are
substituted for the solver output.

## Evidence retained

On completion or failure, the job uploads the audit's actual JSON and
CSV artifacts and `f7_audit/solver.log` (captured standard output and errors),
together with a GitHub job-summary containing the
completed stage count, mesh/stage coverage, structural-output coverage,
interface-moment acceptance and mesh/solver failure count.

Run from GitHub Actions under **f7-supported-excavation** (manual
`workflow_dispatch`), or inspect the pull-request-triggered run.
The job fails if the existing script exits nonzero: missing mesh/stage
rows, solver errors, structural coverage failures and active interface
moment failures are not silently accepted.

This is intentionally a **separate, potentially expensive workflow**
rather than an additional task in the fast Python 3.10–3.13 CI matrix.
Its job timeout is 45 minutes; actual runtime and convergence cannot
be assumed before a completed run has been inspected.

## Interpretation

A green run would demonstrate that all requested stages completed
on three generated meshes and passed the implemented bounded checks.
It would **not** by itself certify physical N/V/M, groundwater seepage,
anchor design or independent RS2/Plaxis agreement.

The resulting artifacts must be examined for support-profile changes,
global reactions, plasticity, interface force/moment transfer and
numerical convergence. Unsupported reference cases remain
unsupported and are not replaced by fabricated passing metrics.

## F7 mesh sensitivity diagnostics

The audit JSON now contains `mesh_sensitivity_diagnostics`, including
coarse-to-medium and medium-to-fine relative changes for each stage's peak
displacement, tagged beam moments, and tagged bar axial forces. Missing,
duplicated or nonfinite data are explicitly classified as incomplete.
The `diagnostic_only` status is **not** a passed convergence threshold:
spatial peak locations may differ between meshes. These descriptors do not
change the pre-existing execution integrity gate or imply external validation.
No acceptance tolerance is imposed until a justified benchmark is available.

## Engineering evidence review after execution

The workflow now runs `scripts/f7_evidence_review.py` against the *actual*
`f7_audit/excavation_mesh_audit.json`. It preserves
`f7_audit/f7_evidence_review.json` and `f7_audit/f7_evidence_review.md`
in the uploaded artifact and appends the Markdown review to the Actions
job summary. The review distinguishes gravity-balance passes from
unsupported dry-load and coupled excavation-force budgets, groups the
unsupported reasons, and lists measured structural profile differences.

A finest-pair beam-peak relative difference of at least 25% is highlighted
as an **investigation priority only**, not an acceptance or rejection
criterion. The magnitude of the corresponding peak is retained to avoid
misinterpreting a large ratio between small forces/moments. The review
never reports independent physical validation as achieved, and it does
not change the pre-existing solver acceptance exit status. Future work
must establish a complete coupled force budget and an independent
reference before defining engineering tolerances.

## Global interface-transfer ledger

The actual excavation JSON now also includes `interface_transfer_ledger`:
per mesh and stage, this combines nodal interface force residuals with
paired-face resultants and their integration reference errors. Missing
interface tags, nonfinite values, duplicate stages, and noncancelling
forces are explicitly failed. No active interfaces is *not applicable*,
not a pass.

Each interface also has its own residual check, normalized by its own
face-force scale (with a unit floor). Opposing errors on different interfaces
cannot cancel into a passing total, and a large neighboring interface cannot
hide a smaller interface's reference error. Per-interface statuses and ratios
are retained under each stage's `interfaces` entry in the ledger.

These are **internal interface action–reaction consistency checks**.
Their completion cannot replace a full continuum–pile–anchor external
force equilibrium budget or an independent physical benchmark. The
existing F7 FEM execution integrity gate is unchanged.

## Stage-aware interface transfer acceptance

The three-mesh F7 audit now reports `interface_transfer_acceptance`, checked
against the stage definitions and the aggregate interface-transfer ledger.
An expected-active interface stage must report positive active-element count
and a finite residual within the stated tolerance. Stages with no expected
active interfaces must be marked `not_applicable`, not falsely passed.
Missing, duplicate, inconsistent or nonfinite records fail the bounded
interface-transfer acceptance gate.

This adds an **internal interface assembly/integrity requirement** to the
existing F7 execution gate. It does not replace the newer coupled dry, wet,
or seepage budgets and does not establish independent physical validation.

## CAD-aligned N/V/M profile integrity

The actual three-mesh audit additionally emits `support_profile_integrity`.
It checks each declared pile/anchor support against the independently defined
stage activation schedule. Active supports must have finite sampled profiles
at monotonically increasing common CAD-length stations (beam N, V, M;
bar axial force). Inactive supports must not carry sampled profiles.
Missing/duplicate mesh-stage records, unknown support tags, nonfinite force
components and mismatched station grids are reported as incomplete.

This is a **descriptive data-integrity check** and does not alter the
existing solver/force-balance acceptance gates. In particular, sampled local
N/V/M agreement is neither a physical design check nor independent
RS2/PLAXIS validation.

## Full-field N/V/M sensitivity at common CAD stations

The real F7 audit now includes `support_field_sensitivity`: for each
stage-active beam and bar, each successive coarse-to-fine mesh pair is
compared at the same normalized CAD-length stations. It records absolute
and normalized RMS differences, maximum absolute stationwise deviation,
the location of that deviation, and the maximum absolute force or moment
in each mesh. Beam N/V/M and bar axial profiles are assessed separately;
signed-local and magnitude profiles are never mixed.

Missing, duplicated, nonfinite and incompatible profile data are
reported as incomplete. An orientation problem blocking signed-local
sampling remains explicit in `signed_profile_errors`, rather than being
silently replaced by magnitude comparisons. This is descriptive mesh
sensitivity, not an engineering convergence threshold or an independent
RS2/PLAXIS benchmark. The current bounded solver acceptance gate is unchanged.

## Interpreting large N/V/M percentage changes at low force levels

The three-mesh JSON additionally includes `structural_field_review`.
For each beam N/V/M or anchor axial component and local-sign mode, it
retains the normalized RMS difference, RMS force/moment difference,
maximum stationwise difference, and pair maximum magnitude. It reports
the pair peak as a fraction of the largest observed peak for that same
support, component and mode across all sampled stages. This prevents
mistaking a large relative difference between small first-stage moments
for a proven physical instability. The review ranks components by
relative RMS and prints the top entries in the Actions evidence review.

The cross-stage observed peak is **not** a material capacity, reference
solution or engineering tolerance. Signed and magnitude fields use
separate scales. No numerical/physical acceptance criterion is added,
and independent reference validation remains necessary.
