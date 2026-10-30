"""NATM tunnel sections, composite shotcrete linings and rock-bolt patterns for the CAD.

A section is drawn about its springline centre ``(0, 0)``:

* crown: circular arc of radius ``radius`` above the springline,
* side walls (NATM): arcs of radius ``wall_radius`` tangent to the crown at the springline,
  down to ``-wall_height``,
* invert: arc through both wall feet with sag ``invert_depth`` (0 = flat).

A circular section is the special case ``wall_height = 0`` with a half-circle invert.
The section is split into top heading / bench / invert at ``heading_level`` and
``invert_level``; each part becomes its own excavation region with its own shotcrete
liner and bolts, and :func:`place_tunnel` writes the matching construction sequence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split

from .geometry import ConstructionStep, Drawing, Entity
from .lining import STEEL_RIBS, WIRE_MESH, LiningSystem  # noqa: F401  re-exported
from .supports import SupportAssignment

PART_LABELS = {"heading": "Üst yarı", "bench": "Alt yarı", "invert": "İnvert", "full": "Tam kesit"}
PART_KEYS = {"heading": "Ust", "bench": "Alt", "invert": "Inv", "full": "Tam"}


@dataclass(frozen=True)
class TunnelSection:
    name: str = "NATM"
    shape: str = "natm"  # natm | circle
    radius: float = 5.0
    wall_radius: float = 9.0
    wall_height: float = 2.0
    invert_depth: float = 1.2
    heading_level: float = 0.0  # top heading / bench split, relative to the springline
    invert_level: float = -2.0  # bench / invert split, relative to the springline
    parts: int = 3  # 1 full face, 2 heading + bench, 3 heading + bench + invert
    segments: int = 48

    def __post_init__(self):
        if self.shape not in {"natm", "circle"}:
            raise ValueError("Kesit türü natm veya circle olmalıdır.")
        values = [self.radius, self.wall_radius, self.wall_height, self.invert_depth]
        if not np.isfinite([*values, self.heading_level, self.invert_level]).all():
            raise ValueError("Kesit ölçüleri sonlu olmalıdır.")
        if self.radius <= 0 or self.parts not in (1, 2, 3) or not 12 <= self.segments <= 400:
            raise ValueError("Yarıçap pozitif, bölüm sayısı 1-3, segment 12-400 olmalıdır.")
        if self.shape == "natm":
            if self.wall_radius < self.radius or not 0 <= self.wall_height < self.wall_radius:
                raise ValueError("Yan duvar yarıçapı ≥ tepe yarıçapı ve > duvar yüksekliği olmalı.")
            if self.invert_depth < 0:
                raise ValueError("İnvert derinliği negatif olamaz.")
        bottom, top = self.bounds_y()
        if self.parts >= 2 and not bottom < self.heading_level < top:
            raise ValueError("Üst yarı seviyesi kesit içinde olmalıdır.")
        if self.parts == 3 and not bottom < self.invert_level < self.heading_level:
            raise ValueError("İnvert seviyesi tabanla üst yarı seviyesi arasında olmalıdır.")

    def bounds_y(self):
        if self.shape == "circle":
            return -self.radius, self.radius
        return -self.wall_height - self.invert_depth, self.radius

    def outline(self):
        """Closed outline (counter-clockwise, no repeated point) about the springline centre."""
        R = self.radius
        if self.shape == "circle":
            n = self.segments
            a = np.linspace(0, 2 * np.pi, n, endpoint=False)
            return np.column_stack([R * np.cos(a), R * np.sin(a)])
        R2, h, d = self.wall_radius, self.wall_height, self.invert_depth
        cx = R - R2  # right wall centre (left wall mirrored)
        t_end = -np.arcsin(h / R2) if h > 0 else 0.0
        xb = cx + R2 * np.cos(t_end)
        lengths = [np.pi * R, R2 * abs(t_end)]
        if d > 1e-9:
            Ri = (xb**2 + d**2) / (2 * d)
            yc = -h - d + Ri
            a0, a1 = np.arctan2(-h - yc, -xb), np.arctan2(-h - yc, xb)
            lengths.append(Ri * (a1 - a0))
        else:
            lengths.append(2 * xb)
        ds = sum(lengths[:1]) / max(self.segments // 2, 6)

        def count(length):
            return max(int(np.ceil(length / ds)), 1)

        pts = []
        a = np.linspace(0, np.pi, count(np.pi * R) + 1)[:-1]  # right springline -> crown
        pts += list(np.column_stack([R * np.cos(a), R * np.sin(a)]))
        if h > 0:  # left wall, springline -> foot
            t = np.linspace(0, t_end, count(R2 * abs(t_end)) + 1)[:-1]
            pts += list(np.column_stack([-(cx + R2 * np.cos(t)), R2 * np.sin(t)]))
        if d > 1e-9:  # invert, left foot -> right foot
            a = np.linspace(a0, a1, count(Ri * (a1 - a0)) + 1)[:-1]
            pts += list(np.column_stack([Ri * np.cos(a), yc + Ri * np.sin(a)]))
        else:
            x = np.linspace(-xb, xb, count(2 * xb) + 1)[:-1]
            pts += list(np.column_stack([x, np.full_like(x, -h)]))
        if h > 0:  # right wall, foot -> springline
            t = np.linspace(t_end, 0, count(R2 * abs(t_end)) + 1)[:-1]
            pts += list(np.column_stack([cx + R2 * np.cos(t), R2 * np.sin(t)]))
        return np.asarray(pts)

    def part_names(self):
        return {1: ["full"], 2: ["heading", "bench"], 3: ["heading", "bench", "invert"]}[self.parts]

    def parts_at(self, center=(0.0, 0.0)):
        """``{part: polygon points}`` translated to ``center``; neighbours share cut points."""
        ring = _rounded(self.outline() + np.asarray(center, float))
        polygon = Polygon(ring)
        cy = float(center[1])
        levels = []
        if self.parts >= 2:
            levels.append(cy + self.heading_level)
        if self.parts == 3:
            levels.append(cy + self.invert_level)
        pieces = [polygon]
        x0, _, x1, _ = polygon.bounds
        for level in levels:
            cutter = LineString([(x0 - 1, level), (x1 + 1, level)])
            pieces = [g for p in pieces for g in split(p, cutter).geoms]
        pieces.sort(key=lambda g: -g.centroid.y)
        out = {}
        for key, piece in zip(self.part_names(), pieces):
            out[key] = _clean(_rounded(np.asarray(piece.exterior.coords[:-1])))
        return out

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class BoltPattern:
    """Radial rock bolts over an angular range (degrees from +x, counter-clockwise).

    The bolt count is derived from the arc length and ``spacing`` (m along the
    excavation contour): ``count = max(1, round(arc / spacing))``, then spread evenly
    between ``start_angle`` and ``end_angle``. A legacy explicit ``count`` still wins.
    """

    count: int | None = None  # legacy explicit count; None -> derive from spacing
    length: float = 4.0
    start_angle: float = 20.0
    end_angle: float = 160.0
    spacing: float = 1.5  # m along the contour between bolts (used when count is None)
    EA: float = 1e5  # kN per bolt
    T_yield: float = 250.0  # kN per bolt
    spacing_out_of_plane: float = 1.5
    pretension: float = 0.0

    def __post_init__(self):
        if self.count is not None and self.count < 0:
            raise ValueError("Bulon sayısı ≥ 0 olmalıdır.")
        if self.length <= 0 or self.EA <= 0 or self.T_yield <= 0:
            raise ValueError("Boy, EA ve akma kuvveti pozitif olmalıdır.")
        if self.spacing <= 0 or self.spacing_out_of_plane <= 0 or self.pretension < 0:
            raise ValueError("Aralıklar pozitif, öngerme negatif olamaz.")

    def bolt_count(self, arc_length: float | None = None) -> int:
        """Number of bolts on an arc of ``arc_length`` metres."""
        if self.count is not None:
            return self.count
        span = arc_length if arc_length is not None else np.radians(
            abs(self.end_angle - self.start_angle)
        )
        return max(1, int(round(span / self.spacing)))

    def angles(self, arc_length: float | None = None):
        n = self.bolt_count(arc_length)
        if n == 0:
            return np.empty(0)
        if n == 1:
            return np.array([(self.start_angle + self.end_angle) / 2])
        return np.linspace(self.start_angle, self.end_angle, n)

    def properties(self):
        return dict(EA=self.EA, T_yield=self.T_yield, pretension=self.pretension,
                    spacing_out_of_plane=self.spacing_out_of_plane)  # fmt: skip

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if "spacing" not in data:  # legacy file without a contour-spacing field
            data["spacing"] = data.get("spacing_out_of_plane", 1.5)
        return cls(**data)


@dataclass(frozen=True)
class PartBolts:
    """Bolt patterns of one tunnel: a shared ``pattern`` plus optional per-part
    overrides in ``per_part`` (part key -> BoltPattern | None; None = no bolts there)."""

    pattern: BoltPattern | None = field(default_factory=BoltPattern)
    per_part: dict = field(default_factory=dict)

    def for_part(self, key):
        return self.per_part.get(key, self.pattern)

    def to_dict(self):
        return {
            "pattern": None if self.pattern is None else self.pattern.to_dict(),
            "per_part": {
                k: (None if v is None else v.to_dict()) for k, v in self.per_part.items()
            },
        }

    @classmethod
    def from_dict(cls, data):
        if isinstance(data, dict) and "pattern" in data:
            return cls(
                None if data.get("pattern") is None else BoltPattern.from_dict(data["pattern"]),
                {
                    k: (None if v is None else BoltPattern.from_dict(v))
                    for k, v in (data.get("per_part") or {}).items()
                },
            )
        return cls(BoltPattern.from_dict(data), {})  # legacy: one pattern for all parts


@dataclass(frozen=True)
class TunnelDesign:
    section: TunnelSection = field(default_factory=TunnelSection)
    lining: LiningSystem | None = field(default_factory=LiningSystem)
    bolts: PartBolts | BoltPattern | None = field(default_factory=PartBolts)
    load_split: float = 0.5  # share of the excavation unbalance released before support
    separate_support_stage: bool = True

    def part_bolts(self):
        """``PartBolts`` of this design (a legacy BoltPattern becomes the shared one)."""
        if self.bolts is None or isinstance(self.bolts, PartBolts):
            return self.bolts
        return PartBolts(self.bolts, {})

    def to_dict(self):
        bolts = self.part_bolts()
        return {
            "section": self.section.to_dict(),
            "lining": None if self.lining is None else self.lining.to_dict(),
            "bolts": None if bolts is None else bolts.to_dict(),
            "load_split": self.load_split,
            "separate_support_stage": self.separate_support_stage,
        }

    @classmethod
    def from_dict(cls, data):
        bolts = data.get("bolts")
        return cls(
            TunnelSection(**data["section"]),
            None if data.get("lining") is None else LiningSystem(**data["lining"]),
            None if bolts is None else PartBolts.from_dict(bolts),
            float(data.get("load_split", 0.5)),
            bool(data.get("separate_support_stage", True)),
        )


def _rounded(points):
    return np.round(np.asarray(points, float), 9) + 0.0  # + 0.0 drops negative zeros


def _clean(points):
    out = []
    for p in map(tuple, points):
        if not out or np.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-7:
            out.append(p)
    if len(out) > 1 and np.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1e-7:
        out.pop()
    return out


def _lining_chains(points, cut_levels):
    """Open chains of a part's boundary without its straight cut edges."""
    n = len(points)
    on_cut = [
        any(abs(points[i][1] - y) < 1e-7 and abs(points[(i + 1) % n][1] - y) < 1e-7
            for y in cut_levels)
        for i in range(n)
    ]  # fmt: skip
    if not any(on_cut):  # full face: two halves (a line entity cannot be closed)
        half = n // 2
        return [points[: half + 1], [*points[half:], points[0]]]
    start = on_cut.index(True)
    chains, chain = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        chain.append(points[i])
        if on_cut[i]:
            if len(chain) >= 2:
                chains.append(chain)
            chain = []
    return chains


