"""HDF5 storage of meshes and staged results (h5py, gzip, lazy reading).

Layout of a results file::

    /                         attrs: format="slipsurface-results", format_version, analysis
    /mesh/coords              (nn, 2)
    /mesh/blocks/<i>          attrs: tag, etype; datasets conn, region
    /mesh/node_sets/<name>    (n,)        /mesh/edge_sets/<name>  (m, npe)
    /geom/<tag>/xg            (ne, ngp, 2) Gauss point coordinates (for recovery/plots)
    /stages/<k>               k = 0 (initial), 1, 2, ...; attrs: name, lam, timings (JSON),
                              history (JSON: per step lam, iterations, residuals, converged)
        u (nn, 2), rotation (nn,), reactions (nn, 3), head (nn,) [seepage stages]
        sig/<tag> (ne, ngp, 4), q/<tag>, plastic/<tag>, active/<tag>, pore/<tag>
        beams/<tag> (ne, 2, 3), bars/<tag> (ne,), interfaces/<tag> (ne, ip, 2),
        struct_flags/<tag>

Group and dataset names that are not valid HDF5 path components (block tags may contain
``/``) are percent-encoded. :class:`ResultsFile` reads arrays only when accessed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import numpy as np
from numpy.typing import NDArray

from ..core.enums import ElemType
from ..core.errors import ModelError
from ..fem.nonlinear import StageHistory, StepRecord
from ..fem.static import SolveResult, StageResult
from ..model.mesh import ElementBlock, Mesh
from ..model.model import Model

FORMAT = "slipsurface-results"
FORMAT_VERSION = 1
_COMP = {"compression": "gzip", "compression_opts": 4, "shuffle": True}
_DICT_FIELDS = ("sig", "q", "plastic", "active", "pore", "beams", "bars", "interfaces",
                "struct_flags")  # fmt: skip


def _h5py() -> Any:
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - h5py is a core dependency
        raise ImportError("HDF5 support needs h5py (pip install h5py)") from exc
    return h5py


def _key(name: str) -> str:
    return quote(name, safe="")


def _unkey(name: str) -> str:
    return unquote(name)


def _put(g: Any, name: str, arr: NDArray) -> None:
    a = np.asarray(arr)
    kw = _COMP if a.size >= 1024 else {}
    g.create_dataset(_key(name), data=a, **kw)


# ----------------------------------------------------------------------------- mesh
def write_mesh(g: Any, mesh: Mesh) -> None:
    _put(g, "coords", mesh.coords)
    blocks = g.create_group("blocks")
    for i, b in enumerate(mesh.blocks):
        bg = blocks.create_group(str(i))
        bg.attrs["tag"] = b.tag
        bg.attrs["etype"] = b.etype.name
        _put(bg, "conn", b.conn)
        _put(bg, "region", b.region)
    ns = g.create_group("node_sets")
    for k, v in mesh.node_sets.items():
        _put(ns, k, v)
    es = g.create_group("edge_sets")
    for k, v in mesh.edge_sets.items():
        _put(es, k, v)


def read_mesh(g: Any) -> Mesh:
    blocks = []
    for i in sorted(g["blocks"], key=int):
        bg = g["blocks"][i]
        blocks.append(
            ElementBlock(
                ElemType[str(bg.attrs["etype"])], bg["conn"][()], bg["region"][()],
                str(bg.attrs["tag"]),
            )
        )  # fmt: skip
    return Mesh(
        g["coords"][()],
        tuple(blocks),
        {_unkey(k): v[()] for k, v in g["node_sets"].items()},
        {_unkey(k): v[()] for k, v in g["edge_sets"].items()},
    )


def save_mesh(mesh: Mesh, path: str | Path) -> Path:
    h5py = _h5py()
    path = Path(path)
    with h5py.File(path, "w") as f:
        f.attrs["format"] = "slipsurface-mesh"
        f.attrs["format_version"] = FORMAT_VERSION
        write_mesh(f.create_group("mesh"), mesh)
    return path


def load_mesh(path: str | Path) -> Mesh:
    h5py = _h5py()
    with h5py.File(path, "r") as f:
        return read_mesh(f["mesh"])


# ----------------------------------------------------------------------------- results
def _history_json(h: StageHistory | None) -> str:
    if h is None:
        return "null"
    return json.dumps(
        [
            {"lam": s.lam, "iterations": s.iterations, "residuals": list(map(float, s.residuals)),
             "converged": bool(s.converged)}
            for s in h.steps
        ]
    )  # fmt: skip


def _history_from_json(text: str) -> StageHistory | None:
    data = json.loads(text)
    if data is None:
        return None
    return StageHistory(
        [StepRecord(d["lam"], d["iterations"], d["residuals"], d["converged"]) for d in data]
    )


def _write_stage(g: Any, st: StageResult) -> None:
    g.attrs["name"] = st.name
    g.attrs["lam"] = float(st.lam)
    g.attrs["timings"] = json.dumps(st.timings)
    g.attrs["history"] = _history_json(st.history)
    g.attrs["flow"] = json.dumps(st.flow)
    _put(g, "u", st.u)
    _put(g, "reactions", st.reactions)
    if st.rotation is not None:
        _put(g, "rotation", st.rotation)
    if st.head is not None:
        _put(g, "head", st.head)
    for fld in _DICT_FIELDS:
        d = getattr(st, fld)
        if d:
            sub = g.create_group(fld)
            for k, v in d.items():
                _put(sub, k, v)


def write_results(result: SolveResult, path: str | Path) -> Path:
    """Write mesh, Gauss-point geometry and every stage of ``result``."""
    h5py = _h5py()
    path = Path(path)
    with h5py.File(path, "w") as f:
        f.attrs["format"] = FORMAT
        f.attrs["format_version"] = FORMAT_VERSION
        f.attrs["analysis"] = result.model.analysis.value
        write_mesh(f.create_group("mesh"), result.model.mesh)
        geo = f.create_group("geom")
        for tag, gc in result.geom.items():
            _put(geo.create_group(_key(tag)), "xg", gc.xg)
        stages = f.create_group("stages")
        for k, st in enumerate([result.initial, *result.stages]):
            _write_stage(stages.create_group(str(k)), st)
    return path


class LazyStage:
    """Stage view of a results file: arrays are read on attribute access."""

    def __init__(self, g: Any) -> None:
        self._g = g
        self.name: str = str(g.attrs["name"])
        self.lam: float = float(g.attrs["lam"])
        self.timings: dict[str, float] = json.loads(g.attrs["timings"])
        self.flow: dict[str, float] = json.loads(g.attrs.get("flow", "{}"))

    @property
    def history(self) -> StageHistory | None:
        return _history_from_json(self._g.attrs["history"])

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        g = self._g
        if item in _DICT_FIELDS:
            if item not in g:
                return {}
            return {_unkey(k): v[()] for k, v in g[item].items()}
        if item in ("u", "reactions", "rotation", "head"):
            return g[item][()] if item in g else None
        raise AttributeError(item)

    def field(self, group: str, tag: str) -> NDArray:
        """One array, e.g. ``field("sig", "soil")``, without loading the others."""
        return self._g[group][_key(tag)][()]

    def to_stage_result(self) -> StageResult:
        kw = {f: getattr(self, f) for f in _DICT_FIELDS}
        return StageResult(
            name=self.name, u=self.u, reactions=self.reactions, timings=self.timings,
            history=self.history, rotation=self.rotation, lam=self.lam, head=self.head,
            flow=self.flow, **kw,
        )  # fmt: skip


class ResultsFile:
    """Read-only, lazy access to a results file (use as a context manager).

    >>> with ResultsFile("run.h5") as rf:
    ...     rf.stage_names
    ...     s = rf.stage("excavate")
    ...     s.field("sig", "soil")
    """

    def __init__(self, path: str | Path) -> None:
        h5py = _h5py()
        self._f = h5py.File(path, "r")
        if self._f.attrs.get("format") != FORMAT:
            self._f.close()
            raise ModelError(f"{path}: not a SlipSurface results file")
        ver = int(self._f.attrs["format_version"])
        if ver > FORMAT_VERSION:
            self._f.close()
            raise ModelError(f"{path}: results format v{ver} is newer than this library")
        self._stages = [self._f["stages"][k] for k in sorted(self._f["stages"], key=int)]

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> ResultsFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def stage_names(self) -> list[str]:
        """Names of the user stages (the initial state is ``stage("initial")``)."""
        return [str(g.attrs["name"]) for g in self._stages[1:]]

    @property
    def initial(self) -> LazyStage:
        return LazyStage(self._stages[0])

    def stage(self, name_or_index: str | int) -> LazyStage:
        if isinstance(name_or_index, int):
            return LazyStage(self._stages[1:][name_or_index])
        if name_or_index == "initial":
            return self.initial
        for g in self._stages[1:]:
            if g.attrs["name"] == name_or_index:
                return LazyStage(g)
        raise KeyError(name_or_index)

    def __iter__(self) -> Iterator[LazyStage]:
        return (LazyStage(g) for g in self._stages[1:])

    def mesh(self) -> Mesh:
        return read_mesh(self._f["mesh"])

    def xg(self, tag: str) -> NDArray:
        return self._f["geom"][_key(tag)]["xg"][()]

    def to_solve_result(self, model: Model) -> SolveResult:
        """Load everything into a :class:`SolveResult` (``model`` supplies the model;
        geometry caches are recomputed on demand by the post-processing functions)."""
        from ..fem.elements import kernel

        geom = {
            b.tag: kernel(b.etype).precompute(
                model.mesh.coords, b.conn, model.analysis, model.settings.gauss_order
            )
            for b in model.mesh.continuum_blocks()
        }
        return SolveResult(
            model=model,
            geom=geom,
            initial=self.initial.to_stage_result(),
            stages=[s.to_stage_result() for s in self],
        )


def read_results(path: str | Path, model: Model) -> SolveResult:
    with ResultsFile(path) as rf:
        return rf.to_solve_result(model)
