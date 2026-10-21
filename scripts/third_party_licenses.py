"""Copy installed distributions' licence files into the portable distribution."""

import importlib.metadata
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
license_dir = out / "THIRD_PARTY_LICENSES"
license_dir.mkdir(parents=True, exist_ok=True)
rows = [
    "# Third-party software",
    "",
    "Generated from the isolated portable build environment.",
    "Qt/PySide6 libraries are dynamically linked and replaceable in _internal.",
    "",
    "| Distribution | Version | Licence metadata |",
    "|---|---|---|",
]
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
    name = dist.metadata["Name"]
    license_text = (
        dist.metadata.get("License-Expression")
        or dist.metadata.get("License")
        or "; ".join(
            c for c in dist.metadata.get_all("Classifier", []) if c.startswith("License ::")
        )
        or "See licence files"
    )
    rows.append(f"| {name} | {dist.version} | {license_text.splitlines()[0].replace('|', '/')} |")
    for item in dist.files or ():
        p = Path(item)
        if p.is_absolute() or ".." in p.parts:
            continue
        if "licenses" in (x.lower() for x in p.parts) or p.name.lower().startswith(
            ("license", "licence", "copying", "notice")
        ):
            source = Path(dist.locate_file(item))
            if source.is_file():
                target = license_dir / name / p
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(out / "THIRD_PARTY_LICENSES.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
