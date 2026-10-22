"""Drawing support assignments compiled to actual beam/bar mesh blocks."""

from dataclasses import dataclass, field, replace

import numpy as np

from .. import api
from ..mesh.structures import add_bars_along, add_beams


def default_properties(kind):
    if kind == "bolt":
        return dict(EA=200000.0, T_yield=200.0, pretension=0.0, spacing_out_of_plane=1.0)
    if kind == "pile":
        # Diameter 0.8 m, spacing 2 m: equivalent properties per metre out of plane.
        area = np.pi * 0.8**2 / 4 / 2
        inertia = np.pi * 0.8**4 / 64 / 2
        return dict(E=3e7, nu=0.2, A=area, I=inertia, As=area * 5 / 6, unit_weight=24.0)
    return dict(E=3e7, nu=0.2, A=0.3, I=0.3**3 / 12, As=0.25, unit_weight=24.0)


@dataclass(frozen=True)
class SupportAssignment:
    entity: str
    kind: str  # pile, liner, bolt
    properties: dict = field(default_factory=dict)
    active: bool = True

    @property
    def tag(self):
        return f"cad_{self.entity}"

    def __post_init__(self):
        if self.kind not in {"pile", "liner", "bolt"}:
            raise ValueError("Destek türü pile, liner veya bolt olmalıdır.")
        if not self.entity or "," in self.entity or not isinstance(self.active, bool):
            raise ValueError("Destek adı ve etkinlik değeri geçersiz.")
        props = {**default_properties(self.kind), **self.properties}
        object.__setattr__(self, "properties", props)
        self.spec()  # reject invalid stiffness/section values before changing a drawing

    def spec(self):
        cls = api.BoltSpec if self.kind == "bolt" else api.LinerSpec
        return cls(self.tag, **self.properties)


def compile_supports(model, drawing):
    mesh = model.mesh
    liners, bolts = dict(model.liners), dict(model.bolts)
    entities = {e.name: e for e in drawing.entities}
    active = set()
    for assignment in drawing.supports:
        entity = entities[assignment.entity]
        edges = np.vstack([mesh.edge_sets[name] for name in entity.edge_names()])
        if not len(edges):
            raise ValueError(f"{entity.name}: destek için ağ kenarı bulunamadı.")
        edge_name = f"{assignment.tag}:path"
        mesh = replace(mesh, edge_sets={**mesh.edge_sets, edge_name: edges})
        if assignment.kind == "bolt":
            mesh = add_bars_along(mesh, edge_name, assignment.tag)
            bolts[assignment.tag] = assignment.spec()
        else:
            mesh = add_beams(mesh, edge_name, assignment.tag)
            liners[assignment.tag] = assignment.spec()
        if assignment.active:
            active.add(assignment.tag)
    return replace(
        model,
        mesh=mesh,
        liners=liners,
        bolts=bolts,
        stages=[replace(s, active_structures=s.active_structures | active) for s in model.stages],
    )
