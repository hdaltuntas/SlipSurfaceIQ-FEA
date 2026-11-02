"""Drawing support assignments compiled to actual beam/bar/interface mesh blocks.

A pile is a beam row: its section follows from the pile diameter ``D`` and the
out-of-plane spacing ``spacing`` (``A = pi D^2 / 4 / s``, ``I = pi D^4 / 64 / s``, per metre).
With ``interface = 1`` it is a *structural interface*: the beam keeps its own nodes and is
joined to the soil on both sides by zero-thickness interfaces whose shear strength is the
skin resistance ``T_skin`` [kN/m per pile] shared by the two faces (``c_i = T / (2 s)``).
"""

from dataclasses import dataclass, field, replace

import numpy as np

from .. import api
from ..mesh.structures import add_bars_along, add_beams, insert_interface

INTERFACE_SIDES = ("ifL", "ifR")


def pile_section(D, spacing):
    """Equivalent area and inertia per metre out of plane of a row of solid round piles."""
    if not (np.isfinite([D, spacing]).all() and D > 0 and spacing > 0):
        raise ValueError("Pile diameter and spacing must be positive.")
    return np.pi * D**2 / 4 / spacing, np.pi * D**4 / 64 / spacing


BOLT_GRADES = {
    0: ("Steel rebar B500B", 200e6, 500e3),
    1: ("Steel bar S355", 210e6, 355e3),
    2: ("Steel bar S460", 210e6, 460e3),
}


def bolt_section(diameter_mm, grade_code):
    """Nominal elastic stiffness and tensile yield for a solid circular steel bolt."""
    grade = int(grade_code)
    if grade not in BOLT_GRADES or not np.isfinite(diameter_mm) or diameter_mm <= 0:
        raise ValueError("A valid grade and positive diameter in mm are required.")
    _, e, fy = BOLT_GRADES[grade]
    area = np.pi * (diameter_mm / 1000.0) ** 2 / 4.0
    return e * area, fy * area


def default_properties(kind, legacy=False):
    if kind == "bolt":
        ea, fy = bolt_section(25.0, 0)
        return dict(EA=ea, T_yield=fy, pretension=0.0, spacing_out_of_plane=1.0,
                    diameter_mm=25.0, grade_code=0)
    if kind == "pile" and legacy:
        area, inertia = pile_section(0.8, 2.0)
        return dict(E=3e7, nu=0.2, A=area, I=inertia, As=area * 5 / 6, unit_weight=24.0)
    if kind == "pile":
        return dict(
            E=3e7,
            nu=0.2,
            D=0.8,
            spacing=2.0,
            unit_weight=24.0,
            interface=1.0,
            T_skin=200.0,
            kn=1e6,
            ks=1e5,
        )
    return dict(E=3e7, nu=0.2, A=0.3, I=0.3**3 / 12, As=0.25, unit_weight=24.0)


def companion_tags(tag):
    """Interface tags that belong to the structure ``tag`` (a pile's two skin faces)."""
    return tuple(f"{tag}_{side}" for side in INTERFACE_SIDES)


def owner_tag(tag):
    """The structure an interface tag belongs to (``tag`` itself for anything else)."""
    for side in INTERFACE_SIDES:
        if tag.endswith(f"_{side}"):
            return tag[: -len(side) - 1]
    return tag


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
            raise ValueError("Support kind must be pile, liner or bolt.")
        if not self.entity or "," in self.entity or not isinstance(self.active, bool):
            raise ValueError("Support name or active flag is invalid.")
        legacy = self.kind == "pile" and "A" in self.properties and "D" not in self.properties
        props = {**default_properties(self.kind, legacy), **self.properties}
        object.__setattr__(self, "properties", props)
        self.spec()  # reject invalid stiffness/section values before changing a drawing
        for spec in self.interface_specs():
            spec.name  # noqa: B018 - constructing the spec validates it

    @property
    def has_interface(self):
        return self.kind == "pile" and bool(self.properties.get("interface", 0.0))

    def spec(self):
        p = self.properties
        if self.kind == "bolt":
            values = {k: p[k] for k in ("EA", "T_yield", "pretension", "spacing_out_of_plane")}
            if "diameter_mm" in self.properties:
                values["EA"], values["T_yield"] = bolt_section(
                    p["diameter_mm"], p.get("grade_code", 0)
                )
            return api.BoltSpec(self.tag, **values)
        if self.kind == "pile" and "D" in p:
            area, inertia = pile_section(p["D"], p["spacing"])
            # Shear area of a solid circle: 0.9 A.
            return api.LinerSpec(self.tag, p["E"], p["nu"], area, inertia, 0.9 * area,
                                 p["unit_weight"])  # fmt: skip
        return api.LinerSpec(self.tag, **p)

    def interface_specs(self):
        if not self.has_interface:
            return ()
        p = self.properties
        if not (p["T_skin"] >= 0 and p["kn"] > 0 and p["ks"] >= 0):
            raise ValueError("Interface: T_skin ≥ 0, kn > 0 and ks ≥ 0 are required.")
        c = p["T_skin"] / (2 * p["spacing"])
        return tuple(
            api.InterfaceSpec(name, p["kn"], p["ks"], c=c, sig_t=c)
            for name in companion_tags(self.tag)
        )


def compile_supports(model, drawing):
    mesh = model.mesh
    liners, bolts = dict(model.liners), dict(model.bolts)
    interfaces = dict(model.interfaces)
    entities = {e.name: e for e in drawing.entities}
    active = set()
    for assignment in drawing.supports:
        entity = entities[assignment.entity]
        edges = np.vstack([mesh.edge_sets[name] for name in entity.edge_names()])
        if not len(edges):
            raise ValueError(f"{entity.name}: no mesh edge found for the support.")
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
            active.update(s.name for s in assignment.interface_specs())
    # Skin interfaces last: anchors and liners added above stay on the pile's own nodes,
    # only the soil on either side moves to the duplicated nodes.
    for assignment in drawing.supports:
        for spec, side in zip(assignment.interface_specs(), ("left", "right")):
            mesh = insert_interface(mesh, f"{assignment.tag}:path", spec.name, side)
            interfaces[spec.name] = spec
    return replace(
        model,
        mesh=mesh,
        liners=liners,
        bolts=bolts,
        interfaces=interfaces,
        stages=[replace(s, active_structures=s.active_structures | active) for s in model.stages],
    )
