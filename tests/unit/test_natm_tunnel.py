"""NATM tunnel designer, composite lining, bolt patterns and pile structural interfaces."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("shapely")

from slipsurface.fe2d.cad.geometry import Drawing, Entity
from slipsurface.fe2d.cad.supports import (
    SupportAssignment,
    companion_tags,
    owner_tag,
    pile_section,
)
from slipsurface.fe2d.cad.tunnel import (
    BlastDisturbance,
    BoltPattern,
    LiningSystem,
    SteelSet,
    TunnelDesign,
    TunnelSection,
    _stations,
    bolt_pattern_along,
    place_tunnel,
)


def ground(width=40.0, height=30.0):
    return replace(
        Drawing.example(),
        entities=(Entity("Zemin", "region", ((0, 0), (width, 0), (width, height), (0, height))),),
        h=2.5,
    )


def test_pile_section_follows_diameter_and_spacing():
    area, inertia = pile_section(1.0, 2.5)
    assert area == pytest.approx(np.pi / 4 / 2.5)
    assert inertia == pytest.approx(np.pi / 64 / 2.5)
    # Doubling the diameter multiplies the row inertia by 16, halving the spacing by 2.
    assert pile_section(2.0, 2.5)[1] == pytest.approx(16 * inertia)
    assert pile_section(1.0, 1.25)[1] == pytest.approx(2 * inertia)
    with pytest.raises(ValueError):
        pile_section(0.0, 2.0)


def test_pile_is_a_structural_interface_with_skin_strength():
    pile = SupportAssignment("K", "pile", dict(D=1.2, spacing=3.0, T_skin=300.0))
    spec = pile.spec()
    area, inertia = pile_section(1.2, 3.0)
    assert (spec.A, spec.I, spec.As) == pytest.approx((area, inertia, 0.9 * area))
    faces = pile.interface_specs()
    assert [f.name for f in faces] == list(companion_tags("cad_K")) == ["cad_K_ifL", "cad_K_ifR"]
    assert all(f.c == pytest.approx(300.0 / 6.0) for f in faces)
    assert owner_tag("cad_K_ifR") == "cad_K" and owner_tag("cad_K") == "cad_K"
    assert not SupportAssignment("K", "pile", dict(interface=0.0)).interface_specs()
    legacy = SupportAssignment("K", "pile", dict(E=3e7, nu=0.2, A=0.4, I=0.02, As=0.3,
                                                 unit_weight=24.0))  # fmt: skip
    assert legacy.spec().A == 0.4 and not legacy.has_interface


def test_pile_interfaces_mesh_and_activate_with_the_pile():
    drawing = replace(
        ground(12, 6),
        entities=(*ground(12, 6).entities, Entity("Kazik", "line", ((6, 1), (6, 5)))),
        supports=(SupportAssignment("Kazik", "pile"),),
        h=1.0,
    )
    model = drawing.build_model()
    assert {"cad_Kazik_ifL", "cad_Kazik_ifR"} <= set(model.interfaces)
    assert model.initial.active_structures == frozenset()
    assert {"cad_Kazik", "cad_Kazik_ifL", "cad_Kazik_ifR"} <= model.stages[0].active_structures


def test_bolt_count_follows_circumferential_spacing():
    pattern = BoltPattern(spacing=1.5)
    assert pattern.count_on_length(9.0) == 6
    assert pattern.count_on_length(0.0) == 0
    assert BoltPattern(count=5, spacing=99.0).count_on_length(9.0) == 5


def test_spacing_stations_fill_the_chain_equally():
    s = _stations(10.0, 2.0)
    assert len(s) == 5
    np.testing.assert_allclose(np.diff(s), s[1] - s[0])
    assert s[0] == pytest.approx(1.0)
    assert s[-1] == pytest.approx(9.0)
    explicit = _stations(6.0, 99.0, count=3, margin=1.0)
    np.testing.assert_allclose(explicit, [1.0, 3.0, 5.0])


def test_tunnel_bolts_are_equally_spaced_along_the_lining():
    design = TunnelDesign(
        TunnelSection(
            radius=4.0,
            wall_radius=7.0,
            wall_height=1.5,
            invert_level=-1.5,
            parts=1,
            segments=48,
        ),
        LiningSystem(rib="Yok"),
        BoltPattern(spacing=1.5, length=3.0),
    )
    drawing = place_tunnel(ground(), design, (20.0, 15.0))
    bolts = [e for e in drawing.entities if e.name.startswith("Tunel_Bulon")]
    assert len(bolts) >= 8
    heads = np.array([e.points[0] for e in bolts])
    liners = [e for e in drawing.entities if e.name.startswith("Tunel_PB")]
    liner_pts = {tuple(np.round(p, 6)) for e in liners for p in e.points}
    assert all(tuple(np.round(h, 6)) in liner_pts for h in heads)
    for liner in liners:
        pts = np.asarray(liner.points, float)
        station = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
        )
        on_this = []
        for h in heads:
            dist = np.linalg.norm(pts - h, axis=1)
            if dist.min() < 1e-6:
                on_this.append(station[int(dist.argmin())])
        on_this = np.sort(on_this)
        if len(on_this) < 3:
            continue
        gaps = np.diff(on_this)
        assert gaps.std() / gaps.mean() < 0.05, gaps


def test_place_tunnel_adds_bench_invert_bolts_and_steel_sets():
    design = TunnelDesign(
        TunnelSection(radius=4.0, wall_radius=7.0, wall_height=1.5, invert_level=-1.5),
        LiningSystem(rib="Yok"),
        BoltPattern(spacing=1.5, length=3.0),
        bench_bolts=BoltPattern(spacing=2.0, length=3.0),
        invert_bolts=BoltPattern(spacing=1.8, length=2.5),
        steel=SteelSet(rib="HEB 140", spacing=0.8),
    )
    drawing = place_tunnel(ground(), design, (20.0, 15.0))
    names = {e.name for e in drawing.entities}
    bolts = [e for e in drawing.entities if e.name.startswith("Tunel_Bulon")]
    assert len(bolts) >= 6
    assert any("PB_Ust" in n for n in names)
    liner = next(s for s in drawing.supports if s.kind == "liner")
    combined = LiningSystem(rib="Yok").with_steel(SteelSet(rib="HEB 140", spacing=0.8))
    assert liner.properties["A"] == pytest.approx(combined.liner_properties()["A"])
    assert TunnelDesign.from_dict(design.to_dict()) == design


def test_steel_only_liner_uses_rib_spacing():
    steel = SteelSet(rib="HEB 140", spacing=1.0)
    double = SteelSet(rib="HEB 140", spacing=2.0)
    assert steel.liner_properties()["A"] == pytest.approx(2 * double.liner_properties()["A"])
    design = TunnelDesign(
        TunnelSection(radius=4.0, wall_radius=7.0, wall_height=1.5, invert_level=-1.5, parts=1),
        None,
        None,
        steel=steel,
    )
    drawing = place_tunnel(ground(), design, (20.0, 15.0))
    assert any(e.name.startswith("Tunel_Iksa") for e in drawing.entities)


def test_blast_disturbance_halo_is_applied_on_the_stage_after_the_blast():
    from shapely.geometry import Polygon

    design = TunnelDesign(
        TunnelSection(radius=4.0, wall_radius=7.0, wall_height=1.5, invert_level=-1.5),
        LiningSystem(),
        None,
        disturbance=BlastDisturbance(0.8, 2.0),
    )
    drawing = place_tunnel(ground(), design, (20.0, 15.0))
    halo = next(e for e in drawing.entities if e.name.endswith("_Orselenme"))
    assert drawing.sequence[0].excavate and not drawing.sequence[0].disturb
    assert drawing.sequence[1].disturb == (halo.name,)
    assert drawing.disturbance["D"] == pytest.approx(0.8)
    assert Polygon(halo.points).area > Polygon(design.section.outline()).area


def test_lining_stiffness_combines_shotcrete_mesh_and_ribs():
    plain = LiningSystem(thickness=0.3, E_shotcrete=2e7, mesh="Q131", rib="Yok")
    EA, EI = plain.stiffness()
    As = 1.31e-4
    assert EA == pytest.approx(2e7 * 0.3 + 2.1e8 * As)
    assert EI == pytest.approx(2e7 * 0.3**3 / 12)
    ribbed = replace(plain, rib="Özel", rib_area=50.0, rib_inertia=4000.0, rib_spacing=1.0)
    assert ribbed.stiffness()[0] == pytest.approx(EA + 2.1e8 * 50e-4)
    assert ribbed.stiffness()[1] == pytest.approx(EI + 2.1e8 * 4000e-8)
    props = ribbed.liner_properties()
    assert props["E"] * props["I"] == pytest.approx(ribbed.stiffness()[1])
    with pytest.raises(ValueError):
        LiningSystem(mesh="yok-boyle-hasir")


@pytest.mark.parametrize(("shape", "parts"), [("natm", 3), ("natm", 2), ("natm", 1), ("circle", 3)])
def test_section_splits_into_heading_bench_invert(shape, parts):
    section = TunnelSection(shape=shape, parts=parts, radius=4.0, wall_radius=7.0,
                            wall_height=1.5, invert_level=-1.5)  # fmt: skip
    pieces = section.parts_at((20.0, 15.0))
    assert list(pieces) == section.part_names()
    from shapely.geometry import Polygon

    total = sum(Polygon(p).area for p in pieces.values())
    assert total == pytest.approx(Polygon(section.outline()).area, rel=1e-6)
    centroids = [Polygon(p).centroid.y for p in pieces.values()]
    assert centroids == sorted(centroids, reverse=True)


def test_place_tunnel_builds_staged_natm_sequence():
    design = TunnelDesign(
        TunnelSection(radius=4.0, wall_radius=7.0, wall_height=1.5, invert_level=-1.5),
        LiningSystem(),
        BoltPattern(count=5, length=3.0),
        load_split=0.4,
    )
    drawing = place_tunnel(ground(), design, (20.0, 15.0))
    names = {e.name for e in drawing.entities}
    assert {"Tunel_Ust", "Tunel_Alt", "Tunel_Inv", "Tunel_PB_Ust", "Tunel_PB_Inv"} <= names
    assert {"Tunel_PB_Alt_Sol", "Tunel_PB_Alt_Sag"} <= names
    assert sum(n.startswith("Tunel_Bulon") for n in names) == 5
    assert all(not s.active for s in drawing.supports)
    steps = drawing.sequence
    assert [s.name for s in steps][:2] == ["Tunel Üst yarı kazı", "Tunel Üst yarı destek"]
    assert len(steps) == 6
    assert steps[0].load_split == 0.4 and steps[0].excavate == ("Tunel_Ust",)
    assert "Tunel_PB_Ust" in steps[1].install
    # A second tunnel gets unique names and appends its own steps.
    twin = place_tunnel(drawing, replace(design, bolts=None), (20.0, 5.0))
    assert {"Tunel2_Ust", "Tunel2_PB_Ust"} <= {e.name for e in twin.entities}
    assert len(twin.sequence) == 12
    assert TunnelDesign.from_dict(design.to_dict()) == design


def test_tunnel_sequence_becomes_cumulative_fe_stages():
    design = TunnelDesign(
        TunnelSection(radius=3.0, wall_radius=6.0, wall_height=1.0, invert_level=-1.0),
        LiningSystem(),
        BoltPattern(count=3, length=2.5),
    )
    model = place_tunnel(ground(30, 24), design, (15.0, 12.0)).build_model()
    assert len(model.stages) == 1 + 6
    regions = model.mesh.regions()
    active = [s.active_regions for s in model.stages[1:]]
    assert all(b <= a for a, b in zip(active, active[1:]))
    assert len(regions - active[-1]) == 3
    installed = [s.active_structures for s in model.stages[1:]]
    assert not installed[0] and "cad_Tunel_PB_Ust" in installed[1]
    assert all(a <= b for a, b in zip(installed, installed[1:]))
    assert model.stages[1].load_split == pytest.approx(0.5)


def test_bolt_pattern_along_a_wall_inserts_conforming_heads():
    drawing = replace(
        ground(12, 8),
        entities=(*ground(12, 8).entities, Entity("Duvar", "line", ((4, 1), (4, 7)))),
    )
    out = bolt_pattern_along(drawing, "Duvar", 3, 2.0, angle=-90.0, margin=1.0)
    bolts = [e for e in out.entities if e.name.startswith("Bulon_Duvar")]
    assert len(bolts) == 3 and len(out.supports) == 3
    heads = sorted(b.points[0][1] for b in bolts)
    assert heads == pytest.approx([2.0, 4.0, 6.0])
    host = next(e for e in out.entities if e.name == "Duvar")
    assert {(4.0, 2.0), (4.0, 4.0), (4.0, 6.0)} <= set(map(tuple, host.points))
    # Turned clockwise from an upward wall the bolts point to +x.
    assert all(b.points[1][0] == pytest.approx(6.0) for b in bolts)
    spaced = bolt_pattern_along(drawing, "Duvar", 0, 2.0, angle=-90.0, margin=0.0, spacing=2.0)
    assert len([e for e in spaced.entities if e.name.startswith("Bulon_Duvar")]) == 3
    with pytest.raises(ValueError):
        bolt_pattern_along(drawing, "Duvar", 2, 0.0)


def test_library_persists_designs_between_sessions(qt_app):
    from slipsurface.fe2d.gui.tunnel_designer import library, library_remove, library_store

    design = TunnelDesign(TunnelSection(name="T1", radius=5.5))
    library_store("tunnels", "T1", design.to_dict())
    assert TunnelDesign.from_dict(library("tunnels")["T1"]).section.radius == 5.5
    library_remove("tunnels", "T1")
    assert "T1" not in library("tunnels")


def test_designer_dialogs_round_trip(qt_app):
    from slipsurface.fe2d.gui.tunnel_designer import (
        BoltPatternDialog,
        LiningDesignerDialog,
        TunnelDesignerDialog,
    )

    tunnel = TunnelDesignerDialog()
    design = tunnel.design()
    assert isinstance(design, TunnelDesign) and design.section.parts == 3
    assert design.bolts is not None and design.bolts.count == 0
    tunnel.bench_bolts.use.setChecked(True)
    tunnel.invert_bolts.use.setChecked(True)
    tunnel.use_steel.setChecked(True)
    tunnel.rib_spacing.setValue(0.75)
    tunnel.use_disturbance.setChecked(True)
    design = tunnel.design()
    assert design.bench_bolts is not None and design.invert_bolts is not None
    assert design.steel is not None and design.steel.spacing == pytest.approx(0.75)
    assert design.disturbance is not None and design.disturbance.D == pytest.approx(0.8)
    lining = LiningDesignerDialog()
    assert isinstance(lining.lining(), LiningSystem)
    bolts = BoltPatternDialog("Duvar", chain_length=6.0)
    assert isinstance(bolts.pattern(), BoltPattern) and bolts.pattern().count == 0
    for dialog in (tunnel, lining, bolts):
        dialog.deleteLater()
