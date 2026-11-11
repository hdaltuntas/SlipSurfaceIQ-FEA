# F7 — Reusable elastic contact topology-history audit

## New capability and unchanged boundaries

`contact_topology_equilibrium_by_stage(result)` audits a saved native `SolveResult`
without solving it again or requiring a fixture's layer dimensions, region names,
loading sequence or scalar reference. It permits continuum removal/rebirth, automatic
contact deactivation, contact switching and temporary displacement restraints on the
original mesh. All earlier public full/partial/activation/support audits keep their
previous rejection of changing continuum topology. No production solver, material
law, GUI, solver tolerance or old verification gate is changed.

This first general-topology contract is **elastic**, dry, drained, plane strain,
stress-free and zero gravity, with full Newton and constant material assignments.
Supported elements are T3/T6/Q4/Q8 and straight, conforming IFACE4/IFACE6 normal contact.
Contact faces may have a unique continuum owner or be an unattached rigid/support
face. Multiple potential owners or mismatching midside nodes are rejected rather
than guessing. At least one continuum element must survive each stage.

This is numerical snapshot consistency, not general nonlinear-soil validation,
physical deposition into a deformed cavity, remeshing, design capacity, hydraulic or
frictional contact, beams/anchors, restart, experimental calibration or independent
software certification. Continuum shape functions and quadrature are shared with the
library: this is **not a second independent finite-element solver**. Custom external
tractions not persisted in the Model cannot be reconstructed.

## Independent reconstruction

For each stage, derive continuum activity from declared regions and interface activity
from requested tags and topological face ownership. Do not accept stored masks as the
source of truth. Rebuild connected continuum components from surviving elements; never
join opposite faces merely because their coordinates coincide.

Let U be original-reference total nodal displacement, D the reporting datum, P the
current used-node projection, and alpha the accepted fraction. On node rebirth set
D_new=U_previous for newly used nodes. An explicit display reset sets D=U_previous
for all nodes. Recover U on used nodes from `snapshot.u + D`; preserve last-known U
on unused nodes. Their stored displacements MUST be NaN, not invented zeros.

Start stress S0 equals the preceding stress for surviving continuum elements and
zero for newly activated or inactive elements. Integrate S0 through the shared shape
function derivatives to form soil internal force; integrate normal traction
`kn*min(g0+n·(U_face2-U_face1),0)` on current-active contacts using independently
calculated original-coordinate endpoint/Simpson weights. This gives I0 without reading
StaticSolver's state, residual, reactions or private applied-force buffer.

The nodal load histories are:

```
F_previous_projected = P * F_previous
F = (1-alpha)*F_previous_projected + alpha*F_target
H = (1-alpha)*P_free_current*(I0 - F_previous_projected)
```

F contains **physical declared loads** only. H is a numerical retained-release term,
not a current support reaction or a physical extra load. Deleted-node load history is
dropped permanently, not restored when the node reappears. Applied-load resultants
also use independent analytical edge/point first moments, with the dropped previous
resultant removed before interpolation.

Check every nodal equilibrium equation `I_current - F - H - R = 0`, external force
and moment, and each current continuum component's loads, reactions and contact
actions. Independently repeat the balances using only F and R: this separate
`physical_equilibrium` can fail during a valid partial-release transition. All full
stages must satisfy physical-only balance. Opposite contact contributions are not
counted again as global external loads.

## Stress-free birth and contact reference checks

At each active Gauss point, independently form the isotropic plane-strain elasticity
matrix from E and nu and compare `S0 + C * B * (U_current-U_previous)` with stored
stress. Lambda=E*nu/((1+nu)*(1-2nu)); mu=E/(2*(1+nu)); the engineering-shear diagonal
is mu. No native constitutive update routine generates this target. B and quadrature
are explicitly shared. This catches, for example, corrupted out-of-plane stress that
ordinary two-dimensional nodal force balance alone cannot see.

Also compare saved gaps and normal tractions against original-reference U, and check
prescribed displacement interpolation from previous ACTUAL position. Free or inactive
DOFs cannot carry reactions. Inactive contact measurements must remain NaN/status 255;
its gap/law check is `not_applicable`, not a measured pass. Inactive continuum stress
must be exactly zero. Missing maps, wrong fractions/identities, invalid initial data,
nonfinite numbers and contradictory activity fail visibly. A bad predecessor blocks
all later claims. Audit operations do not mutate model or result arrays.

## Use an already-solved project

```python
from slipsurface.fe2d import api
from slipsurface.fe2d.post.contact_topology_equilibrium import (
    contact_topology_equilibrium_by_stage,
)

saved = api.load_project("model.ssproj")
report = contact_topology_equilibrium_by_stage(saved.results, origin=(0.0, 0.0))
```

From a source checkout (`PYTHONPATH=src`, or the package installed):

```
python scripts/f7_contact_topology_benchmark.py --project model.ssproj --output audit.json
```

`.h5` accepted-result snapshots are also supported. The command returns nonzero for
failed/unsupported evidence; an unsolved project is rejected. No Newton restart is
performed. Without `--project`, the command runs the native benchmark matrix; add
`--example example.ssproj` to retain the six-stage asymmetric-notch model.

## Verification scope

The new benchmark runs 52 native models / 552 stages: 24 retained reactivation cases,
24 retained monotone excavation cases, and four asymmetric partial-notch cases with
two material stiffnesses, nonuniform loading and only part of a contact remaining
active. For the 48 layered models, the old independent scalar/boundary-integral
references are evaluated separately on the SAME native result and classifications
must agree. The asymmetric cases assert equilibrium and elastic increment consistency,
not an exact displacement or contact patch. 328 stages satisfy physical-only balance;
224 carry retained release and are not labeled physical-only passes.

Regressions cover triangular and quadrilateral uniform layers, support switching,
corruptions that cancel globally, disappeared/reborn nodes, pore/stress/activity maps,
initial records, pressure/gap, moments, tolerance validation, persistence, CLI operation
without a solver call, and preservation of old audit boundaries. The dedicated workflow
requires unskipped JUnit, complete strict-JSON evidence, saved project and tracked source.
The standard desktop/core CI remains a separate requirement before merging.
