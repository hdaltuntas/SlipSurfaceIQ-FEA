# F7 installation-stage moment sensitivity: controlled load experiments

The 4 November local three-mesh audit flagged a 47.05% change in the
installation-stage pile peak moment between the medium and fine meshes.
The following controlled runs isolate the load responsible, without changing
the canonical excavation demo or assigning a convergence tolerance.

For each regenerated mesh, solve only the installation stage, then repeat with
zero pile unit weight, half pile unit weight, and a soil-only equilibrium stage
inserted before installation. Materials, geometry, fixities and interfaces
otherwise retain their original definitions. These are elastic demo materials.

| h (m) | Baseline signed peak M | Peak y (m) | Half-weight signed peak M | Weightless maximum abs M | Pre-equilibrated signed peak M |
|---:|---:|---:|---:|---:|---:|
| 2.5 | 0.0859951 | -8.5 | 0.0429976 | 0 | 0.0859951 |
| 1.8 | -0.0531650 | -0.75 | -0.0265825 | 0 | -0.0531650 |
| 1.2 | 0.100404 | -8.0 | 0.0502018 | 2.54e-14 | 0.100404 |

Moments retain the solver's local sign and structural-result units. The
reported coordinate is an actual beam element end, not an interpolated chart
maximum. Signed distributions on the same 51 CAD stations are retained in
the [raw experiment output](data/f7/2026-11-04/installation_diagnostic.json).

The peak halves when the pile weight halves, vanishes to roundoff with zero
weight, and is unchanged by prior soil equilibration. This identifies the
pile self-weight response as the source of this installation-stage moment in
these runs. The loaded baseline equilibrium residuals are approximately
1e-12; the observed moment is not explained by a loose iterative stop.

The weight-only experiment does **not** identify the complete mechanism producing lateral
bending under vertical self-weight. Mesh asymmetry, soil/support coupling and
interface traction recovery still need controlled comparisons. In particular,
the maximum changes position and sign across meshes; the 47% ratio compares
different local extrema and cannot establish convergence at one fixed point.
Removing a real load from the demo would hide the sensitivity, so its unit
weight and canonical construction schedule are retained.

Reproduce in the environment recorded with the original audit:

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_installation_diagnostic.py \
  --output /tmp/f7-installation-diagnostic.json
```

All twelve weight-control solves completed. Neither this experiment
nor the existing internal action/reaction ledger establishes independent
physical validation or the coupled excavation external-force budget.

## Follow-up: symmetric meshes and the nodal pile budget

The diagnostic script now also builds six symmetry controls on the same
30 by 14 m rectangle with the same 9 m central pile, materials, self-weight,
K0 field and skin interfaces. These controls omit the excavation partitions
and anchor geometry. T6 alternating triangles and Q8 quadrilaterals use
(nx, ny) = (12, 14), (20, 28), (30, 42). They are controlled geometries,
not replacements for the original three meshes or a convergence sequence
with identical mesh sizes. A test checks reflected element connectivity,
in addition to checking the resulting bending response.

| nx, ny | T6 max abs M | Q8 max abs M |
|---|---:|---:|
| 12, 14 | 4.97e-14 | 6.66e-14 |
| 20, 28 | 5.54e-14 | 8.15e-14 |
| 30, 42 | 5.73e-14 | 1.15e-13 |

The follow-up executed eighteen solves in total (twelve original variants
and six symmetry controls). The complete data, signed profiles and actual-node
force contributions are in
[installation_symmetry_budget.json](data/f7/2026-11-04/installation_symmetry_budget.json).
The command above reproduces this extended report with the current script.

The new `pile_installation_budget` reconstructs global beam nodal internal
forces from signed local N/V/M, scatters effective interface forces by actual
node ID, and subtracts the pile's lumped body forces. Force and moment
residuals are kept separately. At nodes isolated from the continuum, the
largest force residual is 7.57e-12 in the original baseline meshes and
1.97e-11 across the symmetry controls. Original baseline maximum horizontal
interface forces at isolated pile nodes are respectively 0.270016, 0.0730364
and 0.109027 kN/m; symmetry-control values are below 2e-13 kN/m.

These measurements support a discretization asymmetry explanation for the
small installation-stage bending: the same vertical pile loading produces
no resolved horizontal transfer or bending in either symmetric element family.
They do not isolate the individual influence of the unused anchor geometry,
triangulation or stress recovery in the original model, since the controls
change multiple geometric/discretization details together.

The interior pile tip at (0, -9) shares continuum nodes by design. Its
beam/interface-only vertical residuals are 17.6175, 14.5156 and 14.0117 kN/m
on the baseline meshes. They are **unresolved soil-transfer contributions**,
not failed isolated-node checks and not suppressed zeros. A complete tip
budget still needs continuum internal forces and continuum body-force terms.
Prescribed nodes would additionally need reactions. The helper rejects water,
external/seismic loads, imposed displacements and other active beams/bars
whose terms it does not include. It remains `diagnostic_only` and supplies no
full coupled equilibrium pass/fail certificate.

The continuum contribution was the next open step at this point; it is now
implemented as recorded below. The canonical model's self-weight, mesher
and construction stages remain unchanged.

## Completed shared-tip continuum budget

The helper now rebuilds continuum quadrature geometry directly from the mesh
and solver quadrature setting. It integrates effective Gauss-point stresses
as `integral(B.T * stress)` and dry soil body forces as
`integral(N * (0, -gamma))`. Both are scattered by actual node ID, retaining
the shared tip and excluding all coincident nodes with different IDs.
No nodal stress recovery or interpolated chart values enter this calculation.
The complete residual is beam + interface + soil internal forces, minus
beam/soil body forces and prescribed-node reactions.

All eighteen diagnostic solves were repeated with the extended helper:
[installation_continuum_budget.json](data/f7/2026-11-04/installation_continuum_budget.json).
The earlier JSON files retain the historical incomplete budget.

| Baseline h (m) | Soil tip Fx (kN/m) | Soil tip Fy (kN/m) | Complete tip Fy residual (kN/m) |
|---:|---:|---:|---:|
| 2.5 | -0.171990 | -17.617454 | 1.17e-12 |
| 1.8 | -0.008735 | -14.515608 | -1.78e-12 |
| 1.2 | -0.154917 | -14.011689 | -1.14e-12 |

These soil internal forces cancel the previously unresolved beam/interface
contributions at the tip. The consistent soil body force at these T6 corner
nodes is zero to quadrature roundoff, not omitted. Across all pile nodes and
all eighteen solves, the largest complete force residual is 1.9673e-11 kN/m
and the largest nodal moment residual is 1.825e-15 in structural moment units.
Force and moment residuals are reported separately, without combining units.

Verification includes a constant-stress unit square with analytically
integrated nodal forces, a 20 kN/m³ uniform soil weight (5 kN per corner),
and explicit reactions. Separate T6/Q8 solves check actual tip closure;
perturbing a tip-adjacent stress produces a detectable residual. Nonfinite
continuum data are rejected. The helper also rejects excavation, material
changes, undrained materials, partial load factors, inactive-interface ties,
nonzero pore pressures and variable shotcrete sections outside its contract.

This closes the **dry installation pile-node reconstruction** gap. It does
not establish independent physical validation, convergence of the original
mesh's small bending response, or the staged excavation/anchor external-force
budget. The latter remains the next numerical verification task.
