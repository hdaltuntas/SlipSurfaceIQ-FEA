"""Shared test helpers."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.model import Displacement, ElementBlock, Mesh


def distort(mesh: Mesh, amount: float, seed: int = 0) -> Mesh:
    """Randomly move interior corner nodes; T6 mid-nodes are reset to straight midpoints."""
    rng = np.random.default_rng(seed)
    blk = mesh.blocks[0]
    coords = mesh.coords.copy()
    boundary = np.unique(np.concatenate([v for k, v in mesh.node_sets.items() if k != "all"]))
    nc = 4 if blk.etype in (ElemType.Q4, ElemType.Q8) else 3
    corners = np.unique(blk.conn[:, :nc])
    interior = np.setdiff1d(corners, boundary)
    coords[interior] += amount * rng.uniform(-1, 1, (interior.size, 2))
    c = blk.conn
    if blk.etype is ElemType.T6:
        for m, (a, b) in zip((3, 4, 5), ((0, 1), (1, 2), (2, 0))):
            coords[c[:, m]] = 0.5 * (coords[c[:, a]] + coords[c[:, b]])
    if blk.etype is ElemType.Q8:
        for m, (a, b) in zip((4, 5, 6, 7), ((0, 1), (1, 2), (2, 3), (3, 0))):
            coords[c[:, m]] = 0.5 * (coords[c[:, a]] + coords[c[:, b]])
    return Mesh(
        coords,
        (ElementBlock(blk.etype, blk.conn, blk.region, blk.tag),),
        mesh.node_sets,
        mesh.edge_sets,
    )


def per_node_displacements(mesh: Mesh, nodes, field) -> tuple[Mesh, tuple[Displacement, ...]]:
    """Add one node set per node and a Displacement BC with ``field(x, y) -> (ux, uy)``."""
    ns = dict(mesh.node_sets)
    bcs = []
    for n in np.asarray(nodes):
        name = f"_p{int(n)}"
        ns[name] = np.array([n])
        ux, uy = field(*mesh.coords[n])
        bcs.append(Displacement(name, float(ux), float(uy)))
    return Mesh(mesh.coords, mesh.blocks, ns, mesh.edge_sets), tuple(bcs)


def rel_err(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return float(np.max(np.abs(a - b)) / np.max(np.abs(b)))


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


@pytest.fixture(scope="session")
def _qt_application(tmp_path_factory):
    """Qt permits one QApplication for the process, not one per test module."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    # Window layout persistence must not read or write the developer's real settings.
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qt-settings")),
    )
    app = QApplication.instance() or QApplication([])
    yield app  # keep the Python owner alive through every desktop test module


@pytest.fixture
def qt_app(_qt_application):
    """Destroy test widgets while Qt is alive; drain deferred QObject deletions."""
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent, QThread

    yield _qt_application
    for window in _qt_application.topLevelWidgets():
        for thread in window.findChildren(QThread):
            if thread.isRunning():
                thread.requestInterruption()
                assert thread.wait(5000), "test left an unresponsive Qt worker"
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _qt_application.processEvents()
    gc.collect()


def pytest_runtest_logreport(report):  # pragma: no cover - CI only
    """On GitHub Actions, turn every failure into an ``::error`` annotation so the failing
    test and its message are visible in the check run without downloading the log."""
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    text = report.longreprtext.strip().splitlines()
    tail = "\n".join(text[-15:])
    msg = tail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    title = f"{report.nodeid} ({report.when})".replace(",", "%2C").replace("::", "-")
    sys.__stdout__.write(f"\n::error title={title}::{msg}\n")
    sys.__stdout__.flush()
