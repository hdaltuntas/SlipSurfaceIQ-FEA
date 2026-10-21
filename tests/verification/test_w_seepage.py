"""W1–W3 — steady seepage (Faz 4).

* W1: confined flow under a sheet pile in a layer of thickness T (penetration S),
  Harr (1962) conformal mapping: q / (k H) = K(m') / (2 K(m)), m = sin(pi S / 2T),
  m' = sqrt(1 - m^2) (complete elliptic integrals). Criterion: discharge < 2 %.
* W2: rectangular dam with a free surface and a seepage face; the Dupuit-Forchheimer
  discharge q = k (h1^2 - h2^2) / (2 L) is exact for the discharge (Charny 1951).
  Criterion: < 3 %. The remaining difference is flow through the unsaturated zone above
  the free surface and shrinks with steeper van Genuchten curves.
* W3: zero-gradient seepage (equal heads on all boundaries) gives the hydrostatic pore
  pressures of the equivalent piezometric line; the whole staged analysis is identical.
  Criterion: < 1e-8.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import ellipk

from slipsurface.fe2d import api
from slipsurface.fe2d.fem.seepage import SeepageBlock, relative_conductivity, solve_seepage
from slipsurface.fe2d.mesh import DistanceSize, Domain, unstructured_mesh
from slipsurface.fe2d.mesh.structures import insert_interface


def harr(T: float, S: float) -> float:
    m = np.sin(np.pi * S / (2 * T))
    return float(ellipk(1 - m**2) / (2 * ellipk(m**2)))  # scipy uses the parameter m^2


# ------------------------------------------------------------------------------ W1
@pytest.mark.parametrize("S", [3.0, 6.0, 8.0])
def test_w1_sheet_pile_confined_flow(S):
    T, H, k, L = 10.0, 4.0, 1e-5, 40.0
    d = Domain().add_polygon([(-L, -T), (L, -T), (L, 0), (0, 0), (-L, 0)],
                             edge_names=["bottom", "right", "down", "up", "left"])  # fmt: skip
    d.add_line([(0, 0), (0, -S)], name="pile")
    mesh = unstructured_mesh(d, h=DistanceSize(0.25, 3.0, 1.2, points=np.array([[0, -S]])))
    mesh = insert_interface(mesh, "pile", "pile")  # impermeable sheet pile
    assert np.intersect1d(mesh.nodes("up"), mesh.nodes("down")).size == 0
    soil = api.MaterialSpec.elastic("s", 3e4, 0.3, gamma=18.0, gamma_sat=20.0)
    soil = api.MaterialSpec(**{**soil.__dict__, "k_sat": (k, k)})
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials={"s": soil},
        region_material={1: "s"},
        fixities=(
            api.Fixity("bottom", True, True),
            api.Fixity("left", True, False),
            api.Fixity("right", True, False),
        ),
        initial=api.InitialStress("none"),
        stages=[api.Stage("flow", water=api.WaterCondition.seepage({"up": H, "down": 0.0}))],
        interfaces={"pile": api.InterfaceSpec("pile", kn=1e6, ks=1e5)},
    )
    st = api.run(model).last
    q_in, q_out = st.flow["up"], -st.flow["down"]
    assert q_in == pytest.approx(q_out, rel=1e-9)  # mass balance
    err = q_in / (k * H) / harr(T, S) - 1
    assert abs(err) < 0.02, f"discharge error {err:.3%}"
    # head drops by H across the pile tip region; upstream surface at H, downstream at 0
    assert np.allclose(st.head[mesh.nodes("up")], H) and np.allclose(st.head[mesh.nodes("down")], 0)


# ------------------------------------------------------------------------------ W2
def _dam(h: float):
    L, Hd, h1, h2 = 10.0, 10.0, 8.0, 1.0
    d = Domain().add_polygon(
        [(0, 0), (L, 0), (L, h2), (L, Hd), (0, Hd), (0, h1)],
        edge_names=["bottom", "down_wet", "seep", "top", "up_dry", "up_wet"],
    )
    return unstructured_mesh(d, h=h), (L, h1, h2)


@pytest.mark.parametrize("alpha,n,tol", [(5.0, 3.0, 0.03), (10.0, 4.0, 0.015)])
def test_w2_dam_free_surface_discharge(alpha, n, tol):
    k = 1e-5
    mesh, (L, h1, h2) = _dam(0.5)
    b = mesh.block("soil")
    blk = SeepageBlock("soil", b.conn, b.etype, np.full((b.ne, 2), k),
                       np.tile([alpha, n, 1e-5], (b.ne, 1)))  # fmt: skip
    r = solve_seepage(
        mesh,
        [blk],
        [("up", mesh.nodes("up_wet"), h1), ("down", mesh.nodes("down_wet"), h2)],
        seepage_faces=[("seep", mesh.nodes("seep"))],
    )
    assert r.converged
    q_d = k * (h1**2 - h2**2) / (2 * L)
    q_in = r.inflow["up"]
    q_out = -(r.inflow["down"] + r.inflow["seep"])
    assert q_in == pytest.approx(q_out, rel=1e-8)
    assert abs(q_in / q_d - 1) < tol, q_in / q_d
    # a seepage face forms above the tailwater: exit point between h2 and h1
    y_exit = mesh.coords[r.seepage_nodes, 1].max()
    assert h2 < y_exit < h1
    assert r.inflow["seep"] < 0  # outflow through the seepage face
    # free surface: positive pressure low upstream, suction near the top downstream
    top_right = int(np.argmin(np.hypot(mesh.coords[:, 0] - L, mesh.coords[:, 1] - 10.0)))
    assert r.pressure[top_right] < 0


# ------------------------------------------------------------------------------ W3
def test_w3_zero_gradient_equals_piezometric_line():
    hw = -3.0
    d = Domain().add_polygon([(0, -12), (20, -12), (20, 0), (0, 0)],
                             edge_names=["bottom", "right", "top", "left"])  # fmt: skip
    d.add_polygon([(0, -6), (20, -6), (20, 0), (0, 0)], 2)
    mesh = unstructured_mesh(d, h=1.0)
    m1 = api.MaterialSpec.mohr_coulomb("a", 3e4, 0.3, 5.0, 30.0, gamma=18.0, gamma_sat=20.0)
    m2 = api.MaterialSpec.elastic("b", 5e4, 0.25, gamma=19.0, gamma_sat=21.0)

    def model(water):
        return api.Model(
            analysis=api.Analysis.PLANE_STRAIN,
            mesh=mesh,
            materials={"a": m1, "b": m2},
            region_material={1: "b", 2: "a"},
            fixities=(
                api.Fixity("bottom", True, True),
                api.Fixity("left", True, False),
                api.Fixity("right", True, False),
            ),
            initial=api.InitialStress("k0_field", water=water),
            stages=[api.Stage("load", water=water, loads=(api.EdgeLoad("top", qn=30.0),))],
        )

    piezo = api.run(model(api.WaterCondition.piezo([[0.0, hw]])))
    seep = api.run(model(api.WaterCondition.seepage({"left": hw, "right": hw, "bottom": hw})))
    for a, b in ((piezo.initial, seep.initial), (piezo.last, seep.last)):
        for tag in a.pore:
            scale = np.nanmax(a.pore[tag])
            assert np.nanmax(np.abs(a.pore[tag] - b.pore[tag])) < 1e-8 * scale
        assert np.abs(a.u - b.u).max() <= 1e-8 * max(np.abs(a.u).max(), 1e-12)
        assert np.abs(a.sig["soil"] - b.sig["soil"]).max() < 1e-8 * np.abs(a.sig["soil"]).max()
    assert np.allclose(seep.last.head[~np.isnan(seep.last.head)], hw)


def test_van_genuchten_limits():
    psi = np.array([1.0, 0.0, -0.01, -1.0, -100.0])
    kr = relative_conductivity(psi, 2.0, 3.0, 1e-4)
    assert kr[0] == kr[1] == 1.0
    assert np.all(np.diff(kr[1:]) < 0) and kr[-1] == 1e-4


def test_seepage_stage_roundtrip(tmp_path):
    """Seepage condition, hydraulic parameters, head and discharge survive JSON/HDF5."""
    T, H, k = 10.0, 4.0, 1e-5
    d = Domain().add_polygon([(-20, -T), (20, -T), (20, 0), (0, 0), (-20, 0)],
                             edge_names=["bottom", "right", "down", "up", "left"])  # fmt: skip
    d.add_line([(0, 0), (0, -5)], name="pile")
    mesh = insert_interface(unstructured_mesh(d, h=1.0), "pile", "pile")
    soil = api.MaterialSpec("s", "elastic", {"E": 3e4, "nu": 0.3}, 18.0, 20.0,
                            k_sat=(k, 0.5 * k), vg=(3.0, 2.5, 1e-5))  # fmt: skip
    model = api.Model(
        analysis=api.Analysis.PLANE_STRAIN, mesh=mesh, materials={"s": soil},
        region_material={1: "s"},
        fixities=(api.Fixity("bottom", True, True), api.Fixity("left", True, False),
                  api.Fixity("right", True, False)),
        initial=api.InitialStress("none"),
        stages=[api.Stage("flow", water=api.WaterCondition.seepage(
            {"up": H, "down": 0.0}, seepage_faces=["right"]))],
        interfaces={"pile": api.InterfaceSpec("pile", kn=1e6, ks=1e5)},
    )  # fmt: skip
    res = api.run(model)
    p = api.save_project(tmp_path / "flow.ssproj", model, res)
    proj = api.load_project(p)
    assert proj.model.materials["s"].vg == (3.0, 2.5, 1e-5)
    assert proj.model.stages[0].water == model.stages[0].water
    st = proj.results.last
    assert np.allclose(st.head, res.last.head, equal_nan=True)
    assert st.flow == res.last.flow
    assert np.allclose(api.run(proj.model).last.head, res.last.head, equal_nan=True)
