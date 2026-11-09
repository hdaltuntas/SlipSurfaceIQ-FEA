# F7 — Stored normal-contact interface force and moment resultants

## Desktop route

From **Inspect results → Normal contact point results…**, choose
**Interface force / moment…**. The separate window inherits the parent stage and
interface selection without changing it. Select one interface or keep all tags as
separate rows. Enter a global moment origin in metres and press **Apply moment origin**.
Editing the origin immediately clears old totals and disables export until recalculated.
Selected-stage or all-stage CSV uses explicit snapshot indices (0 = initial); repeated
stage names and identical load factors remain distinguishable.

## Sign, geometry and units

This is post-processing of stored accepted normal-contact pressures. It does not
change the material law, solver or any acceptance condition. It uses the original
small-displacement fixed frame, NOT displayed/renormalized displacements. Only
plane-strain, straight, coincident-reference IFACE4/IFACE6 normal-contact blocks are
supported. Goodman results do not acquire geometric contact summaries.

For the first face's directed tangent `(tx, ty)`, the normal is `n=(-ty,tx)`.
Stored normal traction `sigma_n` is tension-positive and nonpositive for this law;
compression-positive pressure is `p=-sigma_n`. For each integration point:

- Contact action **on the body at face 2**: `f2 = w*p*n`.
- Contact action **on the body at face 1**: `f1 = -w*p*n`.
- The native assembled **internal force contributions** are `-f1` and `-f2`.
- About the chosen origin `(ox,oy)`, `Mz=(x-ox)*Fy-(y-oy)*Fx` (counter-clockwise positive).

The UI reports actions. CSV explicitly includes both action and internal-contribution
columns; neither is labelled as a support reaction. Forces are kN/m out of plane,
moments kN*m/m, original coordinates/metre lengths are m. Opposite face totals are
kept separate, not cancelled to a misleading zero. Separate tags remain separate,
even when their nodes or original coordinates coincide.

The scalar `pressure_integral = sum(w*p)` is nonnegative; it is **not** the magnitude
of the net force when element normals differ. Moment origin translation obeys
`M(new)=M(old)-dx*Fy+dy*Fx` for either face's unchanged resultant force.

## Discrete quadrature, not a recovered continuous contact field

Each straight IFACE4 uses endpoint weights `L/2,L/2`. Each straight IFACE6 uses
endpoint/endpoint/midpoint weights `L/6,L/6,2L/3`, exactly in stored point order.
Weights/normals are calculated from geometry in the postprocessor, without calling
the constitutive group or deriving an expected answer from its returned forces.
This reproduces the native discrete nodal-force assembly, not an exact integration
of an unknown continuous contact patch. In particular, a linearly varying pressure
has an exact quadratic moment integral with IFACE6, whereas IFACE4 retains its
endpoint quadrature moment. No interpolation across open/closed transitions or
geometric 'compressed contact length' is invented.

## Coverage and export safety

The stored boolean element activity mask is authoritative. `active_subset` means
only active elements contributed; total/active element counts and lengths are both
exported. Active length includes open and touching elements: it is not compressed
contact length. If any active measurement is unavailable, the whole interface total
is unavailable and force/moment cells are blank. Wholly inactive totals are also
blank, not a measured zero. An available open interface legitimately reports zero.
Malformed data, nonfinite/overflowed arithmetic, unsupported geometry and invalid
origins are rejected. Every requested snapshot is validated before atomically
replacing a CSV; a malformed late stage cannot destroy an earlier export.

## Verification and limits

Tests cover uniform pressure at different orientations, the hand-derived IFACE6
linear-pressure integral, IFACE4's discrete moment, direct comparison to the negative
native nodal internal forces, shifted origins, mixed active/inactive elements,
separate co-located tags, stored snapshot roundtrips and invalid/overflowed evidence.
The existing native continuum-contact benchmark supplies independently balanced
boundary reactions for comparison, without modifying the benchmark or its gates.
Actual Qt tests exercise parent/child stage independence, origin changes, blank
missing data, export/cancel/failure and restored-project screenshots.

This is NOT a complete external force/moment budget, design/capacity check, contact
patch reconstruction, hydraulic/frictional contact extension, remesh transfer,
nonlinear restart or RS2/PLAXIS validation. Action/reaction cancellation alone does
not validate the entire soil–pile–anchor system.
