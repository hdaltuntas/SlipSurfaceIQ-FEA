"""Serializable CAD input, topology validation and an explicit fresh-model builder.

All coordinates are metres. Nested regions override their parent; partial overlaps
are rejected. A hole is an initially empty void, not a staged excavation region.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from shapely.validation import explain_validity

from .. import api
from ..mesh import Domain, unstructured_mesh
from .supports import SupportAssignment, compile_supports


@dataclass(frozen=True)
class Entity:
    name: str
    kind: str  # region, hole, line
    points: tuple[tuple[float, float], ...]
    region: int = 1

    def __post_init__(self):
        p = tuple(tuple(float(v) for v in xy) for xy in self.points)
        if self.kind != "line" and len(p) > 1 and p[0] == p[-1]:
            p = p[:-1]
        object.__setattr__(self, "points", p)
        if not self.name.strip() or ":" in self.name or self.name in {"boundary", "all"}:
            raise ValueError("Geometry name cannot be empty, a reserved name, or contain ':'.")
        if self.kind not in {"region", "hole", "line"}:
            raise ValueError("Geometry kind must be region, hole or line.")
        if len(p) < (2 if self.kind == "line" else 3):
            raise ValueError("A line needs at least 2 points and a closed region at least 3.")
        xy = np.asarray(p)
        if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all():
            raise ValueError("Coordinates must be finite (x, y) pairs.")
        if isinstance(self.region, bool) or int(self.region) != self.region or self.region < 1:
            raise ValueError("Region number must be a positive integer.")
        if len(set(p)) != len(p):
            raise ValueError(f"{self.name}: repeated point.")
        shape = self.shape()
        if not shape.is_valid or not shape.is_simple:
            raise ValueError(
                f"{self.name}: invalid or self-intersecting geometry: {explain_validity(shape)}"
            )
        if self.kind != "line" and shape.area <= 1e-12:
            raise ValueError(f"{self.name}: zero or too small area.")
        if any(np.linalg.norm(np.subtract(a, b)) <= 1e-9 for a, b in self.segments()):
            raise ValueError(f"{self.name}: zero or too short edge.")

    def shape(self):
        return LineString(self.points) if self.kind == "line" else Polygon(self.points)

    def segments(self):
        p = self.points if self.kind == "line" else (*self.points, self.points[0])
        return list(zip(p[:-1], p[1:]))

    def edge_names(self):
        return [f"{self.name}:{i + 1}" for i in range(len(self.segments()))]


@dataclass(frozen=True)
class BoundaryRule:
    edge: str
    ux: bool = False
    uy: bool = False
    pressure: float = 0.0

    def __post_init__(self):
        if not isinstance(self.ux, bool) or not isinstance(self.uy, bool):
            raise ValueError("Fixity values must be true or false.")
        if not np.isfinite(self.pressure):
            raise ValueError("Pressure must be finite.")


@dataclass(frozen=True)
class ConstructionStep:
    """One generated stage: regions excavated and supports installed in it.

    ``load_split`` < 1 stops an excavation stage early (stress-release/beta method); the
    rest of the unbalance is carried by the next stage, after its support is installed.
    ``disturb`` names remaining regions that switch to the blast-disturbed material in
    this stage (typically the halo, on the step after the blast).
    """

    name: str
    excavate: tuple[str, ...] = ()
    install: tuple[str, ...] = ()
    load_split: float = 1.0
    disturb: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "excavate", tuple(self.excavate))
        object.__setattr__(self, "install", tuple(self.install))
        object.__setattr__(self, "disturb", tuple(self.disturb))
        if not self.name.strip():
            raise ValueError("Stage name cannot be empty.")
        if not 0.0 < float(self.load_split) <= 1.0:
            raise ValueError("Pre-support load ratio must be in (0, 1].")


@dataclass(frozen=True)
class Drawing:
    entities: tuple[Entity, ...] = ()
    rules: tuple[BoundaryRule, ...] = ()
    h: float = 1.0
    E: float = 20000.0
    nu: float = 0.3
    gamma: float = 20.0
    supports: tuple[SupportAssignment, ...] = ()
    sequence: tuple[ConstructionStep, ...] = ()
    disturbance: dict | None = None  # {D, thickness, regions, material?}
    disturbed_material: str = ""
    loading_name: str = "CAD loading"
    material_library: tuple[dict, ...] = ()
    material_assignments: tuple[dict, ...] = ()
    mesh_refinements: tuple[dict, ...] = ()  # {x, y, radius, h} circular local zones

    def __post_init__(self):
        if not np.isfinite([self.h, self.E, self.nu, self.gamma]).all():
            raise ValueError("Mesh and material values must be finite.")
        if self.h <= 0 or self.E <= 0 or self.gamma < 0 or not 0 <= self.nu < 0.5:
            raise ValueError("h and E must be positive, γ ≥ 0 and 0 ≤ ν < 0.5.")
        refinements = tuple(dict(item) for item in self.mesh_refinements)
        for item in refinements:
            if not {"x", "y", "radius", "h"} <= set(item):
                raise ValueError("Mesh refinement requires x, y, radius and h.")
            values = np.asarray([item[k] for k in ("x", "y", "radius", "h")], dtype=float)
            if not np.isfinite(values).all() or values[2] <= 0 or values[3] <= 0:
                raise ValueError("Mesh refinement zone needs finite positive radius and h.")
        object.__setattr__(self, "mesh_refinements", refinements)
        names = [self.loading_name, *(step.name for step in self.sequence)]
        if any(not n.strip() for n in names) or len({n.strip() for n in names}) != len(names):
            raise ValueError("Construction stage names must be non-empty and unique.")

    def to_dict(self):
        return {"version": 2, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        if data.get("version") not in (1, 2):
            raise ValueError("Unsupported CAD file version.")
        return cls(
            tuple(Entity(**e) for e in data["entities"]),
            tuple(BoundaryRule(**r) for r in data.get("rules", [])),
            float(data["h"]),
            float(data["E"]),
            float(data["nu"]),
            float(data.get("gamma", 20.0)),
            tuple(SupportAssignment(**s) for s in data.get("supports", [])),
            tuple(ConstructionStep(**c) for c in data.get("sequence", [])),
            data.get("disturbance"),
            str(data.get("disturbed_material") or ""),
            str(data.get("loading_name", "CAD loading")),
            tuple(data.get("material_library", ())),
            tuple(data.get("material_assignments", ())),
            tuple(data.get("mesh_refinements", ())),
        )

    def with_stage_names(self, names):
        """Resize the draft schedule, retaining operations on surviving steps."""
        if not names:
            raise ValueError("At least one construction stage is required.")
        sequence = tuple(
            replace(self.sequence[i], name=name)
            if i < len(self.sequence)
            else ConstructionStep(name)
            for i, name in enumerate(names[1:])
        )
        old_names = ["Initial", self.loading_name, *[s.name for s in self.sequence]]
        renamed = dict(zip(old_names, ["Initial", *names]))
        assignments = tuple({**a, "stage": renamed[a["stage"]]}
                            for a in self.material_assignments if a["stage"] in renamed)
        return replace(self, loading_name=names[0], sequence=sequence,
                       material_assignments=assignments)

    def without_entity(self, name):
        """Drop an entity with its edge rules, support and construction-step references."""
        old = next(e for e in self.entities if e.name == name)
        steps = []
        for step in self.sequence:
            step = replace(
                step,
                excavate=tuple(n for n in step.excavate if n != name),
                install=tuple(n for n in step.install if n != name),
                disturb=tuple(n for n in step.disturb if n != name),
            )
            if step.excavate or step.install or step.disturb:
                steps.append(step)
        return replace(
            self,
            entities=tuple(e for e in self.entities if e.name != name),
            rules=tuple(r for r in self.rules if r.edge not in old.edge_names()),
            supports=tuple(s for s in self.supports if s.entity != name),
            sequence=tuple(steps),
            material_assignments=tuple(a for a in self.material_assignments
                                       if a["region"] != name),
        )

    def renamed(self, old, new):
        """Follow an entity rename in the construction sequence."""
        return replace(
            self,
            material_assignments=tuple({**a, "region": new if a["region"] == old
                                        else a["region"]} for a in self.material_assignments),
            sequence=tuple(
                replace(
                    step,
                    excavate=tuple(new if n == old else n for n in step.excavate),
                    install=tuple(new if n == old else n for n in step.install),
                    disturb=tuple(new if n == old else n for n in step.disturb),
                )
                for step in self.sequence
            ),
        )

    @classmethod
    def example(cls):
        return cls(
            (Entity("Soil", "region", ((0, 0), (12, 0), (12, 6), (0, 6))),),
            (
                BoundaryRule("Soil:1", True, True),
                BoundaryRule("Soil:2", True),
                BoundaryRule("Soil:3", pressure=50),
                BoundaryRule("Soil:4", True),
            ),
        )

    def validate(self):
        names = [e.name for e in self.entities]
        if len(set(names)) != len(names):
            raise ValueError("Geometry names must be unique.")
        assigned = set()
        by_name = {e.name: e for e in self.entities}
        for support in self.supports:
            if support.entity not in by_name or support.entity in assigned:
                raise ValueError(
                    "A support must reference geometry and be assigned once per object."
                )
            if support.kind in {"pile", "bolt"} and by_name[support.entity].kind != "line":
                raise ValueError("Piles and anchors/nails require line geometry.")
            assigned.add(support.entity)
        step_names = [step.name for step in self.sequence]
        if len(set(step_names)) != len(step_names):
            raise ValueError("Construction stage names must be unique.")
        supported = {s.entity for s in self.supports}
        for step in self.sequence:
            for name in step.excavate:
                if name not in by_name or by_name[name].kind != "region":
                    raise ValueError(f"{step.name}: excavation region '{name}' was not found.")
            for name in step.install:
                if name not in supported:
                    raise ValueError(f"{step.name}: support to install '{name}' was not found.")
            for name in step.disturb:
                if name not in by_name or by_name[name].kind != "region":
                    raise ValueError(f"{step.name}: region to disturb '{name}' was not found.")
        regions = [e for e in self.entities if e.kind == "region"]
        holes = [e for e in self.entities if e.kind == "hole"]
        if not regions:
            raise ValueError("At least one closed material region must be drawn.")
        polys = [e.shape() for e in regions]
        for i, a in enumerate(polys):
            for b in polys[i + 1 :]:
                if a.equals(b) or (
                    a.intersection(b).area > 1e-12 and not (a.covers(b) or b.covers(a))
                ):
                    raise ValueError(
                        "Regions overlap partially. Use a shared edge or nested regions."
                    )
        outer = unary_union(polys)
        voids = [e.shape() for e in holes]
        for i, hole in enumerate(voids):
            if not outer.contains(hole) or outer.boundary.intersects(hole):
                raise ValueError(
                    "A void must lie entirely inside the soil "
                    "and must not touch the outer boundary."
                )
            if any(hole.intersects(b) for b in voids[i + 1 :]):
                raise ValueError("Voids cannot intersect or nest.")
            # Domain uses the innermost polygon: crossing layers/islands would be ambiguous.
            if any(hole.intersection(p).area > 1e-12 and not p.covers(hole) for p in polys):
                raise ValueError("A void cannot cross a region boundary or contain a region.")
        soil = outer.difference(unary_union(voids))
        for e in self.entities:
            if e.kind == "line" and not soil.covers(e.shape()):
                raise ValueError(f"{e.name}: line is outside the soil or inside a void.")
        edge_names = {n for e in self.entities for n in e.edge_names()}
        seen = set()
        for rule in self.rules:
            if rule.edge not in edge_names or rule.edge in seen:
                raise ValueError(f"Invalid or duplicate edge condition: {rule.edge}")
            seen.add(rule.edge)
            if not np.isfinite(rule.pressure):
                raise ValueError("Pressure must be finite.")
        return soil

    def split_with_line(self, points, name_prefix="Excav") -> Drawing:
        """RS2-style excavation/layer line: subdivide existing region(s) into new region(s)."""
        pts = [tuple(float(v) for v in xy) for xy in points]
        if len(pts) < 2:
            raise ValueError("A split line needs at least 2 points.")
        cutter = LineString(pts)
        if not cutter.is_valid or cutter.length <= 1e-6:
            raise ValueError("Split line is invalid or has zero length.")
        regions = [e for e in self.entities if e.kind == "region"]
        if not regions:
            raise ValueError("Draw a soil region to split first.")
        holes = [e.shape() for e in self.entities if e.kind == "hole"]
        void_union = unary_union(holes) if holes else Polygon()
        reg_polys = [(e, e.shape()) for e in regions]

        def effective_area(idx):
            _, p = reg_polys[idx]
            inner = [
                q
                for j, (_, q) in enumerate(reg_polys)
                if j != idx and q.area < p.area and p.covers(q)
            ]
            rem = p.difference(unary_union(inner)) if inner else p
            return rem.difference(void_union) if not void_union.is_empty else rem

        lines = [p.boundary for _, p in reg_polys]
        lines.extend(e.shape() for e in self.entities if e.kind == "line")
        lines.append(cutter)
        faces = [
            f
            for f in polygonize(unary_union(lines))
            if f.area > 1e-6 and (void_union.is_empty or f.intersection(void_union).area <= 1e-9)
        ]

        # Group faces by their innermost enclosing region entity.
        grouped: dict[int, list[Polygon]] = {i: [] for i in range(len(reg_polys))}
        for face in faces:
            rep = face.representative_point()
            containing = [(p.area, i) for i, (_, p) in enumerate(reg_polys) if p.covers(rep)]
            if containing:
                _, owner = min(containing)
                eff = effective_area(owner)
                if eff.covers(rep):
                    grouped[owner].append(face)

        new_faces: list[Polygon] = []
        for _owner, subfaces in grouped.items():
            if len(subfaces) >= 2:
                # Keep one face as the parent region (lowest centroid y / largest area),
                # and turn the carved upper/smaller face(s) into new excavatable regions.
                ordered = sorted(
                    subfaces,
                    key=lambda f: (-round(f.centroid.y, 6), round(f.area, 6)),
                )
                new_faces.extend(ordered[:-1])

        if not new_faces:
            raise ValueError(
                "The line did not split any region into two closed parts. "
                "Join the line ends to a region boundary or a pile."
            )

        existing_names = {e.name for e in self.entities}
        next_reg = max((e.region for e in regions), default=0) + 1
        added = []
        num = 1
        for face in new_faces:
            while f"{name_prefix}{num}" in existing_names:
                num += 1
            cname = f"{name_prefix}{num}"
            existing_names.add(cname)
            raw_coords = list(face.exterior.coords[:-1])
            cleaned: list[tuple[float, float]] = []
            for xy in raw_coords:
                pt = (round(float(xy[0]), 9), round(float(xy[1]), 9))
                if not cleaned or np.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) > 1e-7:
                    cleaned.append(pt)
            if (
                len(cleaned) > 1
                and np.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) <= 1e-7
            ):
                cleaned.pop()
            added.append(Entity(cname, "region", tuple(cleaned), next_reg))
            next_reg += 1

        updated = replace(self, entities=(*self.entities, *added))
        updated.validate()
        return updated

    def domain(self):
        self.validate()
        d = Domain()
        for e in self.entities:
            if e.kind == "line":
                d.add_line(e.points, name=e.name)
                for name, segment in zip(e.edge_names(), e.segments()):
                    d.add_line(segment, name=name)
            else:
                d.add_polygon(
                    e.points,
                    region=e.region,
                    hole=e.kind == "hole",
                    name=e.name,
                    edge_names=e.edge_names(),
                )
        return d

    def mesh_size_function(self):
        """Global h with radial local grading, vectorized for the Delaunay refiner."""
        if not self.mesh_refinements:
            return self.h
        zones = tuple(
            (float(v["x"]), float(v["y"]), float(v["radius"]), float(v["h"]))
            for v in self.mesh_refinements
        )
        global_h = float(self.h)

        def size(x, y):
            x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
            target = np.full(x.shape, global_h)
            for cx, cy, radius, local_h in zones:
                distance = np.hypot(x - cx, y - cy)
                # Full refinement inside radius, then linearly grade to global h
                # over one more radius to avoid abrupt element size changes.
                fraction = np.clip((distance - radius) / radius, 0.0, 1.0)
                graded = local_h + (global_h - local_h) * fraction
                target = np.minimum(target, graded)
            return target

        return size

    def build_model(self, checkpoint=None):
        """Elastic model with a K0 self-weight field.

        Structures stay off in the initial state, so a pile's skin interfaces remain
        tied until the pile is installed. γ = 0 keeps a weightless mesh (patch tests).
        """
        mesh = unstructured_mesh(
            self.domain(), h=self.mesh_size_function(),
            max_points=100000, checkpoint=checkpoint,
        )
        if checkpoint:
            checkpoint()
        boundary = {tuple(sorted(e[:2])) for e in mesh.edge_sets["boundary"]}
        loads, fixities = [], []
        loaded = set()
        for r in self.rules:
            edges = mesh.edge_sets[r.edge]
            if (r.ux or r.uy or r.pressure) and edges.size == 0:
                raise ValueError(f"{r.edge}: no mesh edge found for this condition.")
            if r.ux or r.uy:
                fixities.append(api.Fixity(r.edge, r.ux, r.uy))
            if r.pressure:
                keys = {tuple(sorted(e[:2])) for e in edges}
                if not keys <= boundary:
                    raise ValueError(f"{r.edge}: pressure only on an outer or void boundary.")
                if keys & loaded:
                    raise ValueError(f"{r.edge}: two pressures assigned to the same mesh edge.")
                loaded.update(keys)
                loads.append(api.EdgeLoad(r.edge, qn=r.pressure))
        _check_supports(mesh, fixities)
        model = api.Model(
            api.Analysis.PLANE_STRAIN,
            mesh,
            {"soil": api.MaterialSpec.elastic("soil", self.E, self.nu, gamma=self.gamma)},
            {r: "soil" for r in mesh.regions()},
            fixities=tuple(fixities),
            # No structures in the initial state: pile skin interfaces stay tied (continuous).
            # K0 from self-weight is what loads a lining when the opening is excavated.
            initial=api.InitialStress("k0_field", active_structures=frozenset()),
            stages=[api.Stage(self.loading_name, loads=tuple(loads))],
            geometry=self.to_dict(),
        )
        model = compile_supports(model, self)
        model = replace(model, stages=[*model.stages, *self.sequence_stages(model)])
        from .material_assignment import apply_assignments

        model = apply_assignments(model, self)
        model.validate()
        return model

    def sequence_stages(self, model):
        """Stages of the construction sequence, cumulative over the steps, on ``model``."""
        if not self.sequence:
            return []
        from .supports import companion_tags

        by_name = {e.name: e for e in self.entities}
        tags = {s.entity: s for s in self.supports}
        base = model.stages[0]
        excavated: set[int] = set()
        installed = set(base.active_structures)
        overrides = dict(base.material_override)
        disturbed = self.disturbed_material
        stages = []
        for step in self.sequence:
            excavated.update(by_name[n].region for n in step.excavate)
            for name in step.install:
                support = tags[name]
                installed.add(support.tag)
                installed.update(t for t in companion_tags(support.tag) if t in model.interfaces)
            if disturbed:
                for name in step.disturb:
                    overrides[by_name[name].region] = disturbed
            stages.append(
                api.Stage(
                    step.name,
                    active_regions=frozenset(model.mesh.regions() - excavated),
                    active_structures=frozenset(installed),
                    loads=base.loads,
                    load_split=step.load_split,
                    material_override=dict(overrides),
                )
            )
        return stages


def _check_supports(mesh, fixities):
    """Reject rigid translations/rotation separately in each mesh component."""
    c = mesh.blocks[0].conn
    n = c.shape[1]
    rows, cols = np.repeat(c, n, axis=1).ravel(), np.tile(c, (1, n)).ravel()
    graph = coo_matrix((np.ones(rows.size), (rows, cols)), shape=(mesh.nn, mesh.nn))
    count, labels = connected_components(graph, directed=False)
    ux, uy = set(), set()
    for bc in fixities:
        if bc.ux:
            ux.update(mesh.node_sets[bc.node_set])
        if bc.uy:
            uy.update(mesh.node_sets[bc.node_set])
    for k in range(count):
        nodes = np.flatnonzero(labels == k)
        xy = mesh.coords[nodes]
        center = xy.mean(axis=0)
        scale = max(float(np.ptp(xy, axis=0).max()), 1e-12)
        rows = []
        for i in nodes:
            x, y = (mesh.coords[i] - center) / scale
            if i in ux:
                rows.append([1, 0, -y])
            if i in uy:
                rows.append([0, 1, x])
        if not rows or np.linalg.matrix_rank(np.asarray(rows)) < 3:
            raise ValueError(
                f"Soil part {k + 1}: supports do not prevent rigid-body motion. "
                "Complete the ux/uy fixities in the edge table."
            )


def snap_point(point, entities, tolerance, grid=0.0):
    """Endpoint/midpoint snap takes priority over a user-enabled metric grid."""
    p = np.asarray(point, dtype=float)
    candidates = []
    for e in entities:
        candidates.extend(e.points)
        candidates.extend((np.asarray(a) + b) / 2 for a, b in e.segments())
    if candidates:
        q = np.asarray(candidates)
        distance = np.linalg.norm(q - p, axis=1)
        j = int(distance.argmin())
        if distance[j] <= tolerance:
            return tuple(q[j]), "Endpoint/midpoint"
    if grid > 0:
        return tuple(np.round(p / grid) * grid), "Grid"
    return tuple(p), "Free"
