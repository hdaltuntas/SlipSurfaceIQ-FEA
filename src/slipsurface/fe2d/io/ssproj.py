"""``.ssproj`` project container: a ZIP archive with

* ``model.json``   — the model (schema-versioned, diff-friendly; the mesh is a reference)
* ``mesh.h5``      — mesh arrays (HDF5)
* ``results.h5``   — optional staged results (see :mod:`.results_h5`)
* ``manifest.json``— container format version, library version, contents

``save_project`` writes atomically (temporary file + rename). ``load_project`` returns
the model and, if present, the results (eagerly, or lazily through
:func:`open_project_results`).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ModelError
from ..fem.static import SolveResult
from ..model.model import Model
from .project_json import model_from_dict, model_to_dict
from .results_h5 import ResultsFile, load_mesh, save_mesh, write_results

CONTAINER_VERSION = 1


def _lib_version() -> str:
    try:
        from importlib.metadata import version

        return version("slipsurface-fe2d")
    except Exception:  # pragma: no cover
        return "unknown"


@dataclass
class Project:
    model: Model
    results: SolveResult | None = None


def save_project(path: str | Path, model: Model, results: SolveResult | None = None) -> Path:
    """Write ``model`` (and ``results``) to a ``.ssproj`` archive."""
    path = Path(path)
    model.validate()
    if results is not None and model_to_dict(results.model) != model_to_dict(model):
        raise ModelError("results were computed for a different model")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "model.json").write_text(
            json.dumps(model_to_dict(model, mesh_ref="mesh.h5"), indent=1), encoding="utf-8"
        )
        save_mesh(model.mesh, tdp / "mesh.h5")
        files = ["model.json", "mesh.h5"]
        if results is not None:
            write_results(results, tdp / "results.h5")
            files.append("results.h5")
        manifest = {
            "format": "slipsurface-project",
            "container_version": CONTAINER_VERSION,
            "library_version": _lib_version(),
            "files": files,
        }
        (tdp / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        tmp = path.with_name(path.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(tdp / "manifest.json", "manifest.json")
            for name in files:
                # HDF5 is already compressed internally: store it
                comp = zipfile.ZIP_STORED if name.endswith(".h5") else zipfile.ZIP_DEFLATED
                z.write(tdp / name, name, compress_type=comp)
        os.replace(tmp, path)
    return path


def _manifest(z: zipfile.ZipFile, path: Path) -> dict:
    try:
        man = json.loads(z.read("manifest.json"))
    except KeyError:
        raise ModelError(f"{path}: not a SlipSurface project (no manifest)") from None
    if man.get("format") != "slipsurface-project":
        raise ModelError(f"{path}: not a SlipSurface project")
    if int(man.get("container_version", 0)) > CONTAINER_VERSION:
        raise ModelError(f"{path}: project container is newer than this library")
    return man


def load_project(path: str | Path, with_results: bool = True) -> Project:
    """Read a ``.ssproj`` archive (results are loaded fully into memory)."""
    path = Path(path)
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as td:
        man = _manifest(z, path)
        tdp = Path(td)
        z.extract("mesh.h5", tdp)
        mesh = load_mesh(tdp / "mesh.h5")
        model = model_from_dict(json.loads(z.read("model.json")), mesh=mesh)
        results = None
        if with_results and "results.h5" in man["files"]:
            z.extract("results.h5", tdp)
            with ResultsFile(tdp / "results.h5") as rf:
                results = rf.to_solve_result(model)
    return Project(model, results)


class ProjectResults(ResultsFile):
    """Lazy results of a project; the HDF5 file is extracted to a temporary directory
    that is removed on :meth:`close`."""

    def __init__(self, path: str | Path) -> None:
        self._tmp = tempfile.mkdtemp(prefix="ssproj_")
        try:
            with zipfile.ZipFile(path) as z:
                man = _manifest(z, Path(path))
                if "results.h5" not in man["files"]:
                    raise ModelError(f"{path}: project has no results")
                z.extract("results.h5", self._tmp)
            super().__init__(Path(self._tmp) / "results.h5")
        except Exception:
            shutil.rmtree(self._tmp, ignore_errors=True)
            raise

    def close(self) -> None:
        super().close()
        shutil.rmtree(self._tmp, ignore_errors=True)


def open_project_results(path: str | Path) -> ProjectResults:
    return ProjectResults(path)
