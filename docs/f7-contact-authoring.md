# Explicit interface-law authoring after native contact integration

## User path and compatibility fix

Open **Structural elements -> Add interface** or select an existing interface
and open **Properties**. The interface form now has an explicit law selector:

- **Goodman - elastoplastic joint** remains the default for new joints and old
  models. It edits kn, ks, cohesion, friction, dilation and tensile cutoff.
- **Unilateral normal contact - dry, frictionless** edits kn (kPa/m) and initial
  clearance (metres, opening positive). Tangential stiffness and all strength
  values are stored as zero. Open contact has no normal or shear stiffness.

Previously the form always constructed a new default `InterfaceSpec` from six
legacy fields. Opening an already imported normal-contact spec and pressing
Apply could therefore silently turn it into Goodman and discard its clearance.
The form now loads the existing law and clearance, and preserves untouched
properties. Merely opening and saving is not a law conversion. Interface names
that differ from mesh tags are also retained.

A law change is explicit through the selector. Inactive fields are disabled;
their draft text remains available when toggling back, but it is not parsed or
written to the other law. Switching to Goodman stores zero geometric clearance.
Switching to normal contact stores zero shear/strength parameters. Cancel does
not change the model. The manager list identifies the selected law.

## Validation is transactional, not automatic model repair

The same native Model validation from PR #78 rejects wet or undrained models,
axisymmetry, gravity/K0/field initial stresses, non-NR solvers and seismic loads
for this new normal law. The editor does NOT change settings, water, materials,
stages or supports to make a rejected selection fit. Errors remain in the form,
and the source model is unchanged. Normal-contact geometry is preflighted with
the actual staged adapter to reject curved or noncoincident reference faces.
That preflight does not prove global stability or convergence: users must
supply adequate real constraints for open-contact mechanisms. SRF remains
unsupported by the native solver.

Inactive Goodman interfaces tie their faces. Inactive unilateral normal contact
does not. The form states this distinction, as well as the difference between a
Goodman tensile cutoff and geometric contact opening/reclosure.

## Deliberate boundaries

This change exposes the already integrated dry, normal-only penalty law; it
introduces no new constitutive mechanics. The existing mesh/interface editor is
the selection route, not automatic CAD pile skin assignment. CAD remeshing and
result snapshots do not transfer nonlinear contact history or resume Newton
iterations. Property edits use the existing application result-invalidation
path. No frictional/hydraulic contact, GUI gap contours, gravity initialization,
arbitrary excavation validation or external software comparison is claimed.

## Tests and execution evidence

The Qt-free parser is covered in the core test matrix without importing Qt or
Shapely. Real offscreen Qt tests exercise untouched normal and Goodman specs,
explicit switching, disabled fields, invalid environments, geometry rejection,
new interface creation, cancellation, JSON persistence and actual `api.run`
after editing. The six-to-five-millimetre reversal and a closed-contact continuum
equilibrium are checked with independent scalar targets after the edit.

The standard desktop matrix includes the new tests on Windows and Linux. The
`f7-contact-authoring` workflow also runs them with mandatory Qt dependencies,
rejects skipped evidence, runs the unchanged 8-model/56-stage native benchmark,
and archives JUnit, actual dialog capture, solver JSON/log and the exact tracked
source tree (no credentials or Git metadata) for reproducibility. A green parser
or lint check is not substituted for actual GUI/native-solver execution.
