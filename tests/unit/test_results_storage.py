"""Persistence checks on solved models, including mixed structural stage snapshots."""

from __future__ import annotations

import json
import zipfile
from dataclasses import fields

import h5py
import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.io.project_json import model_to_dict
from slipsurface.fe2d.mesh import rectangle
from slipsurface.fe2d.mesh.structures import add_bar, add_beams, insert_interface


def _model():
    mesh = rectangle(2, 1, 2, 1, etype=api.ElemType.Q4)
    a = int(np.flatnonzero(np.all(mesh.coords == [1, 0], axis=1))[0])
    b = int(np.flatnonzero(np.all(mesh.coords == [1, 1], axis=1))[0])
    mesh.edge_sets["joint"] = np.array([[a, b]])
    mesh = insert_interface(mesh, "joint", "joint/soil")
    mesh = add_beams(mesh, "right", "wall/1")
    right = mesh.nodes("right")
    mesh = add_bar(mesh, int(right[0]), int(right[-1]), "bolt/1")
    active = frozenset({"joint/soil", "wall/1", "bolt/1"})
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"soil": api.MaterialSpec.elastic("soil", 2e4, 0.3)},
        region_material={1: "soil"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage("load/one", active_structures=active, loads=(api.EdgeLoad("top", qn=10),)),
            api.Stage(
                "load/one",
                active_structures=active,
                reset_displacements=True,
                loads=(api.EdgeLoad("top", qn=20),),
            ),
        ],
        liners={"wall/1": api.LinerSpec("wall/1", 1e6, 0.2, 0.1, 1e-3, 0.08)},
        bolts={"bolt/1": api.BoltSpec("bolt/1", 2e4, 1e5)},
        interfaces={"joint/soil": api.InterfaceSpec("joint/soil", 1e6, 1e6, c=1e6)},
    )


def _assert_stage(a, b):
    for f in fields(a):
        x, y = getattr(a, f.name), getattr(b, f.name)
        if isinstance(x, np.ndarray):
            np.testing.assert_array_equal(x, y)
            assert x.dtype == y.dtype
        elif isinstance(x, dict) and x and isinstance(next(iter(x.values())), np.ndarray):
            assert x.keys() == y.keys()
            for key in x:
                np.testing.assert_array_equal(x[key], y[key])
                assert x[key].dtype == y[key].dtype
        else:
            assert x == y


@pytest.fixture
def solved():
    return api.run(_model())


def test_h5_roundtrip_and_postprocessing(tmp_path, solved):
    path = api.save_results(solved, tmp_path / "results.h5")
    loaded = api.load_results(path)
    assert model_to_dict(loaded.model) == model_to_dict(solved.model)
    _assert_stage(solved.initial, loaded.initial)
    for a, b in zip(solved.stages, loaded.stages):
        _assert_stage(a, b)
    np.testing.assert_array_equal(api.nodal_stress(solved), api.nodal_stress(loaded))
    api.export_vtu(loaded, tmp_path / "loaded.vtu")
    with h5py.File(path) as root:
        assert root["stages/0/u"].compression == "gzip"
        assert root.attrs["stress_convention"] == "tension_positive"


def test_h5_reads_history_without_new_diagnostics(tmp_path, solved):
    path = api.save_results(solved, tmp_path / "old-history.h5")
    with h5py.File(path, "a") as root:
        group = root["stages/0"]
        data = json.loads(group["history"].asstr()[()])
        for step in data["steps"]:
            for key in ("termination", "force_norms", "energy_ratios", "detail"):
                step.pop(key)
        del group["history"]
        group.create_dataset("history", data=json.dumps(data), dtype=h5py.string_dtype("utf-8"))
    loaded = api.load_results(path)
    assert loaded.stages[0].history.n_steps == solved.stages[0].history.n_steps
    assert all(s.termination == "" for s in loaded.stages[0].history.steps)
    np.testing.assert_array_equal(loaded.stages[0].u, solved.stages[0].u)


def test_lazy_stage_detaches_and_preserves_duplicate_names(tmp_path, solved):
    path = api.save_results(solved, tmp_path / "results.h5")
    with api.ResultsReader(path) as reader:
        assert reader.stage_names == ("load/one", "load/one")
        _assert_stage(solved.stages[0], reader.stage("load/one"))
        last = reader.stage(-1)
        with pytest.raises(KeyError):
            reader.stage("missing")
        with pytest.raises(IndexError):
            reader.stage(2)
    _assert_stage(solved.last, last)


def test_future_h5_rejected(tmp_path, solved):
    path = api.save_results(solved, tmp_path / "results.h5")
    with h5py.File(path, "a") as root:
        root.attrs["schema_version"] = 999
    with pytest.raises(ModelError, match="schema"):
        api.load_results(path)