def _unique(prefix, names):
    """``prefix`` (or ``prefix2``, ``prefix3`` ...) not yet used by a name or a name stem."""

    def taken(stem):
        return any(n == stem or n.startswith(f"{stem}_") for n in names)

    if not taken(prefix):
        return prefix
    n = 2
    while taken(f"{prefix}{n}"):
        n += 1
    return f"{prefix}{n}"


def _ring_arclength(ring, center):
    """Unwrapped angle (rad, from ring[0] around ``center``) and cumulative arc length."""
    c = np.asarray(center, float)
    pts = np.vstack([ring, ring[:1]])
    ang = np.unwrap(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    return ang, np.concatenate([[0.0], np.cumsum(seg)])


def _chain_segs(chains):
    """Flatten boundary chains into ``(a, b, length, s_start)`` segments and total length."""
    segs, total = [], 0.0
    for chain in chains:
        arr = np.asarray(chain, float)
        for a, b in zip(arr[:-1], arr[1:]):
            length = float(np.linalg.norm(b - a))
            segs.append((a, b, length, total))
            total += length
    return segs, total


def _point_at(segs, total, s):
    s = min(max(float(s), 0.0), total)
    for i, (a, b, length, s0) in enumerate(segs):
        if s <= s0 + length or i == len(segs) - 1:
            t = 0.0 if length == 0 else (s - s0) / length
            return a + t * (b - a)
    return segs[-1][1]


def _part_bolt_heads(pattern, ring, center, radius, chains, part_key):
    """``(head, direction)`` per bolt of one excavation part.

    The head is the outline vertex nearest to the ray from the tunnel centre, so the
    mesh stays conforming without T-junctions. For a split part (heading/bench/invert)
    bolts are spread at equal arc-length stations over the part's excavation contour
    (its boundary without the cut lines); for a full-face section they are spread over
    the angular range ``start_angle..end_angle`` of the whole outline. The count comes
    from ``pattern.bolt_count(arc)``.
    """
    if pattern is None:
        return []
    c = np.asarray(center, float)
    if part_key == "full":
        a0, a1 = np.radians(pattern.start_angle), np.radians(pattern.end_angle)
        if a1 <= a0:
            a1 += 2 * np.pi
        ang, s = _ring_arclength(ring, c)
        s0, s1 = np.interp([a0, a1], ang, s)
        arc = float(s1 - s0)
        n = pattern.bolt_count(arc)
        if n == 0:
            return []
        stations = np.array([0.5 * (s0 + s1)]) if n == 1 else np.linspace(s0, s1, n)
        pts = np.column_stack([np.interp(stations, s, ring[:, 0]),
                               np.interp(stations, s, ring[:, 1])])
    else:
        segs, total = _chain_segs(chains)
        if total <= 0:
            return []
        n = pattern.bolt_count(total)
        if n == 0:
            return []
        stations = (np.arange(n) + 0.5) * total / n
        pts = np.array([_point_at(segs, total, s) for s in stations])
    outline = Polygon(ring).exterior
    origin = Point(c)
    out = []
    for p in pts:
        d = p - c
        length = float(np.linalg.norm(d))
        if length < 1e-12:
            continue
        direction = d / length
        hit = LineString([tuple(c), tuple(c + direction * 40 * radius)]).intersection(outline)
        if hit.is_empty:
            continue
        point = hit if hit.geom_type == "Point" else min(hit.geoms, key=origin.distance)
        head = ring[np.argmin(np.linalg.norm(ring - np.asarray(point.coords[0]), axis=1))]
        out.append((head, direction))
    return out


def _bolt_heads(pattern, ring, center, radius):
    """Bolt heads of a full-face section (angular range of ``pattern``)."""
    return _part_bolt_heads(pattern, ring, center, radius, None, "full")


def place_tunnel(drawing: Drawing, design: TunnelDesign, center, name="Tunel") -> Drawing:
    """Add the tunnel parts, liners, bolts and the NATM construction sequence to ``drawing``."""
    section = design.section
    center = (float(center[0]), float(center[1]))
    names = {e.name for e in drawing.entities}
    name = _unique(name, names)
    parts = section.parts_at(center)
    cut_levels = [center[1] + section.heading_level, center[1] + section.invert_level][
        : section.parts - 1
    ]
    next_region = max((e.region for e in drawing.entities if e.kind == "region"), default=0) + 1
    entities, supports, steps = [], [], []
    ring = _rounded(section.outline() + np.asarray(center))
    bolts_cfg = design.part_bolts()
    heads_by_part = {}
    for key, points in parts.items():
        pattern = bolts_cfg.for_part(key) if bolts_cfg is not None else None
        if pattern is not None:
            chains = _lining_chains(points, cut_levels)
            heads_by_part[key] = _part_bolt_heads(
                pattern, ring, center, section.radius, chains, key
            )
    claimed: set[tuple] = set()
    for key, points in parts.items():
        region_name = f"{name}_{PART_KEYS[key]}"
        entities.append(Entity(region_name, "region", tuple(points), next_region))
        next_region += 1
        installed = []
        if design.lining is not None:
            chains = _lining_chains(points, cut_levels)
            if section.parts > 1 and len(chains) == 2:  # bench walls: left, then right
                chains.sort(key=lambda c: float(np.mean([p[0] for p in c])))
                suffixes = ["_Sol", "_Sag"]
            else:
                suffixes = [""] if len(chains) == 1 else [f"_{i + 1}" for i in range(len(chains))]
            for chain, suffix in zip(chains, suffixes):
                liner = f"{name}_PB_{PART_KEYS[key]}{suffix}"
                entities.append(Entity(liner, "line", tuple(map(tuple, chain))))
                supports.append(
                    SupportAssignment(liner, "liner", design.lining.liner_properties(), False)
                )
                installed.append(liner)
        vertices = {tuple(p) for p in points}
        pattern = bolts_cfg.for_part(key) if bolts_cfg is not None else None
        for j, (head, direction) in enumerate(heads_by_part.get(key, [])):
            if tuple(head) in claimed or tuple(head) not in vertices:
                continue  # a head on a cut point goes with the first (upper) part
            claimed.add(tuple(head))
            assert pattern is not None  # heads exist only with a bolt pattern
            tail = _rounded(head + direction * pattern.length)
            bolt = f"{name}_Bulon_{PART_KEYS[key]}{j + 1}"
            entities.append(Entity(bolt, "line", (tuple(head), tuple(tail))))
            supports.append(SupportAssignment(bolt, "bolt", pattern.properties(), False))
            installed.append(bolt)
        label = PART_LABELS[key]
        if design.separate_support_stage and installed:
            steps.append(
                ConstructionStep(f"{name} {label} kazı", (region_name,), (), design.load_split)
            )
            steps.append(ConstructionStep(f"{name} {label} destek", (), tuple(installed)))
        else:
            steps.append(ConstructionStep(f"{name} {label} kazı", (region_name,), tuple(installed)))
    updated = replace(
        drawing,
        entities=(*drawing.entities, *entities),
        supports=(*drawing.supports, *supports),
        sequence=(*drawing.sequence, *steps),
    )
    updated.validate()
    return updated


def bolt_pattern_along(drawing: Drawing, entity_name, count, length, angle=90.0,
                       pattern=None, prefix="Bulon", margin=0.0):  # fmt: skip
    """Bolts at ``count`` equally spaced stations of a line/edge chain, turned ``angle``
    degrees (counter-clockwise) from its direction; ``margin`` keeps them off the ends."""
    entity = next(e for e in drawing.entities if e.name == entity_name)
    pts = np.asarray(entity.points if entity.kind == "line" else (*entity.points, entity.points[0]))
    seg = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(seg, axis=1)
    station = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = station[-1]
    if count < 1 or length <= 0 or not 0 <= margin < total / 2:
        raise ValueError(
            "Bulon sayısı ≥ 1, boy pozitif ve kenar payı yarı uzunluktan küçük olmalıdır."
        )
    s_values = (np.array([total / 2]) if count == 1
                else np.linspace(margin, total - margin, count))  # fmt: skip
    pattern = pattern or BoltPattern()
    names = {e.name for e in drawing.entities}
    entities, supports = [], []
    vertices = {tuple(p) for p in map(tuple, _rounded(pts))}
    new_points = list(map(tuple, pts[:-1] if entity.kind != "line" else pts))
    for s in s_values:
        k = min(int(np.searchsorted(station, s, side="right")) - 1, len(seg) - 1)
        t = (s - station[k]) / max(seg_len[k], 1e-30)
        head = _rounded(pts[k] + t * seg[k])
        d = seg[k] / max(seg_len[k], 1e-30)
        c, sn = np.cos(np.radians(angle)), np.sin(np.radians(angle))
        direction = np.array([c * d[0] - sn * d[1], sn * d[0] + c * d[1]])
        tail = _rounded(head + direction * length)
        n = 1
        while f"{prefix}_{entity_name}_{n}" in names:
            n += 1
        bolt = f"{prefix}_{entity_name}_{n}"
        names.add(bolt)
        entities.append(Entity(bolt, "line", (tuple(head), tuple(tail))))
        supports.append(SupportAssignment(bolt, "bolt", pattern.properties()))
        if tuple(head) not in vertices:
            vertices.add(tuple(head))
            new_points.append((k, t, tuple(head)))
    # Insert the bolt heads as vertices of the host so the mesh stays conforming.
    base = list(map(tuple, entity.points))
    inserts = sorted((p for p in new_points if len(p) == 3), key=lambda p: (p[0], p[1]))
    out: list = []
    for i, point in enumerate(base):
        out.append(point)
        out.extend(h for k, t, h in inserts if k == i and 0 < t < 1)
    host = replace(entity, points=tuple(out))
    updated = replace(
        drawing,
        entities=tuple(host if e.name == entity_name else e for e in drawing.entities)
        + tuple(entities),
        supports=(*drawing.supports, *supports),
    )
    if len(out) != len(base):
        # The host's edge numbering changed: drop its stale edge rules.
        updated = replace(
            updated, rules=tuple(r for r in updated.rules if r.edge not in entity.edge_names())
        )
    updated.validate()
    return updated
