"""CAD contracts: topology, physical boundaries, persistence and strict DXF."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("shapely")
pytest.importorskip("ezdxf")
import ezdxf

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.dxf import read_dxf, write_dxf
from slipsurface.fe2d.cad.geometry import BoundaryRule, Drawing, Entity, snap_point
from slipsurface.fe2d.io.project_json import model_from_dict, model_to_dict


def square(name, x0, y0, x1, y1, kind="region", region=1):
    return Entity(name, kind, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)), region)


@pytest.mark.parametrize(
    "points",
    [
        ((0, 0), (2, 2), (0, 2), (2, 0)),
        ((0, 0), (1, 0), (2, 0)),
        ((0, 0), (2, 0), (2, 2), (2, 0)),
        ((0, 0), (1, 0), (float("nan"), 1)),
    ],
)
def test_rejects_invalid_polygon(points):
    with pytest.raises(ValueError):
        Entity("bad", "region", points)


def test_hole_region_line_and_mesh_area():
    d = replace(Drawing.example(), h=2)
    d = replace(
        d,
        entities=(
            *d.entities,
            square("inside", 2, 2, 4, 4, region=2),
            square("void", 7, 2, 9, 4, "hole"),
            Entity("constraint", "line", ((1, 1), (5, 1))),
        ),
    )
    m = d.build_model()
    xyz = m.mesh.coords[m.mesh.blocks[0].conn[:, :3]]
    a, b = xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]
    area = 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    assert area.min() > 0
    assert area.sum() == pytest.approx(72 - 4)
    assert area[m.mesh.blocks[0].region == 2].sum() == pytest.approx(4)
    assert m.mesh.edge_sets["constraint:1"].size


@pytest.mark.parametrize(
    "entity",
    [
        square("overlap", 10, 2, 15, 4),
        square("outside_hole", 11, 2, 13, 4, "hole"),
        square("touching_hole", 0, 2, 2, 4, "hole"),
        Entity("outside_line", "line", ((2, 2), (15, 2))),
    ],
)
def test_invalid_topology_is_rejected_before_meshing(entity):
    d = Drawing.example()
    with pytest.raises(ValueError):
        replace(d, entities=(*d.entities, entity)).validate()


def test_support_and_internal_pressure_checks():
    d = replace(Drawing.example(), h=3)
    with pytest.raises(ValueError, match="rijit"):
        replace(d, rules=()).build_model()
    interior = square("inner", 3, 2, 5, 4, region=2)
    with pytest.raises(ValueError, match="basınç yalnız"):
        replace(
            d,
            entities=(*d.entities, interior),
            rules=(*d.rules, BoundaryRule("inner:1", pressure=1)),
        ).build_model()
    isolated = square("island", 16, 0, 20, 4)
    with pytest.raises(ValueError, match="rijit"):
        replace(d, entities=(*d.entities, isolated)).build_model()


def test_duplicate_boundary_pressure_is_not_summed_silently():
    d = replace(Drawing.example(), h=2)
    line = Entity("duplicate", "line", ((0, 6), (12, 6)))
    with pytest.raises(ValueError, match="iki basınç"):
        replace(
            d,
            entities=(*d.entities, line),
            rules=(*d.rules, BoundaryRule("duplicate:1", pressure=50)),
        ).build_model()


def test_world_coordinates_do_not_remove_last_corner():
    from slipsurface.fe2d.mesh import Domain, unstructured_mesh

    offset = np.array([1e6, 2e6])
    p = np.array([[0, 0], [12, 0], [12, 6], [0, 6]]) + offset
    d = Domain().add_polygon(p)
    assert d.build().polygons[0].area == 72
    assert d.build().polygons[0].coords.shape == (4, 2)
    mesh = unstructured_mesh(d, h=2)
    x = mesh.coords[mesh.blocks[0].conn[:, :3]]
    a, b = x[:, 1] - x[:, 0], x[:, 2] - x[:, 0]
    assert 0.5 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() == pytest.approx(72)


def test_analytic_patch_and_both_project_formats(tmp_path):
    d = replace(Drawing.example(), h=2)
    m = d.build_model()
    result = api.run(m)
    assert np.allclose(result.last.sig["soil"][:, :, 1], -50, atol=1e-9)
    constrained_modulus = d.E * (1 - d.nu) / ((1 + d.nu) * (1 - 2 * d.nu))
    top = m.mesh.node_sets["Zemin:3"]
    assert np.allclose(result.last.u[top, 1], -50 * 6 / constrained_modulus, atol=1e-12)
    for old in (False, True):
        path = tmp_path / f"project_{old}.ssproj"
        api.save_project(path, m, result) if old else api.save_project(m, path, result)
        loaded = api.load_project(path)
        assert Drawing.from_dict(loaded.model.geometry) == d
        assert np.array_equal(loaded.results.last.u, result.last.u)
    clone = model_from_dict(model_to_dict(m))
    clone.geometry["entities"][0]["name"] = "changed"
    assert m.geometry["entities"][0]["name"] == "Zemin"


def test_snap_endpoint_midpoint_grid_and_free():
    entities = Drawing.example().entities
    assert snap_point((0.02, 0.01), entities, 0.05, 1)[0] == (0, 0)
    assert snap_point((6.02, 0.01), entities, 0.05, 1)[0] == (6, 0)
    assert snap_point((3.21, 2.64), entities, 0.05, 0.5)[0] == (3, 2.5)
    assert snap_point((3.21, 2.64), entities, 0.05, 0)[0] == (3.21, 2.64)


def test_dxf_roundtrip_scaling_and_void_role(tmp_path):
    d = Drawing.example()
    d = replace(d, entities=(*d.entities, square("Boşluk", 2, 2, 4, 4, "hole")))
    path = tmp_path / "drawing.dxf"
    write_dxf(d, path)
    loaded = read_dxf(path, metres_per_unit=1)
    assert loaded.entities == d.entities
    assert loaded.rules == ()  # DXF carries geometry only
    scaled = read_dxf(path, metres_per_unit=0.001)
    assert np.allclose(scaled.entities[0].points, np.asarray(d.entities[0].points) / 1000)
    assert ezdxf.readfile(path).units == 6


@pytest.mark.parametrize("kind", ["arc", "bulge", "z", "block", "text"])
def test_dxf_rejects_lossy_imports(tmp_path, kind):
    doc = ezdxf.new()
    ms = doc.modelspace()
    if kind == "arc":
        ms.add_arc((0, 0), 2, 0, 90)
    elif kind == "bulge":
        ms.add_lwpolyline([(0, 0, 1), (2, 0, 0)], format="xyb")
    elif kind == "z":
        ms.add_line((0, 0, 3), (1, 1, 3))
    elif kind == "block":
        doc.blocks.new("box").add_line((0, 0), (1, 1))
        ms.add_blockref("box", (0, 0))
    else:
        ms.add_text("annotation")
    path = tmp_path / "unsupported.dxf"
    doc.saveas(path)
    with pytest.raises(ValueError):
        read_dxf(path, metres_per_unit=1)


def test_mesher_cancellation_callback():
    calls = []

    def stop():
        calls.append(1)
        raise api.SolveCancelled("cancel")

    with pytest.raises(api.SolveCancelled):
        Drawing.example().build_model(stop)
    assert len(calls) == 1
