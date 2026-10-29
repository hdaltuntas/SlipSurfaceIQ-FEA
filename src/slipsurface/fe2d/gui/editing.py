"""Qt-independent, transactional editing operations used by the desktop forms."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import numpy as np

from .. import api
from ..cad.transfer import forget_mesh_edit, record_mesh_edit
from ..fem.materials import build
from ..mesh.structures import add_bar, add_bars_along, add_beams


def validate_edit(model):
    model.validate()
    for spec in model.materials.values():
        build(spec)
    names = [s.name.strip() for s in model.stages]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Aşama adları boş olamaz ve benzersiz olmalıdır.")
    if model.geometry and model.geometry.get("supports"):
        # Keep CAD-linked definitions in step with advanced mesh property edits/deletions.
        assignments = []
        for assignment in model.geometry["supports"]:
            tag = f"cad_{assignment['entity']}"
            spec = model.liners.get(tag) or model.bolts.get(tag)
            if spec is not None:
                # Pile rows keep D/spacing/interface keys the beam spec does not carry.
                properties = {
                    key: getattr(spec, key, value)
                    for key, value in assignment["properties"].items()
                }
                assignments.append({**assignment, "properties": properties})
        model = replace(model, geometry={**model.geometry, "supports": assignments})
    return model


def put_material(model, spec, old_name=None):
    """Rename references together; fail before touching the input model."""
    build(spec)
    if spec.name != old_name and spec.name in model.materials:
        raise ValueError("Bu malzeme adı zaten kullanılıyor.")
    mats = dict(model.materials)
    if old_name is not None:
        del mats[old_name]
    mats[spec.name] = spec

    def rename(n):
        return spec.name if n == old_name else n

    return validate_edit(
        replace(
            model,
            materials=mats,
            region_material={r: rename(n) for r, n in model.region_material.items()},
            stages=[
                replace(s, material_override={r: rename(n) for r, n in s.material_override.items()})
                for s in model.stages
            ],
        )
    )


def remove_material(model, name):
    used = set(model.region_material.values())
    used.update(n for s in model.stages for n in s.material_override.values())
    if name in used:
        raise ValueError(
            "Malzeme bölge/aşama tarafından kullanılıyor; önce atamalarını değiştirin."
        )
    return validate_edit(
        replace(model, materials={k: v for k, v in model.materials.items() if k != name})
    )


def put_structure(model, spec, *, edge_set=None, nodes=None):
    if spec.name in model.structure_tags() or any(b.tag == spec.name for b in model.mesh.blocks):
        raise ValueError("Bu yapı/blok adı zaten kullanılıyor.")
    if not spec.name.strip() or "," in spec.name or spec.name == "auto":
        raise ValueError("Yapı adı boş, virgül içeren veya ayrılmış auto adı olamaz.")
    if isinstance(spec, api.LinerSpec):
        if model.analysis is not api.Analysis.PLANE_STRAIN:
            raise ValueError("Liner/kiriş yalnız düzlem şekil değiştirmede kullanılabilir.")
        mesh = add_beams(model.mesh, edge_set, spec.name)
        result = replace(model, mesh=mesh, liners={**model.liners, spec.name: spec})
        edit = {"kind": "liner", "tag": spec.name, "edge_set": edge_set}
    else:
        if nodes is None:
            mesh = add_bars_along(model.mesh, edge_set, spec.name)
            edit = {"kind": "bolt", "tag": spec.name, "edge_set": edge_set}
        else:
            a, b = map(int, nodes)
            if not (0 <= a < model.mesh.nn and 0 <= b < model.mesh.nn):
                raise ValueError("Bolt uç düğümü ağ dışında.")
            if np.linalg.norm(model.mesh.coords[a] - model.mesh.coords[b]) <= 1e-12:
                raise ValueError("Bolt uçları farklı konumlarda olmalıdır.")
            mesh = add_bar(model.mesh, a, b, spec.name)
            points = [model.mesh.coords[n].tolist() for n in (a, b)]
            edit = {"kind": "bolt", "tag": spec.name, "points": points}
        result = replace(model, mesh=mesh, bolts={**model.bolts, spec.name: spec})
    block = mesh.block(spec.name)
    if not block.ne:
        raise ValueError("Seçilen kenar kümesi boş.")
    if np.any(
        np.linalg.norm(mesh.coords[block.conn[:, 1]] - mesh.coords[block.conn[:, 0]], axis=1)
        <= 1e-12
    ):
        raise ValueError("Yapı sıfır uzunluklu eleman içeriyor.")
    return validate_edit(record_mesh_edit(result, edit))


def remove_structure(model, tag):
    if model.structure_tags()[tag] == "interface":
        raise ValueError("Ara yüz silme düğüm birleştirmesi gerektirir; bu formda desteklenmiyor.")
    mesh = api.Mesh(
        model.mesh.coords,
        tuple(b for b in model.mesh.blocks if b.tag != tag),
        model.mesh.node_sets,
        model.mesh.edge_sets,
    )
    init = model.initial
    if init.active_structures is not None:
        init = replace(init, active_structures=init.active_structures - {tag})
    return validate_edit(
        replace(
            forget_mesh_edit(model, tag),
            mesh=mesh,
            initial=init,
            liners={k: v for k, v in model.liners.items() if k != tag},
            bolts={k: v for k, v in model.bolts.items() if k != tag},
            stages=[
                replace(s, active_structures=s.active_structures - {tag}) for s in model.stages
            ],
        )
    )


def regions_text(regions):
    if regions is None:
        return ""
    return ",".join(map(str, sorted(regions))) if regions else "-"


def parse_regions(text):
    text = text.strip()
    if not text:
        return None
    if text == "-":
        return frozenset()
    return frozenset(int(n.strip()) for n in text.split(","))


def parse_tags(text):
    return frozenset(n.strip() for n in text.split(",") if n.strip())


def region_names(model) -> dict[int, str]:
    """Map region id -> CAD entity name when CAD geometry metadata is present."""
    out: dict[int, str] = {}
    if model is not None and model.geometry:
        for ent in model.geometry.get("entities", ()):
            if ent.get("kind") == "region":
                r = int(ent.get("region", 1))
                name = str(ent.get("name", "")).strip()
                if name:
                    out[r] = name
    return out


def region_label(model, region: int) -> str:
    names = region_names(model)
    name = names.get(int(region))
    return f"Bölge {region} ({name})" if name else f"Bölge {region}"


def structure_label(model, tag: str) -> str:
    kind_map = {"beam": "Kazık/Kaplama", "bar": "Ankraj/Çivi", "interface": "Ara yüz"}
    kind = (model.structure_tags().get(tag) if model is not None else None) or ""
    if model is not None and model.geometry:
        for sup in model.geometry.get("supports", ()):
            ent = sup.get("entity", "")
            if f"cad_{ent}" == tag:
                sk = {"pile": "Kazık", "liner": "Kaplama", "bolt": "Ankraj/Çivi"}.get(
                    sup.get("kind"), kind_map.get(kind, "Destek")
                )
                return f"{ent} ({sk})"
    clean = tag[4:] if tag.startswith("cad_") else tag
    suffix = kind_map.get(kind)
    return f"{clean} ({suffix})" if suffix else clean


def stage_active_regions(model, stage_index: int) -> frozenset[int]:
    all_regions = frozenset(model.mesh.regions())
    if stage_index <= 0 or not model.stages:
        active = model.initial.active_regions
    else:
        idx = min(stage_index - 1, len(model.stages) - 1)
        active = model.stages[idx].active_regions
    return all_regions if active is None else frozenset(active)


def stage_active_structures(model, stage_index: int) -> frozenset[str]:
    tags = model.structure_tags()
    if stage_index <= 0 or not model.stages:
        if model.initial.active_structures is None:
            return frozenset(t for t, k in tags.items() if k == "interface")
        return frozenset(model.initial.active_structures)
    idx = min(stage_index - 1, len(model.stages) - 1)
    return frozenset(model.stages[idx].active_structures)


def stage_region_material(model, stage_index: int, region: int) -> str | None:
    """Return active material name for ``region`` at ``stage_index``, or ``None`` if excavated."""
    if region not in stage_active_regions(model, stage_index):
        return None
    if stage_index <= 0 or not model.stages:
        return model.region_material[region]
    idx = min(stage_index - 1, len(model.stages) - 1)
    return model.stages[idx].material_override.get(region, model.region_material[region])


def set_region_stage_state(
    model, stage_index: int, region: int, material: str | None, *, propagate: bool = True
):
    """RS2-style region assignment: ``material=None`` excavates; a name activates/assigns."""
    all_regions = frozenset(model.mesh.regions())
    if region not in all_regions:
        raise ValueError(f"Bilinmeyen bölge: {region}")
    mat_name = (
        model.region_material[region]
        if material == "__active__"
        else material
    )
    if mat_name is not None and mat_name not in model.materials:
        raise ValueError(f"Bilinmeyen malzeme: {mat_name}")

    initial = model.initial
    region_material = dict(model.region_material)
    stages = list(model.stages)

    if stage_index <= 0:
        cur = set(stage_active_regions(model, 0))
        if mat_name is None:
            cur.discard(region)
        else:
            cur.add(region)
            region_material[region] = mat_name
        active_val = None if cur == all_regions else frozenset(cur)
        initial = replace(initial, active_regions=active_val)
        target_indices: Iterable[int] = range(1, len(stages) + 1) if propagate else ()
    else:
        start = min(max(1, stage_index), len(stages))
        target_indices = range(start, len(stages) + 1) if propagate else (start,)

    for idx in target_indices:
        st = stages[idx - 1]
        cur = set(all_regions if st.active_regions is None else st.active_regions)
        overrides = dict(st.material_override)
        if mat_name is None:
            cur.discard(region)
        else:
            cur.add(region)
            if mat_name == region_material[region]:
                overrides.pop(region, None)
            else:
                overrides[region] = mat_name
        active_val = None if cur == all_regions else frozenset(cur)
        stages[idx - 1] = replace(
            st, active_regions=active_val, material_override=overrides
        )

    return validate_edit(
        replace(model, initial=initial, region_material=region_material, stages=stages)
    )


def set_structure_stage_state(
    model, stage_index: int, tag: str, active: bool, *, propagate: bool = True
):
    """RS2-style structure activation/deactivation from ``stage_index`` onwards.

    A pile's skin interfaces are switched together with the pile."""
    from ..cad.supports import companion_tags

    if tag not in model.structure_tags():
        raise ValueError(f"Bilinmeyen yapı: {tag}")
    tags = {tag, *(t for t in companion_tags(tag) if t in model.interfaces)}
    initial = model.initial
    stages = list(model.stages)
    if stage_index <= 0:
        cur = set(stage_active_structures(model, 0))
        cur = cur | tags if active else cur - tags
        initial = replace(initial, active_structures=frozenset(cur))
        target_indices: Iterable[int] = range(1, len(stages) + 1) if propagate else ()
    else:
        start = min(max(1, stage_index), len(stages))
        target_indices = range(start, len(stages) + 1) if propagate else (start,)

    for idx in target_indices:
        st = stages[idx - 1]
        cur = set(st.active_structures)
        cur = cur | tags if active else cur - tags
        stages[idx - 1] = replace(st, active_structures=frozenset(cur))

    return validate_edit(replace(model, initial=initial, stages=stages))


