"""SlipSurfaceIQ FEA — start the desktop application.

Run from an IDE (open this file and press Run) or from a terminal:

    python main.py                                  # empty elastic model
    python main.py model.ssproj                     # open a project file
    python main.py model.json                       # open a model JSON
    python main.py --smoke-test DIR                 # installed-app smoke check
    python main.py --check                          # dependency check, no window

Works from any working directory: the src folder is put on sys.path, so
no installation is required (``pip install -e .`` is optional).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

REQUIRED = {
    "PySide6": "PySide6",
    "numpy": "numpy",
    "scipy": "scipy",
    "numba": "numba",
    "h5py": "h5py",
}
MIN_PYTHON = (3, 10)


def check_environment(verbose: bool = True) -> bool:
    ok = True
    if sys.version_info < MIN_PYTHON:
        print(
            f"[ERROR] Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required "
            f"(found {sys.version.split()[0]})."
        )
        ok = False
    missing = []
    for mod, pip_name in REQUIRED.items():
        try:
            m = importlib.import_module(mod)
            if verbose:
                print(f"  {mod:10s} {getattr(m, '__version__', '?')}")
        except ImportError:
            missing.append(pip_name)
    if missing:
        ok = False
        print("[ERROR] Missing package(s): " + ", ".join(missing))
        print("        Install:  python -m pip install -e \".[desktop]\"")
    if ok and verbose:
        print(f"  Python     {sys.version.split()[0]}  ({sys.executable})")
        print("Environment ready.")
    return ok


def main() -> int:
    import os

    args = sys.argv[1:]
    if "--check" in args:
        return 0 if check_environment() else 1
    if not check_environment(verbose=False):
        return 1
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from slipsurface.fe2d.gui.app import main as run_app

    return run_app([sys.argv[0], *args])


if __name__ == "__main__":
    raise SystemExit(main())
