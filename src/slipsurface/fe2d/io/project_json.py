"""Model <-> JSON (L5). Lossless round trip of every L1 definition.

The document carries ``schema_version``; future versions register migration functions
in ``MIGRATIONS`` (``{from_version: fn(dict) -> dict}``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from ..core.enums import Analysis, Drainage, ElemType
from ..core.errors import ModelError
from ..model import (
    BoltSpec,
    Displacement,
    EdgeLoad,
    ElementBlock,
    Fixity,
    FluxBC,
    HeadBC,
    InitialStress,
    InterfaceSpec,
    LinerSpec,
    MaterialSpec,
    Mesh,
    Model,
    PointLoad,
    SolverSettings,
    Stage,
    WaterCondition,
)

SCHEMA_VERSION = 1
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


# ----------------------------------------------------------------------------- encode
def _enc(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (frozenset, set)):
        return sorted(obj)
    if isinstance(obj, tuple):
        return [_enc(v) for v in obj]
    if isinstance(obj, list):
        return [_enc(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _enc(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        d = {f.name: _enc(getattr(obj, f.name)) for f in fields(obj)}
        if isinstance(obj, (EdgeLoad, PointLoad)):
            d["kind"] = type(obj).__name__
        return d
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj


def mesh_to_dict(m: Mesh) -> dict:
    return {
        "coords": m.coords.tolist(),
        "blocks": [
            {
                "etype": b.etype.name,
                "conn": b.conn.tolist(),
                "region": b.region.tolist(),
                "tag": b.tag,
            }
            for b in m.blocks
        ],
        "node_sets": _enc(m.node_sets),
        "edge_sets": _enc(m.edge_sets),
    }


def model_to_dict(
    model: Model, mesh_ref: str | None = None, *, include_mesh: bool = True
) -> dict:
    """JSON-ready dict. ``mesh_ref`` (e.g. ``"mesh.h5"``) stores a reference instead of
    the mesh arrays (used by the ``.ssproj`` container, which keeps the mesh in HDF5)."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "analysis": model.analysis.value,
        "mesh": {"$ref": mesh_ref} if mesh_ref else mesh_to_dict(model.mesh),
        "materials": _enc(model.materials),
        "region_material": _enc(model.region_material),
        "fixities": _enc(model.fixities),
        "displacements": _enc(model.displacements),
        "initial": _enc(model.initial),
        "stages": _enc(model.stages),
        "liners": _enc(model.liners),
        "bolts": _enc(model.bolts),
        "settings": _enc(model.settings),
        "interfaces": _enc(model.interfaces),
        "geometry": _enc(model.geometry),
    }

    if not include_mesh:
        doc.pop("mesh")
    return doc


# ----------------------------------------------------------------------------- decode
def _water(d: dict) -> WaterCondition:
    pl = d.get("piezo_polyline")
    return WaterCondition(
        mode=d.get("mode", "none"),
        piezo_polyline=None if pl is None else np.asarray(pl, dtype=float),
        head_bcs=tuple(HeadBC(**h) for h in d.get("head_bcs", [])),
        flux_bcs=tuple(FluxBC(**f) for f in d.get("flux_bcs", [])),
        seepage_faces=tuple(d.get("seepage_faces", [])),
    )


def _load(d: dict) -> EdgeLoad | PointLoad:
    d = dict(d)
    kind = d.pop("kind")
    return {"EdgeLoad": EdgeLoad, "PointLoad": PointLoad}[kind](**d)


def _initial(d: dict) -> InitialStress:
    d = dict(d)
    if "water" in d:
        d["water"] = _water(d["water"])
    for k in ("active_regions", "active_structures"):
        if d.get(k) is not None:
            d[k] = frozenset(d[k])
    return InitialStress(**d)


def mesh_from_dict(md: dict) -> Mesh:
    return Mesh(
        np.asarray(md["coords"], dtype=float),
        tuple(
            ElementBlock(
                ElemType[b["etype"]], np.asarray(b["conn"]), np.asarray(b["region"]), b["tag"]
            )
            for b in md["blocks"]
        ),
        {k: np.asarray(v, dtype=np.int64) for k, v in md["node_sets"].items()},
        {k: np.asarray(v, dtype=np.int64) for k, v in md["edge_sets"].items()},
    )


def model_from_dict(doc: dict, mesh: Mesh | None = None) -> Model:
    """Inverse of :func:`model_to_dict`; ``mesh`` is required if the document only holds
    a ``{"$ref": ...}`` to an external mesh."""
    ver = int(doc.get("schema_version", 0))
    while ver < SCHEMA_VERSION:
        if ver not in MIGRATIONS:
            raise ModelError(f"cannot migrate project schema v{ver}")
        doc = MIGRATIONS[ver](doc)
        ver = int(doc["schema_version"])
    if ver > SCHEMA_VERSION:
        raise ModelError(f"project schema v{ver} is newer than this library (v{SCHEMA_VERSION})")

    md = doc["mesh"]
    if "$ref" in md:
        if mesh is None:
            raise ModelError(f"model refers to an external mesh '{md['$ref']}'")
    else:
        mesh = mesh_from_dict(md)
    mats = {
        k: MaterialSpec(
            name=v["name"],
            model=v["model"],
            params={pk: float(pv) for pk, pv in v["params"].items()},
            gamma_unsat=v["gamma_unsat"],
            gamma_sat=v["gamma_sat"],
            drainage=Drainage(v["drainage"]),
            k_sat=tuple(v["k_sat"]),
            vg=tuple(v.get("vg", (1.0, 2.0, 1e-4))),
        )
        for k, v in doc["materials"].items()
    }
    stages = [
        Stage(
            name=s["name"],
            active_regions=None if s["active_regions"] is None else frozenset(s["active_regions"]),
            active_structures=frozenset(s["active_structures"]),
            material_override={int(k): v for k, v in s["material_override"].items()},
            loads=tuple(_load(ld) for ld in s["loads"]),
            water=_water(s["water"]),
            load_split=s["load_split"],
            reset_displacements=s["reset_displacements"],
            displacements=tuple(Displacement(**d) for d in s.get("displacements", [])),
            drained=bool(s.get("drained", False)),
        )
        for s in doc["stages"]
    ]
    return Model(
        analysis=Analysis(doc["analysis"]),
        mesh=mesh,
        materials=mats,
        region_material={int(k): v for k, v in doc["region_material"].items()},
        fixities=tuple(Fixity(**f) for f in doc["fixities"]),
        displacements=tuple(Displacement(**d) for d in doc["displacements"]),
        initial=_initial(doc["initial"]),
        stages=stages,
        liners={k: LinerSpec(**v) for k, v in doc["liners"].items()},
        bolts={k: BoltSpec(**v) for k, v in doc["bolts"].items()},
        interfaces={k: InterfaceSpec(**v) for k, v in doc.get("interfaces", {}).items()},
        settings=SolverSettings(**doc["settings"]),
        geometry=deepcopy(doc.get("geometry")),
    )


def save_model(model: Model, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(model_to_dict(model), indent=1), encoding="utf-8")
    return path


def load_model(path: str | Path) -> Model:
    return model_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
