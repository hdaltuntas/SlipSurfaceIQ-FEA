"""Top-level model container (L1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import Analysis, ElemType
from ..core.errors import ModelError
from .boundary import Displacement, EdgeLoad, Fixity, PointLoad
from .materials import BoltSpec, InterfaceSpec, LinerSpec, MaterialSpec
from .mesh import Mesh
from .stages import InitialStress, SolverSettings, Stage


@dataclass
class Model:
    analysis: Analysis
    mesh: Mesh
    materials: dict[str, MaterialSpec]
    region_material: dict[int, str]
    fixities: tuple[Fixity, ...] = ()
    displacements: tuple[Displacement, ...] = ()
    initial: InitialStress = field(default_factory=InitialStress)
    stages: list[Stage] = field(default_factory=list)
    liners: dict[str, LinerSpec] = field(default_factory=dict)
    bolts: dict[str, BoltSpec] = field(default_factory=dict)
    settings: SolverSettings = field(default_factory=SolverSettings)
    interfaces: dict[str, InterfaceSpec] = field(default_factory=dict)
    # Optional CAD authoring snapshot. The solver uses mesh, never this drawing.
    geometry: dict | None = None

    def structure_tags(self) -> dict[str, str]:
        """Structural block tag -> kind ("beam" | "bar" | "interface")."""
        kinds = {ElemType.BEAM2: "beam", ElemType.BAR2: "bar", ElemType.IFACE4: "interface",
                 ElemType.IFACE6: "interface"}  # fmt: skip
        return {b.tag: kinds[b.etype] for b in self.mesh.blocks if b.etype in kinds}

    def validate(self) -> None:
        """Raise :class:`ModelError` on any dangling reference."""
        for name, mat in self.materials.items():
            if name != mat.name:
                raise ModelError(f"materials key '{name}' != MaterialSpec.name '{mat.name}'")
        missing = sorted(r for r in self.mesh.regions() if r not in self.region_material)
        if missing:
            raise ModelError(f"regions without material: {missing}")
        for r, m in self.region_material.items():
            if m not in self.materials:
                raise ModelError(f"region {r} -> unknown material '{m}'")
        for bc in (*self.fixities, *self.displacements):
            if bc.node_set not in self.mesh.node_sets:
                raise ModelError(f"boundary condition refers to unknown node set '{bc.node_set}'")
        for st in self.stages:
            for ld in st.loads:
                if isinstance(ld, EdgeLoad) and ld.edge_set not in self.mesh.edge_sets:
                    raise ModelError(f"stage '{st.name}': unknown edge set '{ld.edge_set}'")
                if isinstance(ld, PointLoad) and not 0 <= ld.node < self.mesh.nn:
                    raise ModelError(f"stage '{st.name}': point load node {ld.node} out of range")
            for dp in st.displacements:
                if dp.node_set not in self.mesh.node_sets:
                    raise ModelError(f"stage '{st.name}': unknown node set '{dp.node_set}'")
            for r, m in st.material_override.items():
                if m not in self.materials:
                    raise ModelError(f"stage '{st.name}': override region {r} -> unknown '{m}'")
        props = {"beam": self.liners, "bar": self.bolts, "interface": self.interfaces}
        tags = self.structure_tags()
        for tag, kind in tags.items():
            if tag not in props[kind]:
                raise ModelError(f"{kind} block '{tag}' has no property set of that name")
        if tags and self.analysis is Analysis.AXISYMMETRIC and "beam" in tags.values():
            raise ModelError("beam (liner) elements are not available in axisymmetry yet")
        all_regions = self.mesh.regions()
        for st in self.stages:
            unknown = set(st.active_structures) - set(tags)
            if unknown:
                raise ModelError(f"stage '{st.name}': unknown structures {sorted(unknown)}")
            if st.active_regions is not None and not set(st.active_regions) <= all_regions:
                raise ModelError(f"stage '{st.name}': unknown regions in active_regions")
            if st.water.mode == "seepage":
                w = st.water
                names = [h.node_set for h in w.head_bcs] + list(w.seepage_faces)
                for nm in names:
                    if nm not in self.mesh.node_sets and nm not in self.mesh.edge_sets:
                        raise ModelError(f"stage '{st.name}': unknown seepage set '{nm}'")
                for fb in w.flux_bcs:
                    if fb.edge_set not in self.mesh.edge_sets:
                        raise ModelError(f"stage '{st.name}': unknown edge set '{fb.edge_set}'")
        if self.initial.active_structures is not None:
            unknown = set(self.initial.active_structures) - set(tags)
            if unknown:
                raise ModelError(f"initial stage: unknown structures {sorted(unknown)}")
        if self.initial.mode not in ("gravity", "k0_field", "field", "none"):
            raise ModelError(f"unknown initial stress mode '{self.initial.mode}'")
        if self.initial.mode == "field" and self.initial.field is None:
            raise ModelError("initial stress mode 'field' needs InitialStress.field")
        if self.settings.method not in ("NR", "mNR", "hybrid", "initial"):
            raise ModelError(f"unknown nonlinear method '{self.settings.method}'")
