"""Regression cases for rejected hydraulic/constitutive trials and phase-4 persistence."""

from dataclasses import replace

import numpy as np
import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.core.errors import MaterialIntegrationError, ModelError, SolverError
from slipsurface.fe2d.fem.materials import HoekBrown, ModifiedCamClay, hb_parameters
from slipsurface.fe2d.fem.seepage import SeepageBlock, solve_seepage
from slipsurface.fe2d.mesh import rectangle


def hydraulic_case():
    mesh = rectangle(2, 1, 2, 1, api.ElemType.Q4)
    b = mesh.blocks[0]
    block = SeepageBlock(
        b.tag, b.conn, b.etype, np.full((b.ne, 2), 1e-4), np.tile([1.0, 2.0, 1e-4], (b.ne, 1))
    )
    heads = [("left", mesh.nodes("left"), 3.0), ("right", mesh.nodes("right"), 2.0)]
    return mesh, block, heads


def test_hydraulic_result_velocity_matches_boundary_discharge():
    mesh, block, heads = hydraulic_case()
    result = solve_seepage(mesh, [block], heads)
    assert result.converged
    assert result.inflow["left"] == pytest.approx(5e-5)
    assert result.inflow["left"] + result.inflow["right"] == pytest.approx(0, abs=1e-15)
    assert result.velocity["soil"][..., 0].mean() == pytest.approx(result.inflow["left"])


def test_unconverged_flow_never_enters_mechanics(monkeypatch):
    from slipsurface.fe2d.fem import static

    mesh, block, heads = hydraulic_case()
    rejected = solve_seepage(mesh, [block], heads, max_iter=1)
    assert not rejected.converged
    monkeypatch.setattr(static, "solve_seepage", lambda *args, **kwargs: rejected)
    model = api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"s": api.MaterialSpec.elastic("s", 1e4, 0.3)},
        {1: "s"},
        fixities=(api.Fixity("bottom", True, True),),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage("flow", water=api.WaterCondition.seepage(heads={"left": 3.0, "right": 2.0}))
        ],
    )
    with pytest.raises(SolverError, match="mechanical stage was not started"):
        api.run(model)


def test_disconnected_flow_component_is_rejected():
    mesh, block, heads = hydraulic_case()
    # Duplicate a disconnected copy; no prescribed head on that copy.
    b = mesh.blocks[0]
    coords = np.vstack([mesh.coords, mesh.coords + [4, 0]])
    mesh2 = api.Mesh(
        coords,
        (replace(b, conn=np.vstack([b.conn, b.conn + mesh.nn]), region=np.tile(b.region, 2)),),
    )
    block = replace(
        block, conn=mesh2.blocks[0].conn, k=np.tile(block.k, (2, 1)), vg=np.tile(block.vg, (2, 1))
    )
    with pytest.raises(SolverError, match="singular|head"):
        solve_seepage(mesh2, [block], heads)


@pytest.mark.parametrize("settings", [{"max_iter": 0}, {"damping": 0}, {"tol": float("nan")}])
def test_invalid_seepage_controls(settings):
    mesh, block, heads = hydraulic_case()
    with pytest.raises(ModelError):
        solve_seepage(mesh, [block], heads, **settings)


def test_conflicting_heads_are_not_silently_overwritten():
    mesh, block, heads = hydraulic_case()
    heads.append(("another", mesh.nodes("left"), 8.0))
    with pytest.raises(ModelError, match="conflicting"):
        solve_seepage(mesh, [block], heads)


@pytest.mark.parametrize("params", [{"Kw_n": -1}, {"Kw_n": float("nan")}])
def test_invalid_water_stiffness(params):
    with pytest.raises(ModelError):
        api.MaterialSpec("s", "elastic", {"E": 1e4, "nu": 0.3, **params})


def test_method_b_rejects_effective_friction_strength():
    soil = api.MaterialSpec.mohr_coulomb("s", 1e4, 0.3, 10, 30)
    with pytest.raises(ModelError, match="phi = 0"):
        soil.with_drainage(api.Drainage.UNDRAINED_B)


@pytest.mark.parametrize("params", [{"p_min": 0}, {"p_ref": -1}, {"OCR": float("nan")}])
def test_mcc_invalid_regularisation(params):
    with pytest.raises(ValueError):
        ModifiedCamClay(0.25, 1.2, 0.2, 0.04, 1, **params)


def test_hoek_brown_isochoric_tensile_obstruction_preserves_inputs():
    hb = HoekBrown(5e6, 0.25, 5e4, *hb_parameters(50, 10))
    stress, history = np.zeros((2, 4)), np.zeros((2, 1))
    strain = np.array([[0.0, 0.0, 0.0, 0.0], [0.001, 0.001, 0.001, 0.0]])
    with pytest.raises(MaterialIntegrationError) as exc:
        hb.integrate(stress, strain, history)
    assert exc.value.details["points"][0]["batch_index"] == 1
    assert not stress.any() and not history.any()


def test_hoek_brown_valid_apex_has_exact_zero_tangent():
    hb = HoekBrown(5e6, 0.25, 5e4, *hb_parameters(50, 10), psi=10)
    deps = np.array([[0.001, 0.001, 0.001, 0.0]])
    sig, _, tangent, flags = hb.integrate(np.zeros((1, 4)), deps, np.zeros((1, 1)))
    assert flags[0] == api.PlasticFlag.APEX
    assert np.array_equal(tangent, np.zeros((1, 4, 4)))
    assert np.all(sig[0, :3] == hb.st)


def test_phase4_fields_roundtrip_both_project_apis(tmp_path):
    mesh = rectangle(1, 1, 2, 2)
    soil = api.MaterialSpec.elastic("s", 1e4, 0.3).with_drainage(api.Drainage.UNDRAINED_A)
    model = api.Model(
        api.Analysis.PLANE_STRAIN,
        mesh,
        {"s": soil},
        {1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[
            api.Stage(
                "load",
                loads=(api.EdgeLoad("top", qn=10),),
                water=api.WaterCondition.seepage(heads={"left": 2, "right": 2}),
            )
        ],
    )
    result = api.run(model)
    for old in (False, True):
        path = tmp_path / f"flow-{old}.ssproj"
        api.save_project(path, model, result) if old else api.save_project(model, path, result)
        back = api.load_project(path).results
        assert np.array_equal(back.last.head, result.last.head)
        assert back.last.flow == result.last.flow
        assert np.array_equal(back.last.excess_pore["soil"], result.last.excess_pore["soil"])


def test_empty_tangent_rejected_before_superlu(monkeypatch):
    import scipy.sparse as sp

    from slipsurface.fe2d.core.errors import SingularSystemError
    from slipsurface.fe2d.fem import linsolve

    matrix = sp.diags([1., 0., 1.], format="csc")
    before = matrix.copy()

    def forbidden(*args, **kwargs):
        raise AssertionError("SuperLU should not receive an empty row/column")

    monkeypatch.setattr(linsolve.spla, "splu", forbidden)
    with pytest.raises(SingularSystemError):
        linsolve.factorize(matrix, method="splu", symmetric=False)
    assert (matrix != before).nnz == 0
