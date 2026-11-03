# Four-stage tunnel example — corrected support activation

The example repair script `examples/repair_staged_tunnel_project.py` accepts the
original four-stage tunnel `.ssproj` (a ZIP archive with `model.json` and
`mesh.h5`) and produces a separate corrected project file.

```bash
python examples/repair_staged_tunnel_project.py model.ssproj corrected_tunnel.ssproj
```

The script intentionally requires the matching original tunnel geometry and stage
region sets; it rejects a different project rather than silently changing its
construction sequence. The corrected example was supplied separately to the model
author. The original uploaded model is **not** committed to the public repository.

## Reviewed corrections

| Stage | Active regions | Support members |
| --- | --- | --- |
| 1, top heading | 1, 3, 4 | Heading shotcrete + 16 heading bolts |
| 2, bench | 1, 4 | Previous + both sidewall liners + 4 sidewall bolts |
| 3, invert | 1 | Previous + invert shotcrete |
| 4, final | 1 | Same active support set as Stage 3 |

The duplicate-looking `cad_Tunnel_Bench` and `cad_Tunnel_Inv` beam
tags remain inactive until their engineering purpose can be confirmed; activating
them together with the shotcrete linings risks artificially high support stiffness.

For the explicitly verified rectangular ground boundary, the left and right
edges constrain horizontal displacement (`ux`); the bottom constrains
both `ux` and `uy`. The original model's side constraints incorrectly
fixed vertical displacement (`uy`) instead.

## Mesh-quality limitation

The supplied mesh has 37,753 nodes and 18,694 T6 soil elements. It has 96
corner triangles with area < 0.0001 m²; the smallest is approximately
4.99e-6 m². The repair script intentionally preserves the HDF5 mesh
byte-for-byte. **Do not treat this example as a verified converged solution.**
Regenerate the mesh with local sizing controls, check curved-element Jacobians
and aspect ratios, and run the same stages at increasing mesh resolution.

The pre-existing fourth stage does not change excavation or activation, and
is retained to preserve user data; it should not be interpreted as a
consolidation time step.

The input's soil material, initial stresses, seismic factors and solver
settings are untouched. Test this model with the current solver and compare
displacements, support forces and force residuals before engineering use.
