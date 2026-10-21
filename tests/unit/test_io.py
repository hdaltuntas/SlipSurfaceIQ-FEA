from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np

from slipsurface.fe2d import api
from slipsurface.fe2d.io import load_model, model_from_dict, model_to_dict, save_model
from slipsurface.fe2d.mesh import rectangle


def _model():
    mesh = rectangle(4.0, 2.0, 4, 2)
    return api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"c": api.MaterialSpec.elastic("c", 1e4, 0.3, gamma=18.0)},
        region_material={1: "c"},
        fixities=(api.Fixity("bottom", True, True),),
        displacements=(api.Displacement("left", ux=0.0),),
        initial=api.InitialStress("k0_field", k0=0.5),
        stages=[
            api.Stage("a", loads=(api.EdgeLoad("top", qn=5.0), api.PointLoad(3, fy=-1.0))),
            api.Stage("b", active_regions=frozenset({1}), reset_displacements=True),
        ],
    )


def test_json_round_trip(tmp_path):
    m = _model()
    p = save_model(m, tmp_path / "m.json")
    m2 = load_model(p)
    assert model_to_dict(m2) == model_to_dict(m)
    assert np.array_equal(m2.mesh.blocks[0].conn, m.mesh.blocks[0].conn)
    assert m2.stages[0].loads[1].fy == -1.0
    assert model_from_dict(model_to_dict(m)).initial.k0 == 0.5


def test_round_tripped_model_gives_same_solution(tmp_path):
    m = _model()
    m.stages = m.stages[:1]
    m2 = load_model(save_model(m, tmp_path / "m.json"))
    r1, r2 = api.run(m), api.run(m2)
    assert np.array_equal(r1.last.u, r2.last.u)


def test_vtu_is_valid_xml(tmp_path):
    m = _model()
    m.stages = m.stages[:1]
    p = api.export_vtu(api.run(m), tmp_path / "r.vtu")
    root = ET.parse(p).getroot()
    piece = root.find("UnstructuredGrid/Piece")
    assert int(piece.get("NumberOfPoints")) == m.mesh.nn
    assert int(piece.get("NumberOfCells")) == m.mesh.blocks[0].ne
    names = {d.get("Name") for d in piece.iter("DataArray")}
    assert {"displacement", "sxx", "s1", "region", "types"} <= names
    # decode the binary payload back and compare with the source data
    import base64

    arr = next(d for d in piece.iter("DataArray") if d.get("Name") == "Points")
    raw = base64.b64decode(arr.text)
    n = int(np.frombuffer(raw[:8], dtype=np.uint64)[0])
    pts = np.frombuffer(raw[8 : 8 + n], dtype=np.float64).reshape(-1, 3)
    assert np.array_equal(pts[:, :2], m.mesh.coords)
