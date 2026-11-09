# F7 — Stored normal-contact results in the desktop

## User workflow

After solving a model that **explicitly** uses `law="unilateral_normal"`:

1. In Interpret / result display options, select the whole model or a particular
   normal-contact interface. Choose `contact_gap`, `contact_pressure` or
   `contact_status`. The native mesh canvas draws individual integration-point
   markers without interpolating or averaging neighboring elements/interfaces.
2. Choose **Inspect results → Normal contact point results…**, or click the
   normal-contact interface / use **Open element charts…**. The read-only table
   selects a saved stage and an individual interface or all normal contacts.
3. Export **Selected stage CSV** or **All stages CSV** from that table. The main
   **Export results → Contact point CSV** uses the selected stage and normal-contact
   object, or all normal contacts when no compatible object is selected.

The modeler still requires the original contact-law prerequisites. This change
adds no new contact law, stiffness, solver acceptance or supported loading mode.
Goodman interfaces do not acquire geometric-gap results by being selected.

## Values, signs and identity

- The table/canvas gap is **mm**; the CSV preserves **metres**, with 17 significant
  digits. Gap > 0 is opening; gap < 0 is penalty penetration. Negative gap is not
  clipped to zero. Penalty contact is not exact nonpenetration.
- Display pressure is **compression-positive kPa**, the negative of the stored
  normal traction. The CSV includes both sign conventions with explicit headings.
- Status is categorical: OPEN=0, TOUCHING=1, COMPRESSED=2, INACTIVE=255.
  It is separate from plasticity flags. Status has a discrete legend, no scalar
  colorbar. Missing optional snapshot maps yield UNAVAILABLE, not TOUCHING or zero.
- One row/marker retains interface tag, local element ID, local point ID and both
  face-node IDs. IFACE6 point order remains endpoint/endpoint/midpoint; no sorting
  creates a fictitious path through disconnected blocks or coincident interfaces.
- Table/CSV coordinates are original undeformed face-1 points. Canvas positions
  are displayed pair midpoints (including the chosen display deformation). Marker
  position never changes stored gap or pressure. Display-datum resets do not
  redefine contact gap; displacement is **not** used to reconstruct a gap.

Inactive rows keep their identity and status but have blank measurements in CSV
and an em dash in the table. Inactive or unavailable markers are hollow. Malformed
shapes, invalid flags, nonfinite active data, stale inactive fields, nonzero shear,
positive normal traction or a status contradicting gap are rejected explicitly.
Exports validate all requested stages before atomic destination replacement.

## Verification and limits

`test_contact_results.py` reads actual IFACE4/IFACE6 `api.run` snapshots, checks
6 mm → 5 mm opening reversal, negative penetration, reporting-datum independence,
point identity, optional-field absence, malformed/corrupted data, HDF5/.ssproj
roundtrips and atomic CSV. The separate Qt tests exercise the real MainWindow,
MeshCanvas, table, selection controls, stage switching, export and captured images.
They run in the existing Windows/Linux desktop matrix and in the dedicated
`f7-contact-results` job. That job rejects skipped Qt tests, archives screenshots,
a solved `.ssproj`, CSV, JUnit, the tracked source tree and the unchanged native
8-model / 56-stage benchmark. Source snapshots contain no Git metadata/credentials.

This is result presentation and export for stored accepted snapshots, not new
mechanical verification, engineering capacity acceptance, continuum contour
recovery, nonlinear restart capability or RS2/PLAXIS comparison. No contacts are
silently selected, enabled or converted by reading their results.
