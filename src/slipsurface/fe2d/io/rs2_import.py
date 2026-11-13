"""Conservative reader for RS2 .fea and .fez files.

This first pass imports continuum triangles, peak Mohr-Coulomb properties, stage
activation/material reassignment and nodal restraints. Unsupported initial stress,
beam and bolt semantics are reported rather than silently approximated.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..core.enums import Analysis, ElemType
from ..model import (
    ElementBlock,
    Fixity,
    InitialStress,
    MaterialSpec,
    Mesh,
    Model,
    SolverSettings,
    Stage,
)


class RS2ImportError(ValueError):
    """Malformed RS2 file or unsupported core format."""


@dataclass(frozen=True)
class RS2ImportReport:
    source: str
    units: str
    nodes: int
    continuum_elements: int
    materials: int
    stages: int
    beam_elements: int
    bolt_groups: int
    unsupported_features: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def analysis_ready(self) -> bool:
        return not self.unsupported_features


@dataclass(frozen=True)
class RS2ImportResult:
    model: Model
    report: RS2ImportReport


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _read_fea(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".fez":
        try:
            with zipfile.ZipFile(path) as archive:
                candidates = [n for n in archive.namelist() if n.lower().endswith(".fea")]
                if len(candidates) != 1:
                    raise RS2ImportError(
                        f"Expected exactly one .fea model in .fez; found {len(candidates)}"
                    )
                return archive.read(candidates[0]).decode("latin1"), candidates[0]
        except (zipfile.BadZipFile, OSError) as exc:
            raise RS2ImportError(f"Cannot read RS2 archive: {exc}") from exc
    try:
        return path.read_text(encoding="latin1"), path.name
    except OSError as exc:
        raise RS2ImportError(f"Cannot read RS2 model: {exc}") from exc


def _section(text: str, start: str, end: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RS2ImportError(f"Missing RS2 section: {start}")
    a += len(start)
    b = text.find(end, a)
    if b < 0:
        raise RS2ImportError(f"Missing RS2 section terminator: {end}")
    return text[a:b]


def _material_specs(text: str) -> dict[str, MaterialSpec]:
    section = _section(text, "material types:", "element types:")
    starts = list(re.finditer(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*formulation:\s*([^\s]+)", section
    ))
    specs: dict[str, MaterialSpec] = {}
    for i, match in enumerate(starts):
        stop = starts[i + 1].start() if i + 1 < len(starts) else len(section)
        raw = section[match.start():stop]
        if match.group(2).lower() != "mohr_coulomb":
            continue
        values = {
            key.lower(): float(value)
            for key, value in re.findall(
                rf"([A-Za-z][A-Za-z0-9_]*)\s*:\s*({_NUMBER})", raw
            )
        }
        required = ("e", "nu", "c", "phi")
        missing = [key for key in required if key not in values]
        if missing:
            raise RS2ImportError(f"Material {match.group(1)} is missing {missing}")
        # RS2 Metric MPa -> SlipSurface kPa; density MN/m3 -> kN/m3.
        specs[match.group(1)] = MaterialSpec.mohr_coulomb(
            match.group(1),
            E=values["e"] * 1000.0,
            nu=values["nu"],
            c=values["c"] * 1000.0,
            phi=values["phi"],
            psi=values.get("dil", 0.0),
            sig_t=values.get("t", 0.0) * 1000.0,
            gamma=values.get("rho", 0.0) * 1000.0,
        )
    if not specs:
        raise RS2ImportError("No supported Mohr-Coulomb continuum materials found")
    return specs


def _node_data(text: str) -> dict[int, tuple[float, float]]:
    section = _section(text, "nodes:  total:", "elements:  total:")
    rows = re.findall(
        rf"(?m)^\s*(\d+)\s+x:\s*({_NUMBER})\s+y:\s*({_NUMBER})\s*$", section
    )
    nodes = {int(i): (float(x), float(y)) for i, x, y in rows}
    if len(nodes) < 3:
        raise RS2ImportError("RS2 node section contains fewer than three usable nodes")
    return nodes


def _element_data(text: str) -> list[tuple[int, tuple[int, int, int], str]]:
    section = _section(text, "elements:  total:", "\nsprings:")
    rows = re.findall(
        r"(?m)^\s*(\d+)\s+type:\s*cst_element\s+nodes:\s*\[([^]]+)\]\s+material:\s*(\w+)",
        section,
    )
    elements = []
    for element_id, node_text, material in rows:
        ids = tuple(int(v.strip()) for v in node_text.split(","))
        if len(ids) != 3:
            raise RS2ImportError(f"Element {element_id} is not a 3-node triangle")
        elements.append((int(element_id), ids, material))
    if not elements:
        raise RS2ImportError("No linear triangular continuum elements found")
    return elements


def _stage_sections(text: str, count: int) -> list[str]:
    matches = list(re.finditer(r"(?m)^#stage\s+(\d+)\s+data\s*$", text))
    sections = []
    for stage in range(1, count + 1):
        if stage == 1:
            next_start = next(
                (m.start() for m in matches if int(m.group(1)) == 2), len(text)
            )
            sections.append(text[:next_start])
            continue
        current = next((m for m in matches if int(m.group(1)) == stage), None)
        if current is None:
            raise RS2ImportError(f"Missing stage {stage} data")
        following = next(
            (m.start() for m in matches if int(m.group(1)) == stage + 1), len(text)
        )
        sections.append(text[current.end():following])
    return sections


def _stage_names(text: str, count: int) -> list[str]:
    match = re.search(
        r"(?ms)^stage_names:\s*number:\s*(\d+)\s*\n(.*?)(?=\n\S[^\n]*:|\Z)", text
    )
    if match:
        names = [line.strip() for line in match.group(2).splitlines() if line.strip()]
        if len(names) >= count:
            return names[:count]
    return [f"Stage {i}" for i in range(1, count + 1)]


def _named_section(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\s*:\s*(.*?)(?=^\S[^\n]*:\s*$|^#stage|\Z)", text
    )
    return match.group(1) if match else ""


def _restraints(text: str, node_map: dict[int, int]):
    start = text.find("restraints:")
    if start < 0:
        return (), {}
    stop_candidates = [
        text.find(token, start + 1)
        for token in ("load curve:", "set:", "#stage 2 data")
    ]
    stop_candidates = [v for v in stop_candidates if v >= 0]
    stop = min(stop_candidates) if stop_candidates else len(text)
    groups: dict[tuple[bool, bool], list[int]] = {}
    for node, tail in re.findall(r"(?m)^\s*n:\s*(\d+)([^\n]*)", text[start:stop]):
        values = dict(re.findall(r"(t[xy])\s*:\s*(-?\d+)", tail))
        ux, uy = values.get("tx") == "0", values.get("ty") == "0"
        if (ux or uy) and int(node) in node_map:
            groups.setdefault((ux, uy), []).append(node_map[int(node)])
    sets, fixities = {}, []
    for i, ((ux, uy), ids) in enumerate(sorted(groups.items()), 1):
        name = f"rs2_restraint_{i}"
        sets[name] = np.asarray(sorted(set(ids)), dtype=np.int64)
        fixities.append(Fixity(name, ux, uy))
    return tuple(fixities), sets


def import_rs2(path: str | Path) -> RS2ImportResult:
    """Import the supported continuum portion of an RS2 .fea or .fez file.

    The returned model is a preview unless report.analysis_ready is true. This
    importer does not approximate element-wise initial stress, beam liners or
    bonded-bolt grout transfer.
    """
    source_path = Path(path)
    text, member = _read_fea(source_path)
    if "option: plane strain" not in text.lower():
        raise RS2ImportError("Only RS2 plane-strain models are currently supported")
    units_match = re.search(r"(?mi)^RFCunits:\s*(.+)$", text)
    units = units_match.group(1).strip() if units_match else "unknown"
    if units.lower() != "metric mpa":
        raise RS2ImportError(f"Unsupported RS2 unit system: {units}")

    count_match = re.search(r"(?mi)^stages:\s*(\d+)", text)
    stage_count = int(count_match.group(1)) if count_match else 1
    nodes = _node_data(text)
    elements = _element_data(text)
    materials = _material_specs(text)
    unknown = sorted({mat for _, _, mat in elements} - set(materials))
    if unknown:
        raise RS2ImportError(f"Elements reference unsupported materials: {unknown}")

    node_ids = sorted(nodes)
    node_map = {node_id: i for i, node_id in enumerate(node_ids)}
    coords = np.asarray([nodes[node_id] for node_id in node_ids], dtype=float)
    conn = np.asarray([[node_map[n] for n in ns] for _, ns, _ in elements], dtype=np.int64)
    element_ids = [eid for eid, _, _ in elements]
    regions = np.asarray(element_ids, dtype=np.int32)
    base_material = {eid: mat for eid, _, mat in elements}
    block = ElementBlock(ElemType.T3, conn, regions, "rs2_continuum")
    fixities, node_sets = _restraints(text, node_map)
    mesh = Mesh(coords, (block,), node_sets=node_sets)

    stage_texts = _stage_sections(text, stage_count)
    names = _stage_names(text, stage_count)
    deleted: set[int] = set()
    stages = []
    for index, stage_text in enumerate(stage_texts):
        delete_section = _named_section(stage_text, "delete")
        deleted.update(
            int(v) for v in re.findall(r"(?m)^\s*element:\s*(\d+)\s*$", delete_section)
        )
        set_section = _named_section(stage_text, "set")
        overrides = {
            int(eid): material
            for eid, material in re.findall(
                r"(?m)^\s*element:\s*(\d+)\s+material:\s*(\w+)", set_section
            )
            if int(eid) in base_material and material in materials
        }
        active = frozenset(eid for eid in element_ids if eid not in deleted)
        stages.append(Stage(name=names[index], active_regions=active, material_override=overrides))

    model = Model(
        analysis=Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials=materials,
        region_material=base_material,
        fixities=fixities,
        initial=InitialStress(mode="gravity"),
        stages=stages,
        settings=SolverSettings(method="initial", max_iter=500, tol_force=1e-3),
    )
    model.validate()

    beam_ids = set(re.findall(
        r"(?m)^\s*(\d+)\s+type:\s*l_beam\w*\s+nodes:", text
    ))
    bolt_ids = set(re.findall(
        r"(?m)^\s*(\d+)\s+type:\s*(?:bonded_bolt|bolt_element|queens_bolt|shear_bolt)",
        text,
    ))
    beam_count, bolt_groups = len(beam_ids), len(bolt_ids)
    unsupported = []
    if re.search(r"(?m)^\s*e:\s*\d+\s+sxx:", text):
        unsupported.append("element-wise initial stress field")
    if beam_count:
        unsupported.append(f"{beam_count} RS2 beam/liner elements")
    if bolt_groups:
        unsupported.append(f"{bolt_groups} RS2 bolt groups and bond-transfer laws")
    report = RS2ImportReport(
        source=f"{source_path.name}:{member}" if source_path.suffix.lower() == ".fez"
        else source_path.name,
        units=units,
        nodes=len(nodes),
        continuum_elements=len(elements),
        materials=len(materials),
        stages=stage_count,
        beam_elements=beam_count,
        bolt_groups=bolt_groups,
        unsupported_features=tuple(unsupported),
        warnings=(
            "Metric MPa values were converted to kPa and MN/m3 densities to kN/m3.",
            "Peak Mohr-Coulomb properties are imported; residual properties are not.",
            "Only continuum stage deletion and material reassignment are transferred.",
            "RS2 result files are not imported as SlipSurface solver results.",
            "Do not treat this preview as analysis-equivalent while features remain unsupported.",
        ),
    )
    return RS2ImportResult(model, report)
