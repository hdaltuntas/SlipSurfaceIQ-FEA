# Mixed triangle/quad mesh (experimental)

`recombine_mesh` merges suitable pairs of triangles in an existing continuum mesh:
T3 → Q4 or T6 → Q8. Only one interpolation degree is used in the same mesh.
The triangle/quad transition is conforming through shared corner nodes and, for
quadratics, shared midside node ids; hanging nodes/MPCs are not used. No scikit-fem
dependency was added.

```python
from slipsurface.fe2d.mesh import rectangle, recombine_mesh, mesh_quality

tri = rectangle(20., 10., 40, 20)  # T6
mixed = recombine_mesh(tri, where=lambda xy: xy[:, 0] < 10.)
print(mesh_quality(mixed))
```

Do this before creating the Model, the loads, the material assignment, and the
beam/bar/interface elements. Node numbers can change; node/edge sets are remapped.
Transfer of a solved state, or of history variables, onto the new mesh is not supported.

## Preserved limits and quality

- Pairs are chosen from the same block and region; named edges are not deleted.
- A quadratic diagonal midside node that belongs to a named node set is kept (`all` excluded).
- Curved T6 pairs stay triangles. Only flat-edged, convex pairs are merged.
- The default interior-angle range is 45–135°, and the ratio of the largest edge-squared
  to the smallest corner cross product is at most 5; both can be changed with `min_angle`
  and `max_aspect`.
- Deterministic greedy matching is done by quality. A regular quad layer parallel to the
  wall, or a particular quad percentage, is not guaranteed.

`validate_conformity` rejects duplicate coordinates of used nodes, edges shared by more
than two elements, inconsistent midside nodes, and hanging corners on straight edges.
It does not check general curved-edge intersection or overlap inside an element.
`mesh_quality` now reports the triangle/quad counts and the scaled Jacobian at quad
corners. The radius/edge ratio is for triangles only; corner-geometry measures do not
replace an interior Jacobian check of curved elements.

## Verified scope

In `test_mixed_mesh.py`, `test_mixed_patch.py`, and `test_e2_cantilever.py` the following
are checked: geometry/set preservation and determinism; plane and axisymmetric constant
strain on a distorted mesh; tension with the minimum rigid-body restraints; analytical
cantilever deflection and reactions; analytical Tresca plastic compression; excavation/backfill
on an elastic path; a two-sided liner/interface; hydrostatic pressure and force balance;
HDF5/.ssproj/VTU round trip. On the higher-order mesh the hydrostatic effective-stress
field is also checked analytically. This scope does not mean that the nonlinear sheet
pile in soil has been verified.

## Comparison on the same sheet-pile model

The sheet-pile numerical records in this document were taken before the embedded-tip
connection of the two-sided interface was fixed. The old model split the tip on the
second side that was added; the current code keeps the tip shared on both sides. The
old values are diagnostic history; the current model and the replays are in the
[S4 protocol](s4-comparison.md).

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order default --csv /tmp/pile-default.csv
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order high --csv /tmp/pile-high.csv
```

Both models use the same geometry, materials, boundaries, and load stages. In the mixed
model only suitable pairs with |x| < 4 m are merged. A failed run returns exit code 1;
the last converged load factor is reported, and no completed-stage moment/displacement
is produced.

| h (m) | Mesh | Nodes | T6 / Q8 | GP (default / high) |
|---|---|---:|---:|---:|
| 0.50 | T6 | 3889 | 1829 / 0 | 5487 / 10974 |
| 0.50 | T6+Q8 | 3658 | 1367 / 231 | 5025 / 10281 |
| 0.25 | T6 | 5380 | 2520 / 0 | 7560 / 15120 |
| 0.25 | T6+Q8 | 4917 | 1594 / 463 | 6634 / 13731 |

`default`: T6 with 3 GP, Q8 with 2×2 reduced integration; `high`: T6 with 6 GP, Q8 with 3×3.
On the coarse mesh the node count drops by 5.94% and the default GP count by 8.42%. This
is not a speed-up or a nonlinear-convergence guarantee. In the first fix (`b5dfcbe`) of the
bug that hid a failed local MC return behind an elastic trial flagged `255`, the same eight
runs were repeated; the records below are for that code with no tension cut-off selected.

| h (m) | Mesh | Integration | Excavation final load factor | Completed? |
|---|---|---|---:|---|
| 0.50 | T6 | default | 0.98698 | No |
| 0.50 | T6+Q8 | default | 1.00000 | Yes |
| 0.25 | T6 | default | 0.88966 | No |
| 0.25 | T6+Q8 | default | 0.57445 | No |
| 0.50 | T6 | high | 0.96729 | No |
| 0.50 | T6+Q8 | high | 0.14826 | No |
| 0.25 | T6 | high | 0.42167 | No |
| 0.25 | T6+Q8 | high | 0.06509 | No |

In the only completed run, |M|max = 168.278009 kNm/m and the maximum nodal displacement
norm is 0.04217045 m. Because the equivalent T6 run did not complete, a verified moment
difference or a mesh-convergence calculation cannot be made. The previously reported 1.80%
difference and the other load factors belong to the unguarded code; they have been withdrawn
as verification evidence.

The high mixed coarse-mesh diagnosis showed 6 Gauss points flagged `255` in the old
accepted state; after the guard that state is not accepted. The separating elastic-soil
run completed. The local error, its effect on P4, and the diagnostic commands:
[nonlinear-diagnostics.md](nonlinear-diagnostics.md).
Tolerances and the physical material parameters were not changed in this comparison.
The gates stay open until the fine-mesh convergence, P4, and an independent S4 reference are resolved.

With the explicit `--soil-tension 0` choice, all four of the current high-integration
cases complete; the definition of that different tension flow, the local tests, and the
new result table are in [coincident-tension-cutoff.md](coincident-tension-cutoff.md).
