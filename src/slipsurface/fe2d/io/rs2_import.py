"""Conservative reader for RS2 .fea and .fez files.

Imports supported continuum triangles, peak Mohr-Coulomb properties, element-wise
initial stresses, staged Euler-Bernoulli beams and nodal restraints. Unsupported
body forces, residual properties, beam joint parameters and bolt transfer are reported.
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
    LinerSpec,
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


def _stage_body_forces(
    stage_texts: list[str], element_ids: list[int]
) -> list[dict[int, tuple[float, float]]]:
    """Read RS2 body-force edits as cumulative (bx, by) volume-force fields."""
    current: dict[int, tuple[float, float]] = {}
    allowed = set(element_ids)
    snapshots = []
    for stage_index, stage_text in enumerate(stage_texts, start=1):
        section = _named_section(stage_text, "body forces")
        for line in section.splitlines():
            match = re.match(r"^\s*e:\s*(\d+)\s+(.*)$", line)
            if not match:
                continue
            element_id = int(match.group(1))
            values = {
                key: float(value)
                for key, value in re.findall(
                    rf"\b(bx|by):\s*({_NUMBER})", match.group(2)
                )
            }
            if not values:
                continue
            if element_id not in allowed:
                raise RS2ImportError(
                    f"Stage {stage_index} body force references unknown continuum "
                    f"element {element_id}"
                )
            bx, by = current.get(element_id, (0.0, 0.0))
            current[element_id] = (
                values.get("bx", bx) * (1000.0 if "bx" in values else 1.0),
                values.get("by", by) * (1000.0 if "by" in values else 1.0),
            )
        snapshots.append(dict(current))
    return snapshots


def _bolt_group_count(text: str) -> int:
    section_start = text.rfind("bolts start:")
    if section_start < 0:
        return 0
    section_end = text.find("bolts end:", section_start)
    if section_end < 0:
        return 0
    section = text[section_start:section_end]
    count = re.search(r"(?mi)^\s*num bolts:\s*(\d+)", section)
    if count:
        return int(count.group(1))
    return len(re.findall(r"(?mi)^\s*bolt\s+\d+\s+start:\s*$", section))


def _initial_stresses(
    stage_one: str, element_ids: list[int]
) -> dict[int, tuple[float, float, float, float]]:
    section = _named_section(stage_one, "stresses")
    rows = re.findall(
        rf"(?m)^\s*e:\s*(\d+)\s+sxx:\s*({_NUMBER})\s+syy:\s*({_NUMBER})"
        rf"\s+sxy:\s*({_NUMBER})\s+szz:\s*({_NUMBER})",
        section,
    )
    values = {
        int(eid): (float(sxx) * 1000.0, float(syy) * 1000.0,
                   float(szz) * 1000.0, float(sxy) * 1000.0)
        for eid, sxx, syy, sxy, szz in rows
    }
    return {eid: values[eid] for eid in element_ids if eid in values}


def _residual_property_differences(text: str) -> tuple[str, ...]:
    section = _section(text, "material types:", "element types:")
    starts = list(re.finditer(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*formulation:\s*([^\s]+)", section
    ))
    changed = []
    for i, match in enumerate(starts):
        if match.group(2).lower() != "mohr_coulomb":
            continue
        stop = starts[i + 1].start() if i + 1 < len(starts) else len(section)
        values = {
            key.lower(): float(value)
            for key, value in re.findall(
                rf"([A-Za-z][A-Za-z0-9_]*)\s*:\s*({_NUMBER})",
                section[match.start():stop],
            )
        }
        pairs = (("e", "eres"), ("c", "cr"), ("phi", "phir"), ("t", "tr"))
        different = [
            residual for peak, residual in pairs
            if peak in values and residual in values
            and not np.isclose(values[peak], values[residual], rtol=1e-10, atol=1e-12)
        ]
        if different:
            changed.append(f"{match.group(1)} residual parameters differ: {', '.join(different)}")
    return tuple(changed)


def _beam_specs(text: str) -> dict[str, LinerSpec]:
    section = _section(text, "material types:", "element types:")
    starts = list(re.finditer(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*formulation:\s*([^\s]+)", section
    ))
    specs = {}
    for i, match in enumerate(starts):
        if match.group(2).lower() != "eulerbeam":
            continue
        stop = starts[i + 1].start() if i + 1 < len(starts) else len(section)
        raw = section[match.start():stop]
        values = {
            key.lower(): float(value)
            for key, value in re.findall(
                rf"([A-Za-z][A-Za-z0-9_]*)\s*:\s*({_NUMBER})", raw
            )
        }
        if int(values.get("beama_i_flag", 0)) != 0 or "beamthick" not in values:
            continue
        thickness = values["beamthick"]
        specs[match.group(1)] = LinerSpec(
            name=match.group(1),
            E=values["e"] * 1000.0,
            nu=values.get("nu", 0.0),
            A=thickness,
            I=thickness**3 / 12.0,
            As=0.0,  # RS2 eulerbeam -> Euler-Bernoulli beam (no shear deformation).
        )
    return specs


def _beam_joint_limitations(text: str) -> tuple[str, ...]:
    section = _section(text, "material types:", "element types:")
    starts = list(re.finditer(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*formulation:\s*([^\s]+)", section
    ))
    limitations = []
    for i, match in enumerate(starts):
        if match.group(2).lower() != "eulerbeam":
            continue
        stop = starts[i + 1].start() if i + 1 < len(starts) else len(section)
        values = {
            key.lower(): float(value)
            for key, value in re.findall(
                rf"([A-Za-z][A-Za-z0-9_]*)\s*:\s*({_NUMBER})",
                section[match.start():stop],
            )
        }
        if values.get("sj", 0.0) != 0.0 or values.get("sjs", 0.0) != 0.0:
            limitations.append(
                f"{match.group(1)} RS2 beam parameters sj/sjs (not mapped)"
            )
    return tuple(limitations)


def _beam_stage_records(stage_text: str, node_map: dict[int, int]):
    section = _named_section(stage_text, "beams")
    records = []
    unsupported_types = set()
    for line in section.splitlines():
        match = re.search(
            r"^\s*(\d+)\s+type:\s*(\w+)\s+nodes:\s*\[(\d+)\s*,\s*(\d+)\]"
            r".*?material:\s*(\w+)",
            line,
        )
        if not match:
            continue
        element_id, element_type, n1, n2, material = match.groups()
        if element_type.lower() != "l_beam2c2":
            unsupported_types.add(element_type)
            continue
        if int(n1) not in node_map or int(n2) not in node_map:
            raise RS2ImportError(f"Beam {element_id} references an unknown node")
        records.append((int(element_id), node_map[int(n1)], node_map[int(n2)], material))
    return records, unsupported_types


def _beam_material_changes(stage_text: str, current: dict[str, LinerSpec]):
    changed = dict(current)
    section = _named_section(stage_text, "change material")
    for material, young, poisson, thickness in re.findall(
        rf"(?m)^\s*material:\s*(\w+)\s+E:\s*({_NUMBER})\s+nu:\s*({_NUMBER})"
        rf".*?beamthick:\s*({_NUMBER})",
        section,
    ):
        if material not in changed:
            continue
        t = float(thickness)
        changed[material] = LinerSpec(
            name=material,
            E=float(young) * 1000.0,
            nu=float(poisson),
            A=t,
            I=t**3 / 12.0,
            As=0.0,
        )
    return changed


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

    The returned model is a preview unless report.analysis_ready is true. It
    imports supported element-wise initial stresses and Euler-Bernoulli beams,
    but does not approximate residual properties, RS2 beam joint parameters,
    stage-specific element body forces, or bonded-bolt grout transfer.
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

    stage_texts = _stage_sections(text, stage_count)
    names = _stage_names(text, stage_count)
    stage_body_forces = _stage_body_forces(stage_texts, element_ids)
    initial_body_force_complete = set(stage_body_forces[0]) == set(element_ids)
    beam_specs = _beam_specs(text)
    beam_records: dict[int, tuple[int, int, str]] = {}
    beam_blocks = []
    current_beam_specs = dict(beam_specs)
    stage_beam_states: list[tuple[frozenset[str], dict[str, LinerSpec]]] = []
    beam_presence: dict[int, set[int]] = {}
    unsupported_beam_types: set[str] = set()
    for stage_index, stage_text in enumerate(stage_texts):
        current_beam_specs = _beam_material_changes(stage_text, current_beam_specs)
        records, unknown_types = _beam_stage_records(stage_text, node_map)
        unsupported_beam_types.update(unknown_types)
        active_beams: set[str] = set()
        for element_id, n1, n2, material in records:
            if material not in beam_specs:
                raise RS2ImportError(
                    f"Beam {element_id} references unknown beam material '{material}'"
                )
            beam_records[element_id] = (n1, n2, material)
            beam_presence.setdefault(element_id, set()).add(stage_index)
            active_beams.add(material)
        stage_beam_states.append(
            (
                frozenset(active_beams),
                {tag: current_beam_specs[tag] for tag in active_beams},
            )
        )
    activation_signatures: dict[str, set[tuple[int, ...]]] = {}
    for element_id, (_, _, material) in beam_records.items():
        signature = tuple(sorted(beam_presence[element_id]))
        activation_signatures.setdefault(material, set()).add(signature)
    if any(len(signatures) > 1 for signatures in activation_signatures.values()):
        unsupported_beam_types.add("per-element activation histories within one beam material")
    for tag in sorted({record[2] for record in beam_records.values()}):
        selected = [
            (eid, n1, n2) for eid, (n1, n2, material) in sorted(beam_records.items())
            if material == tag
        ]
        beam_blocks.append(ElementBlock(
            ElemType.BEAM2,
            np.asarray([[n1, n2] for _, n1, n2 in selected], dtype=np.int64),
            np.full(len(selected), element_ids[0], dtype=np.int32),
            tag,
        ))
    mesh = Mesh(coords, (block, *beam_blocks), node_sets=node_sets)

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
        active_structures, liner_override = stage_beam_states[index]
        stages.append(Stage(
            name=names[index],
            active_regions=active,
            active_structures=active_structures,
            material_override=overrides,
            liner_override=liner_override,
            element_body_force=stage_body_forces[index],
        ))

    initial_field = _initial_stresses(stage_texts[0], element_ids)
    initial_complete = len(initial_field) == len(element_ids)
    initial = (
        InitialStress(
            mode="element_field",
            element_field=initial_field,
            gravity=not initial_body_force_complete,
        )
        if initial_complete else InitialStress(mode="gravity")
    )
    model = Model(
        analysis=Analysis.PLANE_STRAIN,
        mesh=mesh,
        materials=materials,
        region_material=base_material,
        fixities=fixities,
        liners=beam_specs,
        initial=initial,
        stages=stages,
        settings=SolverSettings(method="initial", max_iter=500, tol_force=1e-3),
    )
    model.validate()

    beam_ids = set(beam_records)
    beam_count = len(beam_ids)
    bolt_groups = _bolt_group_count(text)
    unsupported = []
    if not initial_complete:
        unsupported.append(
            "incomplete element-wise initial stress field "
            f"({len(initial_field)}/{len(element_ids)} elements)"
        )
    unsupported.extend(_residual_property_differences(text))
    unsupported.extend(_beam_joint_limitations(text))
    if stage_body_forces[0] and not initial_body_force_complete:
        unsupported.append(
            "incomplete stage-one element body-force field; gravity fallback is not "
            "guaranteed to match RS2"
        )
    if unsupported_beam_types:
        unsupported.append(
            "unsupported RS2 beam element types: " + ", ".join(sorted(unsupported_beam_types))
        )
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
            "Element-wise RS2 stresses are transferred as constant per-element initial stresses.",
            "RS2 element body forces are transferred cumulatively by stage and converted from MN/m3 to kN/m3.",
            "Euler-Bernoulli beam segments and stage-specific section changes are transferred.",
            "Continuum deletion/material reassignment and supported beam section "
            "changes are transferred.",
            "RS2 result files are not imported as SlipSurface solver results.",
            "Do not treat this preview as analysis-equivalent while features remain unsupported.",
        ),
    )
    return RS2ImportResult(model, report)
