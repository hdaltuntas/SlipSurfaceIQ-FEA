"""PyInstaller entry: bounded thread use and writable Numba cache location."""

import multiprocessing
import os
from pathlib import Path

if __name__ == "__main__":
    multiprocessing.freeze_support()
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SlipSurfaceIQ-FEA" / "numba"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(cache))
    from slipsurface.fe2d.gui.app import main

    raise SystemExit(main())
