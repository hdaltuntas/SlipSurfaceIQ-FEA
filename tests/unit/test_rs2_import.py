from __future__ import annotations

import zipfile

import pytest

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

element types:
cst_element = type: solid order: linear shape: tri

nodes:  total: 3
4 x: 0 y: 0
5 x: 1 y: 0
6 x: 0 y: 1
elements:  total: 1
1 type: cst_element nodes: [4,5,6] material: rock

springs:

body forces:

restraints:
n: 4 tx: 0 ty: 0
n: 5 ty: 0

load curve:
scale: 1.0 steps: 0
solve

#stage 2 data

set:
element: 1 material: rock

delete:
elements:

solve

stage_names:
 number: 2
Excavation
Support
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
    assert [stage.name for stage in model.stages] == ["Excavation", "Support"]
    assert model.stages[0].active_regions == frozenset({1})
    assert model.stages[1].active_regions == frozenset({1})
    assert model.fixities


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
