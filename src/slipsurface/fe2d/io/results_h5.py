"""Versioned HDF5 results with lazy, stage-wise reading (L5).

This is a post-processing snapshot, not a nonlinear solver restart. Internal committed
state and displacement activation references are deliberately not reconstructed.
Tags and stage names are attributes on numbered groups so arbitrary user names (even
names containing slashes) round-trip without changing the HDF5 hierarchy.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np

from .. import __version__
from ..core.errors import ModelError
from ..fem.elements import kernel
from ..fem.nonlinear import StageHistory, StepRecord
from ..fem.static import SolveResult, StageResult
from .project_json import model_from_dict, model_to_dict

SCHEMA_VERSION = 1
_MAPS = ("sig", "q", "plastic", "active", "pore", "beams", "bars", "interfaces", "struct_flags")


def _array(group, name, value):
    value = np.asarray(value)
    options = {"compression": "gzip", "shuffle": True} if value.size and value.ndim else {}
    group.create_dataset(name, data=value, **options)


def _json(group, name, value):
    group.create_dataset(name, data=json.dumps(value), dtype=h5py.string_dtype("utf-8"))


def _read_json(group, name):
    return json.loads(group[name].asstr()[()])


def _write_mapping(group, values):
    for i, (tag, value) in enumerate(values.items()):
        entry = group.create_group(str(i))
        entry.attrs["tag"] = tag
        _array(entry, "value", value)


def _read_mapping(group):
    return {entry.attrs["tag"]: entry["value"][()] for entry in group.values()}


def _write_model(root, model):
    doc = model_to_dict(model, include_mesh=False)
    _json(root, "model", doc)
    mg = root.create_group("mesh")
    _array(mg, "coords", model.mesh.coords)
    bg = mg.create_group("blocks")
    for i, block in enumerate(model.mesh.blocks):
        g = bg.create_group(str(i))
        g.attrs.update(tag=block.tag, etype=block.etype.name)
        _array(g, "conn", block.conn)
        _array(g, "region", block.region)
    for name in ("node_sets", "edge_sets"):
        _write_mapping(mg.create_group(name), getattr(model.mesh, name))


def _read_model(root, doc=None):
    doc = _read_json(root, "model") if doc is None else dict(doc)
    mg = root["mesh"]
    doc["mesh"] = {
        "coords": mg["coords"][()],
        "blocks": [
            dict(
                tag=g.attrs["tag"],
                etype=g.attrs["etype"],
                conn=g["conn"][()],
                region=g["region"][()],
            )
            for _, g in sorted(mg["blocks"].items(), key=lambda item: int(item[0]))
        ],
        "node_sets": _read_mapping(mg["node_sets"]),
        "edge_sets": _read_mapping(mg["edge_sets"]),
    }
    return model_from_dict(doc)


def _write_stage(group, stage):
    group.attrs.update(name=stage.name, lam=stage.lam)
    _array(group, "u", stage.u)
    _array(group, "reactions", stage.reactions)
    if stage.rotation is not None:
        _array(group, "rotation", stage.rotation)
    _json(group, "timings", stage.timings)
    if stage.history is not None:
        _json(group, "history", asdict(stage.history))
    for name in _MAPS:
        _write_mapping(group.create_group(name), getattr(stage, name))


def _read_stage(group):
    history = None
    if "history" in group:
        history = StageHistory([StepRecord(**s) for s in _read_json(group, "history")["steps"]])
    return StageResult(
        name=group.attrs["name"],
        lam=float(group.attrs["lam"]),
        u=group["u"][()],
        reactions=group["reactions"][()],
        rotation=group["rotation"][()] if "rotation" in group else None,
        timings=_read_json(group, "timings"),
        history=history,
        **{name: _read_mapping(group[name]) for name in _MAPS},
    )


def _write_results(root, result):
    root.attrs.update(
        format="slipsurface-results",
        schema_version=SCHEMA_VERSION,
        solver_version=__version__,
        units="kN,m,kPa,s",
        stress_convention="tension_positive",
        axisymmetric_measure="per_radian",
        created=datetime.now(timezone.utc).isoformat(),
    )
    _write_model(root, result.model)
    _write_stage(root.create_group("initial"), result.initial)
    stages = root.create_group("stages")
    for i, stage in enumerate(result.stages):
        _write_stage(stages.create_group(str(i)), stage)


def _atomic_write(path, writer):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    try:
        writer(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def save_results(result: SolveResult, path: str | Path) -> Path:
    """Atomically write all converged stage snapshots, preserving NaNs and dtypes."""

    def write(tmp):
        with h5py.File(tmp, "w") as root:
            _write_results(root, result)

    return _atomic_write(path, write)


class ResultsReader:
    """Context-managed lazy results reader; only the mesh/model are read on opening.

    ``reader.stage(i)`` loads one stage into detached NumPy arrays. The returned snapshot
    remains usable after closing the reader. Names follow ``SolveResult.stage`` semantics
    (first matching name); integer indices also support negative indexing.
    """

    def __init__(self, path: str | Path):
        self._file = h5py.File(path, "r")
        try:
            root = self._file
            if root.attrs.get("format") != "slipsurface-results":
                raise ModelError("not a SlipSurface results file")
            if root.attrs.get("schema_version") != SCHEMA_VERSION:
                raise ModelError("unsupported results schema version")
            self.model = _read_model(root)
            groups = root["stages"]
            self.stage_names = tuple(groups[str(i)].attrs["name"] for i in range(len(groups)))
        except BaseException:
            self.close()
            raise

    @property
    def initial(self) -> StageResult:
        return _read_stage(self._file["initial"])

    def stage(self, name_or_index: str | int) -> StageResult:
        if isinstance(name_or_index, int):
            i = range(len(self.stage_names))[name_or_index]
        else:
            try:
                i = self.stage_names.index(name_or_index)
            except ValueError:
                raise KeyError(name_or_index) from None
        return _read_stage(self._file["stages"][str(i)])

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> ResultsReader:
        return self

    def __exit__(self, *exc):
        self.close()


def _load_reader(reader):
    model = reader.model
    geom = {
        b.tag: kernel(b.etype).precompute(
            model.mesh.coords, b.conn, model.analysis, model.settings.gauss_order
        )
        for b in model.mesh.continuum_blocks()
    }
    return SolveResult(
        model, geom, reader.initial, [reader.stage(i) for i in range(len(reader.stage_names))]
    )


def load_results(path: str | Path) -> SolveResult:
    """Load a post-processing snapshot without solving; use ResultsReader for large files."""
    with ResultsReader(path) as reader:
        return _load_reader(reader)
