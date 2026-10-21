"""Top-level model container (L1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import Analysis
from ..core.errors import ModelError
from .boundary import Displacement, EdgeLoad, Fixity, PointLoad
from .materials import BoltSpec, LinerSpec, MaterialSpec
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
            for r, m in st.material_override.items():
                if m not in self.materials:
                    raise ModelError(f"stage '{st.name}': override region {r} -> unknown '{m}'")
        if self.initial.mode not in ("gravity", "k0_field", "none"):
            raise ModelError(f"unknown initial stress mode '{self.initial.mode}'")
