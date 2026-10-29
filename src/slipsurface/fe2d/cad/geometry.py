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
            raise ValueError("Geometri adı boş, ayrılmış bir ad veya ':' içeren bir ad olamaz.")
        if self.kind not in {"region", "hole", "line"}:
            raise ValueError("Geometri türü region, hole veya line olmalıdır.")
        if len(p) < (2 if self.kind == "line" else 3):
            raise ValueError("Çizgi en az 2, kapalı bölge en az 3 nokta gerektirir.")
        xy = np.asarray(p)
        if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all():
            raise ValueError("Koordinatlar sonlu (x, y) çiftleri olmalıdır.")
        if isinstance(self.region, bool) or int(self.region) != self.region or self.region < 1:
            raise ValueError("Bölge numarası pozitif tamsayı olmalıdır.")
        if len(set(p)) != len(p):
            raise ValueError(f"{self.name}: tekrarlanan nokta var.")
        shape = self.shape()
        if not shape.is_valid or not shape.is_simple:
            raise ValueError(
                f"{self.name}: geçersiz/kendini kesen geometri: {explain_validity(shape)}"
            )
        if self.kind != "line" and shape.area <= 1e-12:
            raise ValueError(f"{self.name}: sıfır veya çok küçük alan.")
        if any(np.linalg.norm(np.subtract(a, b)) <= 1e-9 for a, b in self.segments()):
            raise ValueError(f"{self.name}: sıfır veya çok kısa kenar.")

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
            raise ValueError("Mesnet değerleri true/false olmalıdır.")
        if not np.isfinite(self.pressure):
            raise ValueError("Basınç sonlu olmalıdır.")


@dataclass(frozen=True)
class ConstructionStep:
    """One generated stage: regions excavated and supports installed in it.

    ``load_split`` < 1 stops an excavation stage early (stress-release/beta method); the
    rest of the unbalance is carried by the next stage, after its support is installed.
    """

    name: str
    excavate: tuple[str, ...] = ()
    install: tuple[str, ...] = ()
    load_split: float = 1.0

    def __post_init__(self):
        object.__setattr__(self, "excavate", tuple(self.excavate))
        object.__setattr__(self, "install", tuple(self.install))
        if not self.name.strip():
            raise ValueError("Aşama adı boş olamaz.")
        if not 0.0 < float(self.load_split) <= 1.0:
            raise ValueError("Destek öncesi yük oranı (0, 1] aralığında olmalıdır.")


