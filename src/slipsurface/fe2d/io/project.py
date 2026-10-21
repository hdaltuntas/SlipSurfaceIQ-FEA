"""Portable .ssproj ZIP container: model.json, mesh.h5 and optional results.h5."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import h5py

from ..core.errors import ModelError
from ..fem.static import SolveResult
from ..model import Model
from .project_json import model_to_dict
from .results_h5 import (
    _atomic_write,
    _read_model,
    _write_model,
    load_results,
    save_results,
)

PROJECT_VERSION = 1


@dataclass
class Project:
    model: Model
    results: SolveResult | None = None


def save_project(model: Model, path: str | Path, results: SolveResult | None = None) -> Path:
    """Atomically save a model and optional matching post-processing results."""
    if isinstance(model, (str, Path)):
        from .ssproj import save_project as legacy_save
        return legacy_save(model, path, results)
    model.validate()
    doc = model_to_dict(model, include_mesh=False)
    if results is not None and model_to_dict(results.model) != model_to_dict(model):
        raise ModelError("results belong to a different model")
    doc["project_version"] = PROJECT_VERSION
    doc["mesh_file"] = "mesh.h5"

    def write(tmp):
        with tempfile.TemporaryDirectory() as folder:
            mesh_path = Path(folder) / "mesh.h5"
            with h5py.File(mesh_path, "w") as root:
                _write_model(root, model)
                # The authoritative model definition lives in model.json in the ZIP.
                del root["model"]
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("model.json", json.dumps(doc, indent=1))
                archive.write(mesh_path, "mesh.h5")
                if results is not None:
                    result_path = save_results(results, Path(folder) / "results.h5")
                    archive.write(result_path, "results.h5")

    return _atomic_write(path, write)


def load_project(
    path: str | Path, *, include_results: bool = True, with_results: bool | None = None
) -> Project:
    """Read only fixed members (never extract arbitrary archive paths).

    Set ``include_results=False`` to open the model without reading result arrays.
    Result snapshots are for post-processing, not for resuming a solver iteration.
    """
    if with_results is not None:
        include_results = with_results
    with zipfile.ZipFile(path) as probe:
        if "manifest.json" in probe.namelist():
            from .ssproj import load_project as legacy_load
            return legacy_load(path, with_results=include_results)
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as folder:
        names = archive.namelist()
        for name in ("model.json", "mesh.h5", "results.h5"):
            if names.count(name) > 1:
                raise ModelError(f"duplicate project member '{name}'")
        if not {"model.json", "mesh.h5"} <= set(names):
            raise ModelError("project needs model.json and mesh.h5")
        doc = json.loads(archive.read("model.json"))
        if doc.pop("project_version", None) != PROJECT_VERSION:
            raise ModelError("unsupported project container version")
        if doc.pop("mesh_file", None) != "mesh.h5":
            raise ModelError("unsupported project mesh reference")

        def copy_member(name):
            target = Path(folder) / name
            with archive.open(name) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            return target

        with h5py.File(copy_member("mesh.h5"), "r") as root:
            model = _read_model(root, doc)
        model.validate()
        results = None
        if include_results and "results.h5" in names:
            results = load_results(copy_member("results.h5"))
            if model_to_dict(results.model) != model_to_dict(model):
                raise ModelError("project results do not match model.json/mesh.h5")
            results.model = model
        return Project(model, results)
