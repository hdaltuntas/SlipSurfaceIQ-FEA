"""HDF5 results and the .ssproj container (Faz 3)."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.io import (
    ResultsFile,
    load_mesh,
    load_project,
    open_project_results,
    read_results,
    save_mesh,
    save_project,
    write_results,
)
from slipsurface.fe2d.mesh import Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import add_bar, add_beams, insert_interface, nearest_node


@pytest.fixture(scope="module")
def staged():
    """Small model with every Faz 3 feature: wall + joints + anchor + water + split."""
    d = Domain()
    d.add_polygon([(-8, -10), (8, -10), (8, 0), (-8, 0)], 1,
                  edge_names=["bottom", "right", "top", "left"])  # fmt: skip
    d.add_polygon([(-8, -2), (0, -2), (0, 0), (-8, 0)], 2)
    d.add_line([(0, 0), (0, -6)], name="wall")
    d.add_point(0.0, -1.0, "head")
    d.add_point(5.0, -4.0, "fix")
    mesh = unstructured_mesh(d, h=0.8)
    mesh = add_beams(mesh, "wall", "wall/steel")  # tag with '/' (HDF5 path separator)
    mesh = insert_interface(mesh, "wall", "ifL", side="left")
    mesh = insert_interface(mesh, "wall", "ifR", side="right")
    mesh = add_bar(mesh, int(mesh.nodes("head")[0]), nearest_node(mesh, 5.0, -4.0), "anchor")
    soil = api.MaterialSpec.mohr_coulomb("soil", 3e4, 0.3, 5.0, 30.0, 0.0, gamma=18.0,
                                         gamma_sat=20.0)  # fmt: skip
    S = frozenset({"wall/steel", "ifL", "ifR"})
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": soil},
        region_material={1: "soil", 2: "soil"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress(
            "k0_field", active_structures=frozenset(), water=api.WaterCondition.piezo([[0, -3]])
        ),
        stages=[
            api.Stage("install", active_structures=S, water=api.WaterCondition.piezo([[0, -3]])),
            api.Stage(
                "dig",
                active_regions={1},
                active_structures=S,
                load_split=0.6,
                water=api.WaterCondition.piezo([[-8, -4], [8, -3]]),
            ),  # fmt: skip
            api.Stage(
                "anchor",
                active_regions={1},
                active_structures=S | {"anchor"},
                water=api.WaterCondition.piezo([[-8, -4], [8, -3]]),
                loads=(api.EdgeLoad("top", qn=10.0),),
            ),  # fmt: skip
        ],
        liners={"wall/steel": api.LinerSpec("wall/steel", 2.1e8, 0.0, 0.01, 2e-4, 0.005)},
        bolts={
            "anchor": api.BoltSpec(
                "anchor", EA=2e5, T_yield=500.0, pretension=50.0, spacing_out_of_plane=2.0
            )
        },  # fmt: skip
        interfaces={k: api.InterfaceSpec.from_soil(k, soil, R=0.67) for k in ("ifL", "ifR")},
        settings=api.SolverSettings(line_search=True),
    )
    return model, api.run(model)


def _same_stage(a, b):
    assert a.name == b.name and a.lam == b.lam
    for fld in ("u", "reactions", "rotation"):
        x, y = getattr(a, fld), getattr(b, fld)
        assert np.array_equal(np.isnan(x), np.isnan(y))
        assert np.allclose(np.nan_to_num(x), np.nan_to_num(y), rtol=0, atol=0)
    for fld in ("sig", "q", "plastic", "active", "pore", "beams", "bars", "interfaces",
                "struct_flags"):  # fmt: skip
        da, db = getattr(a, fld), getattr(b, fld)
        assert set(da) == set(db), fld
        for k in da:
            assert np.array_equal(np.nan_to_num(da[k]), np.nan_to_num(db[k])), (fld, k)
    if a.history is not None:
        assert [s.residuals for s in a.history.steps] == [s.residuals for s in b.history.steps]


def test_results_roundtrip_eager_and_lazy(staged, tmp_path):
    model, res = staged
    assert res.stages[1].lam == 0.6
    assert np.isfinite(res.last.bars["anchor"]).all()
    p = write_results(res, tmp_path / "run.h5")
    back = read_results(p, model)
    _same_stage(res.initial, back.initial)
    for a, b in zip(res.stages, back.stages):
        _same_stage(a, b)
    with ResultsFile(p) as rf:
        assert rf.stage_names == ["install", "dig", "anchor"]
        s = rf.stage("anchor")
        assert np.array_equal(s.field("beams", "wall/steel"), res.last.beams["wall/steel"])
        assert np.array_equal(rf.xg("soil"), res.geom["soil"].xg)
        m2 = rf.mesh()
        assert np.array_equal(m2.coords, model.mesh.coords)
        assert [b.tag for b in m2.blocks] == [b.tag for b in model.mesh.blocks]
        with pytest.raises(KeyError):
            rf.stage("nope")
    # post-processing works on loaded results
    api.export_vtu(back, tmp_path / "anchor.vtu")


def test_mesh_h5_roundtrip(staged, tmp_path):
    mesh = staged[0].mesh
    m2 = load_mesh(save_mesh(mesh, tmp_path / "m.h5"))
    assert np.array_equal(m2.coords, mesh.coords)
    for b1, b2 in zip(mesh.blocks, m2.blocks):
        assert b1.tag == b2.tag and b1.etype is b2.etype
        assert np.array_equal(b1.conn, b2.conn) and np.array_equal(b1.region, b2.region)
    assert m2.node_sets.keys() == mesh.node_sets.keys()
    for k in mesh.edge_sets:
        assert np.array_equal(m2.edge_sets[k], mesh.edge_sets[k])


def test_ssproj_roundtrip_reproduces_the_analysis(staged, tmp_path):
    model, res = staged
    p = save_project(tmp_path / "wall.ssproj", model, res)
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        assert {"manifest.json", "model.json", "mesh.h5", "results.h5"} <= names
        doc = json.loads(z.read("model.json"))
        assert doc["mesh"] == {"$ref": "mesh.h5"}  # diff-friendly: no arrays in JSON
    proj = load_project(p)
    for a, b in zip(res.stages, proj.results.stages):
        _same_stage(a, b)
    rerun = api.run(proj.model)  # the loaded model reproduces the analysis exactly
    for a, b in zip(res.stages, rerun.stages):
        assert np.allclose(np.nan_to_num(a.u), np.nan_to_num(b.u), rtol=1e-12, atol=1e-15)
        assert np.allclose(a.bars["anchor"], b.bars["anchor"], equal_nan=True)
    with open_project_results(p) as rf:
        assert rf.stage(-1).name == "anchor"
    # model-only project
    p2 = save_project(tmp_path / "model_only.ssproj", model)
    assert load_project(p2).results is None
    with pytest.raises(ModelError):
        open_project_results(p2)


def test_not_a_project(tmp_path):
    bad = tmp_path / "x.ssproj"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(ModelError):
        load_project(bad)
    with pytest.raises(ModelError):
        ResultsFile(save_mesh(unstructured_mesh(Domain().add_polygon([(0, 0), (1, 0), (0, 1)]),
                                                h=0.5), tmp_path / "mesh_only.h5"))  # fmt: skip


@pytest.mark.parametrize("change", ["geometry", "material", "stage"])
def test_project_rejects_results_from_different_model(staged, tmp_path, change):
    model, result = staged
    if change == "geometry":
        other = replace(model, mesh=replace(model.mesh, coords=2 * model.mesh.coords))
    elif change == "material":
        other = replace(model, materials={"soil": api.MaterialSpec.elastic("soil", 1e4, 0.3)})
    else:
        other = replace(model, stages=[api.Stage("different")])
    target = tmp_path / "untouched.ssproj"
    target.write_bytes(b"original")
    with pytest.raises(ModelError, match="different model"):
        save_project(target, other, result)
    assert target.read_bytes() == b"original"


def test_project_accepts_equivalent_model_copy(staged, tmp_path):
    model, result = staged
    path = save_project(tmp_path / "copy.ssproj", replace(model), result)
    assert load_project(path).results is not None