def append_stage_rs2(model, after_index: int | None = None, name: str | None = None):
    """Insert a stage inheriting the preceding stage's excavations, supports, loads and water."""
    stages = list(model.stages)
    existing_names = {s.name for s in stages}
    if name is None:
        n = len(stages) + 1
        candidate = f"Aşama {n}"
        while candidate in existing_names:
            n += 1
            candidate = f"Aşama {n}"
        name = candidate
    if not stages or (after_index is not None and after_index <= 0):
        new_stage = api.Stage(
            name=name,
            active_regions=model.initial.active_regions,
            active_structures=stage_active_structures(model, 0),
            water=model.initial.water,
        )
        insert_pos = 0 if (after_index is not None and after_index <= 0) else len(stages)
    else:
        ref_idx = len(stages) - 1 if after_index is None else min(after_index - 1, len(stages) - 1)
        ref = stages[ref_idx]
        new_stage = replace(
            ref,
            name=name,
            load_split=1.0,
            reset_displacements=False,
        )
        insert_pos = ref_idx + 1
    stages.insert(insert_pos, new_stage)
    return validate_edit(replace(model, stages=stages)), insert_pos + 1


def put_interface(model, spec, edge_set, side="left"):
    """Split a named edge transactionally; preserve the model's activation policy."""
    from ..mesh.structures import insert_interface

    if not spec.name.strip() or "," in spec.name or spec.name == "auto":
        raise ValueError("Ara yüz etiketi boş, virgüllü veya auto olamaz.")
    mesh = insert_interface(model.mesh, edge_set, spec.name, side)
    edit = {"kind": "interface", "tag": spec.name, "edge_set": edge_set, "side": side}
    return validate_edit(
        record_mesh_edit(
            replace(model, mesh=mesh, interfaces={**model.interfaces, spec.name: spec}), edit
        )
    )


