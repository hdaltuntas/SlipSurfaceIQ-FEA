"""Qt-independent, transactional editing operations used by the desktop forms."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .. import api
from ..fem.materials import build
from ..mesh.structures import add_bar, add_bars_along, add_beams


def validate_edit(model):
    model.validate()
    for spec in model.materials.values():
        build(spec)
    names = [s.name.strip() for s in model.stages]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Aşama adları boş olamaz ve benzersiz olmalıdır.")
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
    else:
        if nodes is None:
            mesh = add_bars_along(model.mesh, edge_set, spec.name)
        else:
            a, b = map(int, nodes)
            if not (0 <= a < model.mesh.nn and 0 <= b < model.mesh.nn):
                raise ValueError("Bolt uç düğümü ağ dışında.")
            if np.linalg.norm(model.mesh.coords[a] - model.mesh.coords[b]) <= 1e-12:
                raise ValueError("Bolt uçları farklı konumlarda olmalıdır.")
            mesh = add_bar(model.mesh, a, b, spec.name)
        result = replace(model, mesh=mesh, bolts={**model.bolts, spec.name: spec})
    block = mesh.block(spec.name)
    if not block.ne:
        raise ValueError("Seçilen kenar kümesi boş.")
    if np.any(
        np.linalg.norm(mesh.coords[block.conn[:, 1]] - mesh.coords[block.conn[:, 0]], axis=1)
        <= 1e-12
    ):
        raise ValueError("Yapı sıfır uzunluklu eleman içeriyor.")
    return validate_edit(result)


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
            model,
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
