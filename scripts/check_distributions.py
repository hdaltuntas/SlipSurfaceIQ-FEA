"""Fail a release build if environments/binaries leaked into Python distributions."""

import sys
import tarfile
import zipfile
from pathlib import Path

folder = Path(sys.argv[1])
archives = sorted(folder.glob("*.whl")) + sorted(folder.glob("*.tar.gz"))
if len(archives) != 2:
    raise RuntimeError("Expected one wheel and one source distribution")
for archive in archives:
    if archive.stat().st_size > 20_000_000:
        raise RuntimeError(f"{archive.name}: unexpectedly large Python distribution")
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as stream:
            names = stream.namelist()
    else:
        with tarfile.open(archive) as stream:
            names = stream.getnames()
    bad = [
        n
        for n in names
        if any(
            part in {".venv", ".portable-env", "site-packages", "__pycache__"}
            for part in Path(n).parts
        )
    ]
    if bad:
        raise RuntimeError(f"Build environment leaked into {archive.name}: {bad[:5]}")
    if not any(n.endswith("slipsurface/fe2d/gui/app.py") for n in names):
        raise RuntimeError(f"{archive.name}: missing native GUI source")
    print(f"{archive.name}: {archive.stat().st_size} bytes, content check passed")
