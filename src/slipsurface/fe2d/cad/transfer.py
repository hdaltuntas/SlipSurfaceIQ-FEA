"""Carry user model definitions from a previous mesh onto a freshly meshed drawing.

The drawing stays authoritative for what it defines (regions, CAD supports, CAD
mesnet/pressure rules). Everything else is matched by name: materials and region
assignments, initial stress, solver settings, stages (loads, water, activation,
material overrides), extra fixities and the structures/interfaces added to the old
mesh by the advanced editors (replayed from ``geometry["mesh_edits"]``). Point loads
and node-anchored bolts move to the nearest new node. Anything whose target no longer
exists is dropped and listed in the returned report; results are never transferred.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .. import api
from ..mesh.structures import add_bar, add_bars_along, add_beams, insert_interface, nearest_node
from .geometry import Drawing


def record_mesh_edit(model, edit):
    """Remember how a structure/interface was added so a later remesh can replay it."""
    if not model.geometry:
        return model
    edits = [e for e in model.geometry.get("mesh_edits", []) if e["tag"] != edit["tag"]]
    return replace(model, geometry={**model.geometry, "mesh_edits": [*edits, edit]})


def forget_mesh_edit(model, tag):
    if not model.geometry or "mesh_edits" not in model.geometry:
        return model
    edits = [e for e in model.geometry["mesh_edits"] if e["tag"] != tag]
    return replace(model, geometry={**model.geometry, "mesh_edits": edits})


def _drawing(model):
    try:
        return Drawing.from_dict(model.geometry) if model.geometry else Drawing()
    except (KeyError, TypeError, ValueError):
        return Drawing()


def transfer_model(previous, fresh):
    """Return ``(model, report)``: ``fresh`` with the user definitions of ``previous``."""
    if previous is None:
        return fresh, []
    report = []
    old_mesh, mesh = previous.mesh, fresh.mesh
    old_drawing, new_drawing = _drawing(previous), _drawing(fresh)
    old_rules = {r.edge: r for r in old_drawing.rules}
    new_rules = {r.edge: r for r in new_drawing.rules}
    old_assign = {s.tag: s for s in old_drawing.supports}
    new_assign = {s.tag: s for s in new_drawing.supports}

    def moved_node(node, what):
        xy = old_mesh.coords[node]
        new = nearest_node(mesh, *xy)
        distance = float(np.linalg.norm(mesh.coords[new] - xy))
        if distance > 1e-9:
            report.append(f"{what}: en yakın düğüme taşındı ({distance:.3g} m).")
        return new

    # Advanced-editor structures/interfaces, replayed in their original order.
    model = replace(fresh, analysis=previous.analysis)
    edits = []
    for edit in (previous.geometry or {}).get("mesh_edits", []):
        tag = edit["tag"]
        spec = previous.liners.get(tag) or previous.bolts.get(tag) or previous.interfaces.get(tag)
        if spec is None:
            continue
        try:
            model = _replay(model, edit, spec, report)
        except Exception as exc:  # noqa: BLE001 - every failure is reported, not fatal
            report.append(f"{tag}: yeni ağa aktarılamadı ({exc}).")
        else:
            edits.append(edit)
    mesh = model.mesh
    for tag in previous.structure_tags():
        if not tag.startswith("cad_") and tag not in model.structure_tags():
            if not any(e["tag"] == tag for e in (previous.geometry or {}).get("mesh_edits", [])):
                report.append(f"{tag}: ağ kenarına bağlı kaydı yok; yeniden tanımlayın.")
    for tag in old_assign.keys() - new_assign.keys():
        report.append(f"{tag}: çizimden kaldırılan destek modelden de çıkarıldı.")

    regions = mesh.regions()
    old_regions = old_mesh.regions()
    structures = set(model.structure_tags())

    def keep_set(name, sets, what):
        if name in sets:
            return True
        report.append(f"{what} '{name}': küme yeni ağda yok, çıkarıldı.")
        return False

    # Materials: the library survives; a region keeps its old material where it exists.
    region_material = {
        r: previous.region_material.get(r, fresh.region_material[r]) for r in sorted(regions)
    }
    materials = {
        **{k: v for k, v in fresh.materials.items() if k in region_material.values()},
        **previous.materials,
    }
    for r in sorted(old_regions - regions):
        report.append(f"Bölge {r}: yeni çizimde yok; malzeme ataması çıkarıldı.")

    # Fixities: drawing rules decide their own edges, other named sets are kept.
    ruled = {e for e, r in {**old_rules, **new_rules}.items() if r.ux or r.uy}
    fixities = list(fresh.fixities) + [
        f
        for f in previous.fixities
        if f.node_set not in ruled and keep_set(f.node_set, mesh.node_sets, "Mesnet")
    ]
    displacements = tuple(
        d for d in previous.displacements if keep_set(d.node_set, mesh.node_sets, "Yer değiştirme")
    )

    def stage_structures(old_active):
        out = set()
        for tag in structures:
            assignment = new_assign.get(tag)
            previous_assignment = old_assign.get(tag)
            if tag not in previous.structure_tags() or (
                assignment
                and previous_assignment
                and assignment.active != previous_assignment.active
            ):
                if assignment is None or assignment.active:
                    out.add(tag)
            elif tag in old_active:
                out.add(tag)
        return frozenset(out)

    def stage_regions(active):
        if active is None:
            return None
        return frozenset((set(active) & regions) | (regions - old_regions))

    def water(w, what):
        if w.mode != "seepage":
            return w
        return replace(
            w,
            head_bcs=tuple(b for b in w.head_bcs if keep_set(b.node_set, mesh.node_sets, what)),
            flux_bcs=tuple(b for b in w.flux_bcs if keep_set(b.edge_set, mesh.edge_sets, what)),
            seepage_faces=tuple(
                f
                for f in w.seepage_faces
                if f in mesh.edge_sets or keep_set(f, mesh.node_sets, what)
            ),
        )

    def is_cad_load(load):
        rule = old_rules.get(getattr(load, "edge_set", None))
        return rule is not None and rule.pressure and load.qn == rule.pressure and not load.qt

    cad_loads = {e: r.pressure for e, r in new_rules.items() if r.pressure}
    placed = set()
    stages = []
    for stage in previous.stages:
        loads = []
        for load in stage.loads:
            if isinstance(load, api.PointLoad):
                loads.append(replace(load, node=moved_node(load.node, f"{stage.name} nokta yükü")))
            elif is_cad_load(load):
                if load.edge_set in cad_loads:
                    loads.append(replace(load, qn=cad_loads[load.edge_set]))
                    placed.add(load.edge_set)
            elif keep_set(load.edge_set, mesh.edge_sets, f"{stage.name} kenar yükü"):
                loads.append(load)
        stages.append(
            replace(
                stage,
                active_regions=stage_regions(stage.active_regions),
                active_structures=stage_structures(stage.active_structures),
                material_override={
                    r: m for r, m in stage.material_override.items() if r in regions
                },
                loads=tuple(loads),
                water=water(stage.water, f"{stage.name} su sınırı"),
                displacements=tuple(
                    d
                    for d in stage.displacements
                    if keep_set(d.node_set, mesh.node_sets, f"{stage.name} yer değiştirme")
                ),
            )
        )
    if not stages:
        stages = list(fresh.stages)
        placed.update(cad_loads)
    extra = [api.EdgeLoad(e, qn=q) for e, q in cad_loads.items() if e not in placed]
    if extra:
        stages[0] = replace(stages[0], loads=(*stages[0].loads, *extra))

    initial = previous.initial
    initial = replace(
        initial,
        active_regions=stage_regions(initial.active_regions),
        active_structures=None
        if initial.active_structures is None
        else frozenset(initial.active_structures & structures),
        water=water(initial.water, "Başlangıç su sınırı"),
    )
    geometry = dict(fresh.geometry or {})
    if edits:
        geometry["mesh_edits"] = edits
    result = replace(
        model,
        analysis=previous.analysis,
        materials=materials,
        region_material=region_material,
        fixities=tuple(fixities),
        displacements=displacements,
        initial=initial,
        stages=stages,
        settings=previous.settings,
        geometry=geometry,
    )
    result.validate()
    return result, list(dict.fromkeys(report))


def _replay(model, edit, spec, report):
    tag = edit["tag"]
    if tag in model.structure_tags():
        raise ValueError("ad yeni çizimde kullanılıyor")
    if edit["kind"] == "interface":
        mesh = insert_interface(model.mesh, edit["edge_set"], tag, edit.get("side", "left"))
        model = replace(model, mesh=mesh, interfaces={**model.interfaces, tag: spec})
    elif "points" in edit:
        a, b = (nearest_node(model.mesh, *xy) for xy in edit["points"])
        for xy, n in zip(edit["points"], (a, b)):
            d = float(np.linalg.norm(model.mesh.coords[n] - xy))
            if d > 1e-9:
                report.append(f"{tag}: uç en yakın düğüme taşındı ({d:.3g} m).")
        mesh = add_bar(model.mesh, a, b, tag)
        model = replace(model, mesh=mesh, bolts={**model.bolts, tag: spec})
    elif edit["kind"] == "liner":
        if model.analysis is not api.Analysis.PLANE_STRAIN:
            raise ValueError("liner/kiriş yalnız düzlem şekil değiştirmede kullanılabilir")
        mesh = add_beams(model.mesh, edit["edge_set"], tag)
        model = replace(model, mesh=mesh, liners={**model.liners, tag: spec})
    else:
        mesh = add_bars_along(model.mesh, edit["edge_set"], tag)
        model = replace(model, mesh=mesh, bolts={**model.bolts, tag: spec})
    if not model.mesh.block(tag).ne:
        raise ValueError("kenar kümesi boş")
    return model
