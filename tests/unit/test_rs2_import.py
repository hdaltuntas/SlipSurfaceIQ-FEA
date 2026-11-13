from __future__ import annotations

import zipfile
from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d.fem.static import StaticSolver
from slipsurface.fe2d.io.project_json import model_from_dict, model_to_dict
from slipsurface.fe2d.io.rs2_import import RS2ImportError, import_rs2


def _fea() -> str:
    return """model description:
RFCunits: Metric MPa
option: plane strain
stages: 2

material types:
rock = formulation: mohr_coulomb E: 500 nu: 0.25
 C: 0.12 phi: 30 T: 0.01 Tr: 0
 dil: 5 rho: 0.02
rock2 = formulation: mohr_coulomb E: 1000 nu: 0.3
 C: 0.2 phi: 20 T: 0.01 Tr: 0.01
 Cr: 0.2 phir: 20 Eres: 1000 dil: 2 rho: 0.024
beam1 = formulation: eulerbeam beamlinear: 0 E: 30000 nu: 0
 sj: 0 sjs: 5 beamA_I_Flag: 0 beamthick: 0.2

element types:
cst_element = type: solid order: linear shape: tri

nodes:  total: 3
4 x: 0 y: 0
5 x: 1 y: 0
6 x: 0 y: 1
elements:  total: 1
1 type: cst_element nodes: [4,5,6] material: rock

springs:

stresses:
e: 1 sxx: -0.01 syy: -0.02 sxy: 0.003 szz: -0.015 Kx: 1 Kz: 1 Lx: 0 Lz: 0

body forces:

restraints:
n: 4 tx: 0 ty: 0
n: 5 ty: 0

load curve:
scale: 1.0 steps: 0
body forces:
e: 1 bx: 0.002 by: -0.003
solve

#stage 2 data

set:
element: 1 material: rock2

delete:
element: 1
elements:

change material:
material: beam1 E: 10000 nu: 0 beamA_I_Flag: 0 beamthick: 0.15

beams:
2 type: l_beam2c2 nodes: [4,5] orientation: 0 material: beam1

body forces:
e: 1 by: 0.02

solve

stage_names:
 number: 2
Excavation
Support

bolts start:
  num bolts: 1
  bolt 1 start:
    stage in: 2
    stage out: 2
  bolt 1 end:
bolts end:
"""


def test_import_fea_sparse_node_ids_and_metric_unit_conversion(tmp_path):
    source = tmp_path / "tiny.fea"
    source.write_text(_fea(), encoding="latin1")

    imported = import_rs2(source)
    model, report = imported.model, imported.report

    assert report.nodes == 3
    assert report.continuum_elements == 1
    assert report.stages == 2
    assert model.mesh.coords.tolist() == [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    assert model.mesh.blocks[0].conn.tolist() == [[0, 1, 2]]
    assert model.materials["rock"].params["E"] == pytest.approx(500_000.0)
    assert model.materials["rock"].params["c"] == pytest.approx(120.0)
    assert model.materials["rock"].gamma_unsat == pytest.approx(20.0)
    assert model.initial.mode == "element_field"
    assert model.initial.gravity is False
    assert model.initial.element_field[1] == pytest.approx((-10.0, -20.0, -15.0, 3.0))
    assert model.stages[0].element_body_force[1] == pytest.approx((2.0, -3.0))
    assert model.stages[1].element_body_force[1] == pytest.approx((2.0, 20.0))
    force_model = replace(model, fixities=())
    solver = StaticSolver(force_model)
    ctx = solver.stage_context(force_model.stages[0], {})
    system = solver.build_system(
        solver.layout({}), ctx.active, ctx.water, ctx.displacements
    )
    body_force = solver.external_force(system, ctx)
    np.testing.assert_allclose(
        body_force[system.dm.node_dofs[:, 0]].sum(), 1.0, atol=1e-12
    )
    np.testing.assert_allclose(
        body_force[system.dm.node_dofs[:, 1]].sum(), -1.5, atol=1e-12
    )
    _, initial_result = solver.initial_state()
    np.testing.assert_allclose(
        initial_result.sig["rs2_continuum"][0],
        np.tile([-10.0, -20.0, -15.0, 3.0],
                (initial_result.sig["rs2_continuum"].shape[1], 1)),
    )
    restored = model_from_dict(model_to_dict(model))
    assert restored.initial.element_field == model.initial.element_field
    assert restored.stages[1].liner_override == model.stages[1].liner_override
    assert restored.stages[0].element_body_force == model.stages[0].element_body_force
    assert restored.stages[1].element_body_force == model.stages[1].element_body_force
    assert [stage.name for stage in model.stages] == ["Excavation", "Support"]
    assert model.stages[0].active_regions == frozenset({1})
    assert model.stages[1].active_regions == frozenset()
    assert model.stages[1].material_override == {1: "rock2"}
    assert model.stages[1].active_structures == frozenset({"beam1"})
    assert model.stages[1].liner_override["beam1"].E == pytest.approx(10_000_000.0)
    assert model.stages[1].liner_override["beam1"].A == pytest.approx(0.15)
    assert model.mesh.blocks[1].etype.name == "BEAM2"
    assert report.beam_elements == 1
    assert report.bolt_groups == 1
    assert not any("body-force" in item for item in report.unsupported_features)
    assert any("bolt groups" in item for item in report.unsupported_features)
    assert model.fixities
    assert any("rock residual parameters differ" in item for item in report.unsupported_features)


def test_import_fez_reads_embedded_fea(tmp_path):
    archive_path = tmp_path / "tiny.fez"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("tiny.fea", _fea())
        archive.writestr("tiny.r01", "RS2 results are not imported")

    imported = import_rs2(archive_path)
    assert imported.report.source == "tiny.fez:tiny.fea"
    assert imported.report.continuum_elements == 1


def test_import_rejects_unsupported_units(tmp_path):
    source = tmp_path / "bad.fea"
    source.write_text(_fea().replace("Metric MPa", "Imperial"), encoding="latin1")
    with pytest.raises(RS2ImportError, match="unit system"):
        import_rs2(source)