@dataclass(frozen=True)
class Drawing:
    entities: tuple[Entity, ...] = ()
    rules: tuple[BoundaryRule, ...] = ()
    h: float = 1.0
    E: float = 20000.0
    nu: float = 0.3
    supports: tuple[SupportAssignment, ...] = ()
    sequence: tuple[ConstructionStep, ...] = ()

    def __post_init__(self):
        if not np.isfinite([self.h, self.E, self.nu]).all():
            raise ValueError("Ağ ve malzeme değerleri sonlu olmalıdır.")
        if self.h <= 0 or self.E <= 0 or not 0 <= self.nu < 0.5:
            raise ValueError("h ve E pozitif, 0 ≤ ν < 0.5 olmalıdır.")

    def to_dict(self):
        return {"version": 2, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        if data.get("version") not in (1, 2):
            raise ValueError("Desteklenmeyen CAD dosya sürümü.")
        return cls(
            tuple(Entity(**e) for e in data["entities"]),
            tuple(BoundaryRule(**r) for r in data.get("rules", [])),
            float(data["h"]),
            float(data["E"]),
            float(data["nu"]),
            tuple(SupportAssignment(**s) for s in data.get("supports", [])),
            tuple(ConstructionStep(**c) for c in data.get("sequence", [])),
        )

    def without_entity(self, name):
        """Drop an entity with its edge rules, support and construction-step references."""
        old = next(e for e in self.entities if e.name == name)
        steps = []
        for step in self.sequence:
            step = replace(
                step,
                excavate=tuple(n for n in step.excavate if n != name),
                install=tuple(n for n in step.install if n != name),
            )
            if step.excavate or step.install:
                steps.append(step)
        return replace(
            self,
            entities=tuple(e for e in self.entities if e.name != name),
            rules=tuple(r for r in self.rules if r.edge not in old.edge_names()),
            supports=tuple(s for s in self.supports if s.entity != name),
            sequence=tuple(steps),
        )

    def renamed(self, old, new):
        """Follow an entity rename in the construction sequence."""
        return replace(
            self,
            sequence=tuple(
                replace(
                    step,
                    excavate=tuple(new if n == old else n for n in step.excavate),
                    install=tuple(new if n == old else n for n in step.install),
                )
                for step in self.sequence
            ),
        )

    @classmethod
    def example(cls):
        return cls(
            (Entity("Zemin", "region", ((0, 0), (12, 0), (12, 6), (0, 6))),),
            (
                BoundaryRule("Zemin:1", True, True),
                BoundaryRule("Zemin:2", True),
                BoundaryRule("Zemin:3", pressure=50),
                BoundaryRule("Zemin:4", True),
            ),
        )

    def validate(self):
        names = [e.name for e in self.entities]
        if len(set(names)) != len(names):
            raise ValueError("Geometri adları benzersiz olmalıdır.")
        assigned = set()
        by_name = {e.name: e for e in self.entities}
        for support in self.supports:
            if support.entity not in by_name or support.entity in assigned:
                raise ValueError("Destek geometriye bağlı olmalı ve aynı nesneye bir kez atanmalı.")
            if support.kind in {"pile", "bolt"} and by_name[support.entity].kind != "line":
                raise ValueError("Kazık ve ankraj/çivi için çizgi geometrisi gereklidir.")
            assigned.add(support.entity)
        step_names = [step.name for step in self.sequence]
        if len(set(step_names)) != len(step_names):
            raise ValueError("Yapım aşaması adları benzersiz olmalıdır.")
        supported = {s.entity for s in self.supports}
        for step in self.sequence:
            for name in step.excavate:
                if name not in by_name or by_name[name].kind != "region":
                    raise ValueError(f"{step.name}: kazılacak bölge '{name}' bulunamadı.")
            for name in step.install:
                if name not in supported:
                    raise ValueError(f"{step.name}: yerleştirilecek destek '{name}' bulunamadı.")
        regions = [e for e in self.entities if e.kind == "region"]
        holes = [e for e in self.entities if e.kind == "hole"]
        if not regions:
            raise ValueError("En az bir kapalı malzeme bölgesi çizilmelidir.")
        polys = [e.shape() for e in regions]
        for i, a in enumerate(polys):
            for b in polys[i + 1 :]:
                if a.equals(b) or (
                    a.intersection(b).area > 1e-12 and not (a.covers(b) or b.covers(a))
                ):
                    raise ValueError(
                        "Bölgeler kısmen çakışıyor. Ortak kenar veya iç içe bölgeler kullanın."
                    )
        outer = unary_union(polys)
        voids = [e.shape() for e in holes]
        for i, hole in enumerate(voids):
            if not outer.contains(hole) or outer.boundary.intersects(hole):
                raise ValueError("Boşluk tamamen zemin içinde olmalı; dış sınıra değemez.")
            if any(hole.intersects(b) for b in voids[i + 1 :]):
                raise ValueError("Boşluklar kesişemez veya iç içe olamaz.")
            # Domain uses the innermost polygon: crossing layers/islands would be ambiguous.
            if any(hole.intersection(p).area > 1e-12 and not p.covers(hole) for p in polys):
                raise ValueError("Boşluk bir bölge sınırını kesemez veya bölge içeremez.")
        soil = outer.difference(unary_union(voids))
        for e in self.entities:
            if e.kind == "line" and not soil.covers(e.shape()):
                raise ValueError(f"{e.name}: çizgi zemin dışında veya boşluk içinde.")
        edge_names = {n for e in self.entities for n in e.edge_names()}
        seen = set()
        for rule in self.rules:
            if rule.edge not in edge_names or rule.edge in seen:
                raise ValueError(f"Geçersiz veya yinelenen kenar koşulu: {rule.edge}")
            seen.add(rule.edge)
            if not np.isfinite(rule.pressure):
                raise ValueError("Basınç sonlu olmalıdır.")
        return soil

    def split_with_line(self, points, name_prefix="Kazi") -> Drawing:
        """RS2-style excavation/layer line: subdivide existing region(s) into new region(s)."""
        pts = [tuple(float(v) for v in xy) for xy in points]
        if len(pts) < 2:
            raise ValueError("Bölme çizgisi en az 2 nokta gerektirir.")
        cutter = LineString(pts)
        if not cutter.is_valid or cutter.length <= 1e-6:
            raise ValueError("Bölme çizgisi geçersiz veya sıfır uzunluklu.")
        regions = [e for e in self.entities if e.kind == "region"]
        if not regions:
            raise ValueError("Önce bölünecek bir zemin bölgesi çizin.")
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
                "Çizgi herhangi bir bölgeyi iki kapalı parçaya ayırmadı. "
                "Çizgi uçlarını bölge sınırlarına veya kazığa birleştirin."
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

    def build_model(self, checkpoint=None):
        """Create a fresh weightless elastic model; never remap existing FE definitions."""
        mesh = unstructured_mesh(self.domain(), h=self.h, max_points=100000, checkpoint=checkpoint)
        if checkpoint:
            checkpoint()
        boundary = {tuple(sorted(e[:2])) for e in mesh.edge_sets["boundary"]}
        loads, fixities = [], []
        loaded = set()
        for r in self.rules:
            edges = mesh.edge_sets[r.edge]
            if (r.ux or r.uy or r.pressure) and edges.size == 0:
                raise ValueError(f"{r.edge}: koşul için ağ kenarı bulunamadı.")
            if r.ux or r.uy:
                fixities.append(api.Fixity(r.edge, r.ux, r.uy))
            if r.pressure:
                keys = {tuple(sorted(e[:2])) for e in edges}
                if not keys <= boundary:
                    raise ValueError(f"{r.edge}: basınç yalnız dış/boşluk sınırına atanabilir.")
                if keys & loaded:
                    raise ValueError(f"{r.edge}: aynı ağ kenarına iki basınç atanmış.")
                loaded.update(keys)
                loads.append(api.EdgeLoad(r.edge, qn=r.pressure))
        _check_supports(mesh, fixities)
        model = api.Model(
            api.Analysis.PLANE_STRAIN,
            mesh,
            {"soil": api.MaterialSpec.elastic("soil", self.E, self.nu)},
            {r: "soil" for r in mesh.regions()},
            fixities=tuple(fixities),
            # No structures in the initial state: pile skin interfaces stay tied (continuous).
            initial=api.InitialStress("none", active_structures=frozenset()),
            stages=[api.Stage("CAD yükleme", loads=tuple(loads))],
            geometry=self.to_dict(),
        )
        model = compile_supports(model, self)
        model = replace(model, stages=[*model.stages, *self.sequence_stages(model)])
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
        stages = []
        for step in self.sequence:
            excavated.update(by_name[n].region for n in step.excavate)
            for name in step.install:
                support = tags[name]
                installed.add(support.tag)
                installed.update(t for t in companion_tags(support.tag) if t in model.interfaces)
            stages.append(
                api.Stage(
                    step.name,
                    active_regions=frozenset(model.mesh.regions() - excavated),
                    active_structures=frozenset(installed),
                    loads=base.loads,
                    load_split=step.load_split,
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
                f"Zemin parçası {k + 1}: mesnetler rijit hareketi önlemiyor. "
                "Kenar tablosunda ux/uy mesnetlerini tamamlayın."
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
            return tuple(q[j]), "Nokta/orta nokta"
    if grid > 0:
        return tuple(np.round(p / grid) * grid), "Izgara"
    return tuple(p), "Serbest"
