"""Geometry-backed material definitions and stage assignments, independent of a mesh."""

from dataclasses import asdict, replace

from .. import api
from ..core.enums import Drainage


def material_specs(drawing, model=None):
    materials = {
        "soil": api.MaterialSpec.elastic("soil", drawing.E, drawing.nu, gamma=drawing.gamma)
    }
    if model is not None:
        materials.update(model.materials)
    for data in drawing.material_library:
        materials[data["name"]] = api.MaterialSpec(
            **{**data, "drainage": Drainage(data["drainage"])}
        )
    return materials


def serialize_materials(materials):
    return tuple({**asdict(s), "drainage": s.drainage.value} for s in materials.values())


def stage_names(drawing):
    return ["Initial", drawing.loading_name, *[s.name for s in drawing.sequence]]


def region_state(drawing, row, entity, model=None):
    from ..gui.editing import stage_region_material

    material = "soil"
    if model is not None and entity.region in model.mesh.regions():
        names = ["Initial", *[s.name for s in model.stages]]
        name = stage_names(drawing)[row]
        if name in names:
            material = stage_region_material(model, names.index(name), entity.region)
    else:
        for step in drawing.sequence[: max(0, row - 1)]:
            if entity.name in step.disturb and drawing.disturbed_material:
                material = drawing.disturbed_material
            if entity.name in step.excavate:
                material = None
    name = stage_names(drawing)[row]
    for entry in drawing.material_assignments:
        if entry["stage"] == name and entry["region"] == entity.name:
            material = entry["material"]
    return material


def assign_region(drawing, row, entity, material, propagate=False, model=None):
    materials = material_specs(drawing, model)
    if material is not None and material not in materials:
        raise ValueError(f"Unknown material: {material}")
    names = stage_names(drawing)
    targets = names[row:] if propagate else [names[row]]
    entries = [
        e
        for e in drawing.material_assignments
        if not (e["region"] == entity.name and e["stage"] in targets)
    ]
    entries.extend({"stage": name, "region": entity.name, "material": material} for name in targets)
    return replace(
        drawing,
        material_library=serialize_materials(materials),
        material_assignments=tuple(entries),
    )


def apply_assignments(model, drawing):
    """Apply after ordinary mesh generation/transfer so explicit drawing edits win."""
    if not drawing.material_library and not drawing.material_assignments:
        return model
    from ..gui.editing import set_region_stage_state

    model = replace(model, materials={**model.materials, **material_specs(drawing, model)})
    names = ["Initial", *[s.name for s in model.stages]]
    regions = {e.name: e.region for e in drawing.entities if e.kind == "region"}
    # Initial first: it preserves later states before explicit construction-stage edits.
    entries = sorted(
        drawing.material_assignments,
        key=lambda e: names.index(e["stage"]) if e["stage"] in names else len(names),
    )
    for entry in entries:
        if entry["stage"] in names and entry["region"] in regions:
            model = set_region_stage_state(
                model,
                names.index(entry["stage"]),
                regions[entry["region"]],
                entry["material"],
                propagate=False,
            )
    return model
