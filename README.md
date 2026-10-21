# SlipSurface 2D (`slipsurface.fe2d`)

Plane strain / axisymmetric geotechnical finite element core — staged construction,
excavation & support, seepage coupling and elasto-plasticity — as a GUI-independent,
MIT-licensed Python package. The roadmap and architecture are described in
*SlipSurface 2D — Teknik Mimari ve Yol Haritası* (Oct 2026).

**Status: Faz 1 (lineer elastik statik çekirdek).**

## Install (development)

```bash
pip install -e ".[dev]"
pytest                    # unit + verification tests
pytest -m benchmark       # Kapı 1 performance criterion
```

## Quick start

```python
from slipsurface.fe2d import api
from slipsurface.fe2d.mesh import rectangle

mesh = rectangle(20.0, 10.0, 40, 20)            # T6 by default; sets: bottom/top/left/right
model = api.Model(
    analysis=api.Analysis.PLANE_STRAIN,
    mesh=mesh,
    materials={"clay": api.MaterialSpec.elastic("clay", E=2e4, nu=0.3, gamma=18.0)},
    region_material={1: "clay"},
    fixities=(api.Fixity("bottom", True, True),
              api.Fixity("left", True, False),
              api.Fixity("right", True, False)),
    stages=[api.Stage("surcharge", loads=(api.EdgeLoad("top", qn=100.0),))],
)
res = api.run(model)                  # gravity initial stress + stages
api.export_vtu(res, "surcharge.vtu")  # open in ParaView
```

### Unstructured mesh (Delaunay + Ruppert)

```python
from slipsurface.fe2d.mesh import Domain, DistanceSize, circle, unstructured_mesh, mesh_quality

ring = circle(0.0, -15.0, 4.0, 64)
d = Domain()
d.add_polygon([(-40, -50), (40, -50), (40, 0), (-40, 0)], region=2,
              edge_names=["bottom", "right", "top", "left"])
d.add_polygon([(-40, -6), (40, -6), (40, 0), (-40, 0)], region=1)   # upper layer
d.add_polygon(ring, hole=True, name="tunnel")                        # opening
d.add_line([(-10, 0), (-10, -12)], name="wall")                      # embedded line
mesh = unstructured_mesh(d, h=DistanceSize(0.4, 4.0, 1.25, lines=[ring], closed=[True]))
print(mesh_quality(mesh))   # min angle ≥ 28° (default target) except at small input angles
```

Regions need no seed points: each patch takes the region of the innermost polygon that
contains it. Every named polygon edge, polygon or line becomes an edge/node set; named
points become one-node sets; `boundary` and `all` are always present. See
`examples/tunnel_unstructured_elastic.py`.

## Conventions

* Units: kN, m, kPa, s. Axisymmetric quantities are **per radian** (x = r, y = z).
* Core sign convention: **tension positive**, stress `[sxx, syy, szz, txy]`, engineering
  shear strain. Compression-positive display is a post-processing concern only.
* `EdgeLoad.qn > 0` is a pressure (pushes into the material); the outward side is found
  from the adjacent element, so edge node order does not matter.

## Layers

| Layer | Package | Depends on |
|---|---|---|
| L6 | `api/` (`cli/`, `gui/` later) | L0–L5 |
| L5 | `io/` — project JSON, VTU | L0–L4 |
| L4 | `post/` — stress recovery, principal stresses | L0–L3 |
| L3 | `fem/` — elements, materials, assembly, stage driver | L0–L2 |
| L2 | `mesh/` — structured + Delaunay/Ruppert mesh generation, size fields, quality | L0–L1 |
| L1 | `model/` — immutable model definition | L0 |
| L0 | `core/` — units, enums, errors, logging | NumPy |

## Verification (Kapı 1)

See [`docs/verification.md`](docs/verification.md).

## License

MIT — see [LICENSE](LICENSE). The "SlipSurface" name and logo are not covered by the
code license.
