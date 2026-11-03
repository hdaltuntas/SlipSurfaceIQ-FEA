"""Repair the documented four-stage uploaded tunnel .ssproj as a reproducible example.

Usage:
    python examples/repair_staged_tunnel_project.py model.ssproj corrected_tunnel.ssproj

The original mesh.h5 is retained byte-for-byte. This is an activation and boundary
condition correction, not a remeshing or validated numerical solution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile


STAGE_NAMES = (
    "Excavation 1 - Top heading / primary support",
    "Excavation 2 - Bench / sidewall support",
    "Excavation 3 - Invert / ring closure",
    "Stage 4 - Final equilibrium",
)

FIXITIES = {
    "Region1:2": (True, False),  # right roller: ux only
    "Region1:3": (True, True),   # bottom: ux and uy
    "Region1:4": (True, False),  # left roller: ux only
}


def repair_document(doc: dict) -> dict:
    """Return a new project document, never modify the supplied dictionary."""
    from copy import deepcopy

    data = deepcopy(doc)
    stages = data["stages"]
    if len(stages) != 4 or [set(st["active_regions"]) for st in stages] != [
        {1, 3, 4}, {1, 4}, {1}, {1}
    ]:
        raise ValueError("Example repair expects head, bench and invert excavation stages.")
    points = next(
        entity["points"] for entity in data["geometry"]["entities"]
        if entity["name"] == "Region1"
    )
    if len(points) != 4 or [tuple(p) for p in points] != [
        (28.0, 20.0), (102.5, 20.0), (102.5, -34.0), (28.0, -34.0)
    ]:
        raise ValueError("Unexpected outer boundary; do not change fixities blindly.")

    head_bolts = {k for k in data["bolts"] if "SC_Head_" in k}
    wall_bolts = {k for k in data["bolts"] if "SC_Bench_" in k}
    if len(head_bolts) != 16 or len(wall_bolts) != 4:
        raise ValueError("Unexpected bolt inventory.")
    head_liner = "cad_Tunnel_SC_Head"
    wall_liners = {"cad_Tunnel_SC_Bench_Left", "cad_Tunnel_SC_Bench_Right"}
    invert_liner = "cad_Tunnel_SC_Inv"
    if not ({head_liner, invert_liner} | wall_liners) <= set(data["liners"]):
        raise ValueError("Missing expected shotcrete lining.")

    for index, stage in enumerate(stages):
        active = head_bolts | {head_liner}
        if index >= 1:
            active |= wall_bolts | wall_liners
        if index >= 2:
            active.add(invert_liner)
        stage["name"] = STAGE_NAMES[index]
        stage["active_structures"] = sorted(active)

    for fix in data["fixities"]:
        if fix["node_set"] in FIXITIES:
            fix["ux"], fix["uy"] = FIXITIES[fix["node_set"]]
    for rule in data["geometry"]["rules"]:
        if rule["edge"] in FIXITIES:
            rule["ux"], rule["uy"] = FIXITIES[rule["edge"]]

    drawing = data["geometry"]
    old_names = ["CAD loading", "Stage 2", "Stage 3", "Stage 4"]
    drawing["loading_name"] = STAGE_NAMES[0]
    for step, name in zip(drawing["sequence"], STAGE_NAMES[1:]):
        step["name"] = name
    for assignment in drawing.get("material_assignments", []):
        if assignment["stage"] in old_names:
            assignment["stage"] = STAGE_NAMES[old_names.index(assignment["stage"])]
    for support in drawing["supports"]:
        if support["entity"] == "Tunnel_SC_Head":
            support["active"] = True

    # Do not add cad_Tunnel_Bench/cad_Tunnel_Inv: they overlap other
    # structural linework. Their physical identity needs manual confirmation.
    return data


def repair_project(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ.")
    with ZipFile(source) as archive:
        if "model.json" not in archive.namelist() or "mesh.h5" not in archive.namelist():
            raise ValueError("Expected a .ssproj archive with model.json and mesh.h5.")
        document = json.loads(archive.read("model.json"))
        corrected = repair_document(document)
        with ZipFile(destination, "w") as output:
            for entry in archive.infolist():
                content = (
                    json.dumps(corrected, indent=2, ensure_ascii=False).encode("utf-8")
                    if entry.filename == "model.json"
                    else archive.read(entry.filename)
                )
                output.writestr(entry, content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    repair_project(args.source, args.destination)
    print(f"Saved corrected example: {args.destination}")


if __name__ == "__main__":
    main()