@pytest.mark.parametrize("with_results", [False, True])
def test_project_roundtrip(tmp_path, solved, with_results):
    path = api.save_project(
        solved.model, tmp_path / "model.ssproj", solved if with_results else None
    )
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"model.json", "mesh.h5"} | (
            {"results.h5"} if with_results else set()
        )
        doc = json.loads(z.read("model.json"))
        assert "mesh" not in doc
    project = api.load_project(path)
    assert model_to_dict(project.model) == model_to_dict(solved.model)
    rerun = api.run(project.model)
    np.testing.assert_array_equal(rerun.last.u, solved.last.u)
    if with_results:
        _assert_stage(project.results.last, solved.last)
    else:
        assert project.results is None
    assert api.load_project(path, include_results=False).results is None


def test_initial_only_empty_internal_arrays_and_inactive_nan(tmp_path):
    model = _model()
    model.stages = []
    solved = api.run(model)
    path = api.save_results(solved, tmp_path / "initial.h5")
    loaded = api.load_results(path)
    assert loaded.stages == []
    _assert_stage(loaded.last, solved.initial)
    assert np.isnan(loaded.last.bars["bolt/1"]).all()


def test_atomic_failure_keeps_previous_file(tmp_path, solved, monkeypatch):
    from slipsurface.fe2d.io import results_h5

    path = tmp_path / "results.h5"
    path.write_bytes(b"previous file")

    def fail(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(results_h5, "_write_stage", fail)
    with pytest.raises(OSError, match="disk failure"):
        api.save_results(solved, path)
    assert path.read_bytes() == b"previous file"
    assert list(tmp_path.iterdir()) == [path]


def test_project_rejects_mismatched_results(tmp_path, solved):
    model = _model()
    model.stages = []
    with pytest.raises(ModelError, match="different model"):
        api.save_project(model, tmp_path / "m.ssproj", solved)


def test_project_rejects_future_version(tmp_path):
    path = tmp_path / "m.ssproj"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("model.json", json.dumps({"project_version": 999}))
        z.writestr("mesh.h5", b"")
    with pytest.raises(ModelError, match="version"):
        api.load_project(path)


def test_lazy_open_does_not_read_stage_arrays(tmp_path, solved, monkeypatch):
    from slipsurface.fe2d.io import results_h5

    solved.stages = solved.stages * 6
    path = api.save_results(solved, tmp_path / "many.h5")
    original = results_h5._read_stage
    calls = []

    def read(group):
        calls.append(group.name)
        return original(group)

    monkeypatch.setattr(results_h5, "_read_stage", read)
    with api.ResultsReader(path) as reader:
        assert calls == []
        reader.stage(10)
        assert calls == ["/stages/10"]
    loaded = api.load_results(path)
    assert len(loaded.stages) == 12


def test_project_rejects_inconsistent_embedded_results(tmp_path, solved):
    path = api.save_project(solved.model, tmp_path / "m.ssproj", solved)
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    doc = json.loads(members["model.json"])
    doc["stages"][0]["loads"][0]["qn"] = 500
    members["model.json"] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    with pytest.raises(ModelError, match="do not match"):
        api.load_project(path)


def test_mixed_vtu_cell_array_lengths(tmp_path, solved):
    import base64
    import xml.etree.ElementTree as ET

    root = ET.parse(api.export_vtu(solved, tmp_path / "mixed.vtu"))
    piece = root.find("UnstructuredGrid/Piece")
    ncell = int(piece.get("NumberOfCells"))
    for array in piece.findall("CellData/DataArray"):
        raw = base64.b64decode(array.text)
        size = int(np.frombuffer(raw[:8], dtype=np.uint64)[0])
        item_size = {"Int32": 4, "Float64": 8}[array.get("type")]
        assert size // item_size == ncell


def test_vtu_rejects_wrong_cell_count(tmp_path, solved):
    from slipsurface.fe2d.io.vtk_export import write_vtu

    with pytest.raises(ValueError, match="cell data"):
        write_vtu(tmp_path / "bad.vtu", solved.model.mesh, cell_data={"plastic": np.zeros(1)})


@pytest.mark.parametrize("analysis", [api.Analysis.PLANE_STRAIN, api.Analysis.AXISYMMETRIC])
def test_plastic_gauss_state_roundtrip(tmp_path, analysis):
    mesh = rectangle(1, 1, 2, 2)
    if analysis is api.Analysis.AXISYMMETRIC:
        mesh = api.Mesh(mesh.coords + [1, 0], mesh.blocks, mesh.node_sets, mesh.edge_sets)
    model = api.Model(
        analysis=analysis,
        mesh=mesh,
        materials={"mc": api.MaterialSpec.mohr_coulomb("mc", 2e4, 0.3, 10, 0)},
        region_material={1: "mc"},
        initial=api.InitialStress("none"),
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False)),
        stages=[api.Stage("compress", displacements=(api.Displacement("top", uy=-0.01),))],
    )
    result = api.run(model)
    assert any(np.any(flag) for flag in result.last.plastic.values())
    loaded = api.load_results(api.save_results(result, tmp_path / "plastic.h5"))
    _assert_stage(loaded.last, result.last)
    np.testing.assert_array_equal(api.nodal_stress(loaded), api.nodal_stress(result))
