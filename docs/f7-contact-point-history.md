# F7 — Stored contact point history

## User route

Open **Inspect results → Normal contact point results…** from the main results
window or the independent Interpret window. Select one row (interface, element,
integration point) and press **Selected point history…**. The new read-only
window shows that exact point in the initial snapshot and every stored stage.
Selecting a history row highlights the same stage in both plots. It does not
change the parent window's stage. The point selection survives a stage change
in the point table. An already opened history window retains its own identity.

The left plot displays signed gap in **mm**; the right displays normal contact
pressure in **kPa, compression positive**. Positive gap means separation; negative
gap is penalty penetration, not a sign error. Values come from the accepted
`contact_gap`, `contact_status`, `interfaces` and activity maps through the same
strict reader introduced for contact results. No gap is reconstructed from
reported displacement, so display-datum resets cannot alter this measurement.

## Interpretation boundary

The horizontal axis is the **stored stage index**: 0 is the initial snapshot,
then 1..N in result order. It is not time, accumulated loading or solver iteration.
Accepted load factor lambda is shown in the table only, is not cumulative and
is not a safety factor. Repeated stage names and equal load factors do not merge
or reorder samples. Lines connecting adjacent stored samples are visual guides,
not solved intermediate states, constitutive paths or interpolated gap closure.

Inactive and unavailable snapshots remain table rows with blank measurements.
They break the numerical plot lines instead of becoming zeros; singleton
segments remain visible as points. OPEN, TOUCHING, COMPRESSED, INACTIVE and
UNAVAILABLE are categorical table entries, not values interpolated on a graph.
No histories are averaged by coincident coordinates. Interface tag, element,
point and both face-node IDs remain distinct, including the IFACE6
endpoint/endpoint/midpoint ordering. This feature uses one SolveResult mesh and
does not implement matching across independently remeshed results.

## Export and failure behavior

**Point history CSV…** exports all snapshots for the selected identity. CSV uses
`gap_m` in metres, both `normal_traction_kPa` (tension positive) and
`pressure_kPa` (compression positive), explicit `stage_index`, stage name,
accepted load factor, availability/activity/state and the undeformed point/node
identity. Missing or inactive measurements are empty cells, never synthetic zero.
The original per-stage and all-point CSV exports are unchanged.

All history stages are validated before the exporter atomically replaces a
file. Malformed late-stage data, invalid identity, nonfinite display conversion,
invalid accepted load factor or a Goodman selection cannot overwrite an existing
export with a partial history. Cancelling the file dialog leaves the file alone.
Rejected GUI histories clear the previous samples and disable history export.

## Verification and scope

Tests use native `api.run` Q4/IFACE4 and Q8/IFACE6 solutions, covering the 6 mm →
5 mm open reversal (zero pressure), closure, reopening, reset reporting datum,
exact point identities, missing/inactive stages, repeated names, partial factors,
invalid late data and project/CSV round trips. Qt tests exercise actual buttons,
plots, selected rows, rejection and export cancellation. The dedicated contact
results workflow requires unskipped Qt execution, captures the real history
window and a missing-stage example, and retains CSV, solved project, JUnit and
the tracked source tree. The native 8-model / 56-stage benchmark remains intact.

This is stored-snapshot presentation, not a new physical contact model, fatigue
analysis, time-domain simulation, within-stage nonlinear restart, continuous
field recovery or independent RS2/PLAXIS validation. No solver, material law,
physical residual, tangent, model compatibility default or acceptance gate is
changed by this feature.
