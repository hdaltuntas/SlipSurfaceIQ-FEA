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
        Entity("Zemin", "region", ((0, 0), (12, 0), (12, 6), (0, 6))),
        Entity("Duvar", "line", ((4, 6), (4, 2))),
    ]
    if excavation:
        entities.append(Entity("Kazi", "region", ((7, 3), (10, 3), (10, 5), (7, 5)), 2))
    return Drawing(
        tuple(entities),
        (
            BoundaryRule("Zemin:1", True, True),
            BoundaryRule("Zemin:2", True),
            BoundaryRule("Zemin:3", pressure=top),
            BoundaryRule("Zemin:4", True),
        ),
        h=h,
        supports=(SupportAssignment("Duvar", "pile"),),
    )


def user_model():
    model = drawing().build_model()
    clay = api.MaterialSpec.mohr_coulomb("kil", E=3e4, nu=0.3, c=8.0, phi=25.0, gamma=19.0)
    model = replace(
        model,
        materials={**model.materials, "kil": clay},
        region_material={1: "kil", 2: "kil"},
        initial=api.InitialStress("k0_field"),
        settings=api.SolverSettings(method="mNR", max_iter=40),
        stages=[
            replace(model.stages[0], name="Yükleme", loads=(*model.stages[0].loads,)),
            api.Stage(
                "Kazı",
                active_regions={1},
                active_structures={"cad_Duvar"},
                loads=(api.EdgeLoad("Zemin:3", qn=50.0), api.EdgeLoad("Zemin:3", qn=5.0)),
                load_split=0.6,
            ),
        ],
    )
    model = put_interface(model, api.InterfaceSpec("ara", kn=1e6, ks=1e5, phi=20), "Duvar:1")
    model = replace(
        model,
        stages=[replace(s, active_structures=s.active_structures | {"ara"}) for s in model.stages],
    )
    node = int(np.argmin(np.hypot(*(model.mesh.coords - (12, 6)).T)))
    other = int(np.argmin(np.hypot(*(model.mesh.coords - (12, 3)).T)))
    return put_structure(model, api.BoltSpec("ankraj", EA=1e5, T_yield=200.0), nodes=(node, other))


def test_remesh_keeps_materials_stages_and_structures():
    old = user_model()
    fresh = drawing(h=1.0, top=80.0).build_model()
    new, report = transfer_model(old, fresh)
    assert new.mesh.nn != old.mesh.nn
    assert new.region_material == {1: "kil", 2: "kil"}
    assert new.materials["kil"] == old.materials["kil"]
    assert new.initial.mode == "k0_field" and new.settings.method == "mNR"
    assert [s.name for s in new.stages] == ["Yükleme", "Kazı"]
    assert new.stages[1].active_regions == {1} and new.stages[1].load_split == 0.6
    # CAD pressure follows the drawing; the extra user load stays.
    assert [(ld.edge_set, ld.qn) for ld in new.stages[1].loads] == [
        ("Zemin:3", 80.0),
        ("Zemin:3", 5.0),
    ]
    assert new.stages[0].loads == (api.EdgeLoad("Zemin:3", qn=80.0),)
    tags = new.structure_tags()
    assert tags["ara"] == "interface" and tags["ankraj"] == "bar" and tags["cad_Duvar"] == "beam"
    assert all({"ara", "cad_Duvar"} <= s.active_structures for s in new.stages)
    assert [e["tag"] for e in new.geometry["mesh_edits"]] == ["ara", "ankraj"]
    assert report == []
    elastic = api.MaterialSpec.elastic("kil", E=3e4, nu=0.3)
    stiff = api.InterfaceSpec("ara", kn=1e6, ks=1e5, c=1e4, sig_t=1e4)
    solvable = replace(
        new,
        materials={**new.materials, "kil": elastic},
        interfaces={"ara": stiff},
        initial=api.InitialStress("none"),
    )
    result = api.run(solvable)
    assert result.last.lam == pytest.approx(0.6)  # excavated nodes are NaN by design
    assert 0 < np.nanmax(np.abs(result.last.u)) < 1


def test_remesh_reports_what_cannot_be_carried():
    old = user_model()
    old = replace(old, stages=[*old.stages, api.Stage("Yük", loads=(api.EdgeLoad("yok", 1.0),))])
    fresh = replace(drawing(excavation=False), supports=()).build_model()
    new, report = transfer_model(old, fresh)
    assert new.region_material == {1: "kil"}
    assert new.stages[1].active_regions == {1}
    assert "cad_Duvar" not in new.structure_tags()
    assert any("Bölge 2" in line for line in report)
    assert any("cad_Duvar" in line for line in report)
    assert any("'yok'" in line for line in report)
    new.validate()


def test_new_region_and_support_start_active_and_removed_edit_is_not_replayed():
    old = remove_structure(user_model(), "ankraj")
    assert [e["tag"] for e in old.geometry["mesh_edits"]] == ["ara"]
    base = drawing()
    extra = Entity("Civi", "line", ((1, 5), (3, 4)))
    fresh = replace(
        base,
        entities=(*base.entities, extra),
        supports=(*base.supports, SupportAssignment("Civi", "bolt")),
    ).build_model()
    new, _ = transfer_model(old, fresh)
    assert "ankraj" not in new.structure_tags()
    assert all("cad_Civi" in s.active_structures for s in new.stages)


def test_no_previous_model_returns_fresh():
    fresh = drawing().build_model()
    assert transfer_model(None, fresh) == (fresh, [])


def test_axisymmetric_rejects_replayed_liner_without_losing_user_model():
    old = replace(
        user_model(),
        analysis=api.Analysis.AXISYMMETRIC,
        liners={
            "duvar_liner": api.LinerSpec("duvar_liner", E=3e7, nu=0.2, A=0.2, I=1e-3, As=0.167)
        },
    )
    old.geometry["mesh_edits"].append(
        {"kind": "liner", "tag": "duvar_liner", "edge_set": "Zemin:2"}
    )
    fresh = replace(drawing(h=1.0), supports=()).build_model()
    new, report = transfer_model(old, fresh)
    assert new.analysis is api.Analysis.AXISYMMETRIC
    assert "duvar_liner" not in new.structure_tags()
    assert any("duvar_liner" in line for line in report)
    assert new.region_material == {1: "kil", 2: "kil"}
    new.validate()
