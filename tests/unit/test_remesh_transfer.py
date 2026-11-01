"""Re-meshing a drawing keeps the user's materials, stages and mesh-bound edits."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("shapely")

from slipsurface.fe2d import api
from slipsurface.fe2d.cad.geometry import BoundaryRule, Drawing, Entity
from slipsurface.fe2d.cad.supports import SupportAssignment
from slipsurface.fe2d.cad.transfer import transfer_model
from slipsurface.fe2d.gui.editing import put_interface, put_structure, remove_structure


def drawing(h=1.5, top=50.0, excavation=True):
    entities = [
        Entity("Soil", "region", ((0, 0), (12, 0), (12, 6), (0, 6))),
        Entity("Wall", "line", ((4, 6), (4, 2))),
    ]
    if excavation:
        entities.append(Entity("Pit", "region", ((7, 3), (10, 3), (10, 5), (7, 5)), 2))
    return Drawing(
        tuple(entities),
        (
            BoundaryRule("Soil:1", True, True),
            BoundaryRule("Soil:2", True),
            BoundaryRule("Soil:3", pressure=top),
            BoundaryRule("Soil:4", True),
        ),
        h=h,
        supports=(SupportAssignment("Wall", "pile"),),
    )


def user_model():
    model = drawing().build_model()
    clay = api.MaterialSpec.mohr_coulomb("clay", E=3e4, nu=0.3, c=8.0, phi=25.0, gamma=19.0)
    model = replace(
        model,
        materials={**model.materials, "clay": clay},
        region_material={1: "clay", 2: "clay"},
        initial=api.InitialStress("k0_field"),
        settings=api.SolverSettings(method="mNR", max_iter=40),
        stages=[
            replace(model.stages[0], name="Loading", loads=(*model.stages[0].loads,)),
            api.Stage(
                "Excavation",
                active_regions={1},
                active_structures={"cad_Wall"},
                loads=(api.EdgeLoad("Soil:3", qn=50.0), api.EdgeLoad("Soil:3", qn=5.0)),
                load_split=0.6,
            ),
        ],
    )
    model = put_interface(model, api.InterfaceSpec("joint", kn=1e6, ks=1e5, phi=20), "Wall:1")
    model = replace(
        model,
        stages=[
            replace(s, active_structures=s.active_structures | {"joint"}) for s in model.stages
        ],
    )
    node = int(np.argmin(np.hypot(*(model.mesh.coords - (12, 6)).T)))
    other = int(np.argmin(np.hypot(*(model.mesh.coords - (12, 3)).T)))
    return put_structure(model, api.BoltSpec("anchor", EA=1e5, T_yield=200.0), nodes=(node, other))


def test_remesh_keeps_materials_stages_and_structures():
    old = user_model()
    fresh = drawing(h=1.0, top=80.0).build_model()
    new, report = transfer_model(old, fresh)
    assert new.mesh.nn != old.mesh.nn
    assert new.region_material == {1: "clay", 2: "clay"}
    assert new.materials["clay"] == old.materials["clay"]
    assert new.initial.mode == "k0_field" and new.settings.method == "mNR"
    assert [s.name for s in new.stages] == ["Loading", "Excavation"]
    assert new.stages[1].active_regions == {1} and new.stages[1].load_split == 0.6
    # CAD pressure follows the drawing; the extra user load stays.
    assert [(ld.edge_set, ld.qn) for ld in new.stages[1].loads] == [
        ("Soil:3", 80.0),
        ("Soil:3", 5.0),
    ]
    assert new.stages[0].loads == (api.EdgeLoad("Soil:3", qn=80.0),)
    tags = new.structure_tags()
    assert tags["joint"] == "interface" and tags["anchor"] == "bar" and tags["cad_Wall"] == "beam"
    assert all({"joint", "cad_Wall"} <= s.active_structures for s in new.stages)
    assert [e["tag"] for e in new.geometry["mesh_edits"]] == ["joint", "anchor"]
    assert report == []
    elastic = api.MaterialSpec.elastic("clay", E=3e4, nu=0.3)
    stiff = api.InterfaceSpec("joint", kn=1e6, ks=1e5, c=1e4, sig_t=1e4)
    solvable = replace(
        new,
        materials={**new.materials, "clay": elastic},
        interfaces={**new.interfaces, "joint": stiff},
        initial=api.InitialStress("none"),
    )
    result = api.run(solvable)
    assert result.last.lam == pytest.approx(0.6)  # excavated nodes are NaN by design
    assert 0 < np.nanmax(np.abs(result.last.u)) < 1


def test_remesh_reports_what_cannot_be_carried():
    old = user_model()
    old = replace(
        old,
        stages=[*old.stages, api.Stage("Load", loads=(api.EdgeLoad("missing", 1.0),))],
    )
    fresh = replace(drawing(excavation=False), supports=()).build_model()
    new, report = transfer_model(old, fresh)
    assert new.region_material == {1: "clay"}
    assert new.stages[1].active_regions == {1}
    assert "cad_Wall" not in new.structure_tags()
    assert any("Region 2" in line for line in report)
    assert any("cad_Wall" in line for line in report)
    assert any("'missing'" in line for line in report)
    new.validate()


def test_new_region_and_support_start_active_and_removed_edit_is_not_replayed():
    old = remove_structure(user_model(), "anchor")
    assert [e["tag"] for e in old.geometry["mesh_edits"]] == ["joint"]
    base = drawing()
    extra = Entity("Nail", "line", ((1, 5), (3, 4)))
    fresh = replace(
        base,
        entities=(*base.entities, extra),
        supports=(*base.supports, SupportAssignment("Nail", "bolt")),
    ).build_model()
    new, _ = transfer_model(old, fresh)
    assert "anchor" not in new.structure_tags()
    assert all("cad_Nail" in s.active_structures for s in new.stages)


def test_no_previous_model_returns_fresh():
    fresh = drawing().build_model()
    assert transfer_model(None, fresh) == (fresh, [])


def test_axisymmetric_rejects_replayed_liner_without_losing_user_model():
    old = replace(
        user_model(),
        analysis=api.Analysis.AXISYMMETRIC,
        liners={
            "wall_liner": api.LinerSpec("wall_liner", E=3e7, nu=0.2, A=0.2, I=1e-3, As=0.167)
        },
    )
    old.geometry["mesh_edits"].append(
        {"kind": "liner", "tag": "wall_liner", "edge_set": "Soil:2"}
    )
    fresh = replace(drawing(h=1.0), supports=()).build_model()
    new, report = transfer_model(old, fresh)
    assert new.analysis is api.Analysis.AXISYMMETRIC
    assert "wall_liner" not in new.structure_tags()
    assert any("wall_liner" in line for line in report)
    assert new.region_material == {1: "clay", 2: "clay"}
    new.validate()
