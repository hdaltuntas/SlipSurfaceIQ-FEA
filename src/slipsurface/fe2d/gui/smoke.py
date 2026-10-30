"""Installed/frozen application smoke check; failures return nonzero, never masked."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtTest import QTest

from .. import __version__, api
from ..io.report import export_csv, export_html
from .app import MainWindow
from .demo import tunnel_model
from .dialogs import sample_model
from .result_tools import BeamDiagramDialog, QueryDialog


def smoke_check(app, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "version": __version__,
        "success": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "numpy_path": np.__file__,
    }
    window = None
    try:
        # Exercise the bundled DXF reader/writer and optional native dependencies.
        from ..cad.dxf import read_dxf, write_dxf
        from ..cad.geometry import Drawing

        write_dxf(Drawing.example(), directory / "drawing.dxf")
        read_dxf(directory / "drawing.dxf", metres_per_unit=1.0).validate()
        expected = api.run(tunnel_model())
        window = MainWindow()
        window.set_model(tunnel_model())
        window.show()
        app.processEvents()
        window.start_solve()
        until = time.monotonic() + 180
        while window.busy and time.monotonic() < until:
            app.processEvents()
            QTest.qWait(10)
        if window.busy:
            window.cancel_solve()
            raise RuntimeError("Portable solver exceeded 180 seconds")
        if window.result is None:
            raise RuntimeError(window.log.toPlainText())
        actual = window.result
        for a, b in zip(actual.stages, expected.stages):
            np.testing.assert_allclose(a.u, b.u, rtol=0, atol=0, equal_nan=True)
        window.principal.setChecked(True)
        window.plastic_points.setChecked(True)
        app.processEvents()
        window.grab().save(str(directory / "portable-tunnel.png"))
        window.save_path(directory / "tunnel.ssproj")
        reopened = api.load_project(directory / "tunnel.ssproj")
        np.testing.assert_allclose(
            reopened.results.last.u, expected.last.u, rtol=0, atol=0, equal_nan=True
        )
        query = QueryDialog(actual, actual.last)
        query.query()
        query.export_path(directory / "query.csv")
        beam = BeamDiagramDialog(actual, actual.last)
        beam.export_path(directory / "liner.csv")
        export_csv(actual, directory / "nodes.csv")
        export_html(actual, directory / "report.html")
        api.export_vtu(actual, directory / "tunnel.vtu")
        # Trigger a compiled plastic material kernel as well as the elastic tunnel path.
        from ..fem._jit import HAVE_NUMBA

        if not HAVE_NUMBA:
            raise RuntimeError("Bundled Numba could not be imported")
        report["numba_enabled"] = HAVE_NUMBA
        plastic = sample_model(nx=1, ny=1, load=10)
        plastic.materials = {"soil": api.MaterialSpec.mohr_coulomb("soil", 20000, 0.3, 20, 30)}
        assert np.isfinite(api.run(plastic).last.u).all()
        report.update(
            success=True,
            nodes=actual.model.mesh.nn,
            states=4,
            max_displacement_m=float(np.nanmax(np.linalg.norm(actual.last.u, axis=1))),
        )
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        (directory / "smoke-result.json").write_text(json.dumps(report, indent=2), "utf-8")
        if window is not None and not window.busy:
            window.dirty = False
            window.close()
            app.processEvents()
    code = 0 if report["success"] else 1
    # Frozen Qt builds can abort in interpreter finalization after a successful check.
    if getattr(sys, "frozen", False):
        os._exit(code)
    return code
