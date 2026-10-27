from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.io.report import export_csv, export_html
from slipsurface.fe2d.mesh import layered_box


def excavated():
    mesh = layered_box(2, [0, -1], -2, 2, [1, 1])
    return api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"s": api.MaterialSpec.elastic("s", 1e4, 0.3, gamma=18)},
        {1: "s", 2: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        stages=[api.Stage("dig <test>", active_regions={2})],
    )


def test_progress_and_cancel_are_observational():
    model = excavated()
    events = []
    actual = api.run(model, progress=events.append)
    expected = api.run(model)
    assert np.array_equal(actual.last.u, expected.last.u, equal_nan=True)
    assert [e.stage for e in events if e.completed] == ["initial", "dig <test>"]
    assert events[-1].stage_index == 1
    with pytest.raises(api.SolveCancelled):
        api.run(model, cancel=lambda: True)
    with pytest.raises(api.SolveCancelled):
        api.run(model, progress=events.append, cancel=lambda: len(events) > 2)


def test_excavation_recovery_uses_active_cells_only(tmp_path):
    result = api.run(excavated())
    st, mesh = result.last, result.model.mesh
    used = np.unique(
        np.concatenate([b.conn[st.active[b.tag]].ravel() for b in mesh.continuum_blocks()])
    )
    for method in ["spr", "average"]:
        stress = api.nodal_stress(result, method=method)
        assert np.isfinite(stress[used]).all()
        assert np.isnan(stress[np.setdiff1d(np.arange(mesh.nn), used)]).all()
    path = export_csv(result, tmp_path / "nodes.csv")
    rows = list(csv.reader(path.open()))
    assert len(rows) == mesh.nn + 1
    dead = np.flatnonzero(~np.isfinite(st.u[:, 0]))
    assert dead.size > 0
    assert rows[dead[0] + 1][3:5] == ["", ""]
    html = export_html(result, tmp_path / "report.html").read_text()
    assert "dig &lt;test&gt;" in html
    assert "dig <test>" not in html


def test_active_vtu_and_viewer_agree(tmp_path):
    pv = pytest.importorskip("pyvista", exc_type=ImportError)
    from slipsurface.fe2d.gui import to_pyvista

    result = api.run(excavated())
    expected = sum(int(mask.sum()) for mask in result.last.active.values())
    grid = to_pyvista(result)
    assert grid.n_cells == expected
    file_grid = pv.read(api.export_vtu(result, tmp_path / "dig.vtu"))
    assert file_grid.n_cells == expected
    assert np.array_equal(
        np.isnan(grid.point_data["u"][:, :2]), np.isnan(file_grid.point_data["displacement"][:, :2])
    )


def test_both_result_formats_keep_diagnostics(tmp_path):
    model = replace(excavated(), stages=[])
    result = api.run(model)
    # An optional failed-attempt diagnostic must survive persistence.
    from slipsurface.fe2d.fem.nonlinear import StageHistory, StepRecord

    result.initial.history = StageHistory(
        [
            StepRecord(
                0.5,
                3,
                [1.0, 0.1],
                False,
                termination="material_return",
                detail="test",
                material_failure={"points": []},
                worst_dofs=np.array([1, 3]),
            )
        ]
    )
    for modern in (False, True):
        path = tmp_path / f"{modern}.h5"
        if modern:
            api.save_results(result, path)
            back = api.load_results(path)
        else:
            api.write_results(result, path)
            back = api.read_results(path, model)
        step = back.initial.history.steps[0]
        assert step.termination == "material_return"
        assert step.detail == "test"
        assert step.material_failure == {"points": []}
        assert list(step.worst_dofs) == [1, 3]