def remove_interface(model, tag):
    """Weld paired coincident nodes. Refuse to collapse another interface element."""
    block = model.mesh.block(tag)
    if model.structure_tags().get(tag) != "interface":
        raise ValueError("Ara yüz bloğu seçilmeli.")
    parent = np.arange(model.mesh.nn)

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    half = block.conn.shape[1] // 2
    for a, b in zip(block.conn[:, :half].ravel(), block.conn[:, half:].ravel()):
        if np.linalg.norm(model.mesh.coords[a] - model.mesh.coords[b]) > 1e-9:
            raise ValueError("Çakışmayan ara yüz düğümleri birleştirilemez.")
        a, b = root(a), root(b)
        parent[max(a, b)] = min(a, b)
    remap = np.array([root(i) for i in range(model.mesh.nn)])
    blocks = []
    for b in model.mesh.blocks:
        if b.tag == tag:
            continue
        conn = remap[b.conn]
        if model.structure_tags().get(b.tag) == "interface":
            n = conn.shape[1] // 2
            if np.any(np.all(conn[:, :n] == conn[:, n:], axis=1)):
                raise ValueError("Silme başka ara yüz elemanını kapatır; önce onu kaldırın.")
        blocks.append(replace(b, conn=conn))
    mesh = api.Mesh(
        model.mesh.coords,
        tuple(blocks),
        {k: np.unique(remap[v]) for k, v in model.mesh.node_sets.items()},
        {k: remap[v] for k, v in model.mesh.edge_sets.items()},
    )
    initial = model.initial
    if initial.active_structures is not None:
        initial = replace(initial, active_structures=initial.active_structures - {tag})
    return validate_edit(
        replace(
            forget_mesh_edit(model, tag),
            mesh=mesh,
            initial=initial,
            interfaces={k: v for k, v in model.interfaces.items() if k != tag},
            stages=[
                replace(s, active_structures=s.active_structures - {tag}) for s in model.stages
            ],
        )
    )
