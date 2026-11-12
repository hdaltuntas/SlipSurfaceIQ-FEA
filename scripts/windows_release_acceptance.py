"""Prepare and record the manual Windows usability gate for SlipSurfaceIQ-FEA 1.0.

Preparation does not close the gate. Recording is allowed only on Windows and only
after explicit checklist confirmations plus two user-captured screenshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_NUMERIC = (
    "tunnel-log.txt",
    "sheet-pile-log.txt",
    "sheet-pile-nvm.csv",
)
SCREENSHOTS = ("tunnel-ui.png", "sheet-pile-ui.png")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _windows_platform() -> str:
    return f"{platform.system()} {platform.release()} ({platform.version()})"


def prepare(out: Path, *, run_cases: bool = True) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    numeric = out / "numeric"
    numeric.mkdir(exist_ok=True)
    if run_cases:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "phase5_cases.py"),
                "--out",
                str(numeric),
                "--tunnel",
                "--sheet-pile",
            ],
            cwd=ROOT,
            check=True,
        )
    checklist = out / "WINDOWS-ACCEPTANCE-CHECKLIST.md"
    checklist.write_text(
        """# SlipSurfaceIQ-FEA 1.0 Windows usability acceptance

This is a manual product acceptance, not an automated test.

## Environment

1. Use a real Windows desktop session.
2. Install dependencies with: python -m pip install -r requirements.txt
3. Start the application with: python main.py
4. Do not edit source code during the acceptance session.

## Tunnel workflow

From a blank project, build the four-state tunnel workflow used by the Phase 5
acceptance case: geometry, rock material, excavation stages, shotcrete and bolt.
Generate the mesh, solve all stages, inspect deformation/contours and liner N/V/M.

Acceptance criteria:
- all labels, menus, dialogs and stage controls are readable;
- the CAD/model area remains usable without hidden required controls;
- the model can be completed without editing Python/JSON;
- solve completes without crash;
- stage switching and result selection are understandable;
- N/V/M plot and result table are readable;
- save, close, reopen and result inspection work.

Save a screenshot showing the solved model, stage/result controls and readable UI as
tunnel-ui.png in this acceptance folder.

## Sheet-pile workflow

Build or open the S4 sheet-pile case through the supported desktop workflow. Solve it,
inspect wall displacement and N/V/M, then save/reopen the project.

Acceptance criteria are the same as above. Save sheet-pile-ui.png.

## Numerical cross-check

Compare the visible qualitative/peak outputs with files under numeric/.
These files are internal SlipSurface references only and do NOT close the separate
RS2/PLAXIS validation gate.

## Record acceptance

Only if every item above is acceptable, run:

python scripts/windows_release_acceptance.py record --evidence WINDOWS_FOLDER --accept-workflow --accept-readability --accept-results --accept-save-reopen --note "Accepted for SlipSurfaceIQ-FEA 1.0 usability"

The command copies the screenshots into docs/data/release-acceptance/ and writes
docs/release-acceptance.json. If any item is not acceptable, do not run record;
report the defect instead.
""",
        encoding="utf-8",
    )
    return checklist


def _require_evidence(evidence: Path) -> list[Path]:
    missing = []
    for name in REQUIRED_NUMERIC:
        path = evidence / "numeric" / name
        if not path.is_file():
            missing.append(str(path))
    for name in SCREENSHOTS:
        path = evidence / name
        if not path.is_file():
            missing.append(str(path))
    if missing:
        raise FileNotFoundError("Missing acceptance evidence: " + ", ".join(missing))
    return [evidence / name for name in SCREENSHOTS]


def record(
    evidence: Path,
    *,
    accept_workflow: bool,
    accept_readability: bool,
    accept_results: bool,
    accept_save_reopen: bool,
    note: str,
    root: Path = ROOT,
    system_name: str | None = None,
) -> dict:
    system_name = platform.system() if system_name is None else system_name
    if system_name.lower() != "windows":
        raise RuntimeError("Manual v1 usability acceptance must be recorded on Windows.")
    accepted = {
        "workflow": accept_workflow,
        "readability": accept_readability,
        "results": accept_results,
        "save_reopen": accept_save_reopen,
    }
    failed = [name for name, ok in accepted.items() if not ok]
    if failed:
        raise ValueError("Acceptance cannot be recorded; unchecked: " + ", ".join(failed))
    screenshots = _require_evidence(evidence)
    destination = root / "docs" / "data" / "release-acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in screenshots:
        target = destination / source.name
        shutil.copyfile(source, target)
        copied.append(
            {
                "path": target.relative_to(root).as_posix(),
                "sha256": _sha256(target),
            }
        )
    record_path = root / "docs" / "release-acceptance.json"
    payload = {
        "schema": "slipsurface.windows-usability-acceptance.v1",
        "phase5_user_acceptance": True,
        "platform": _windows_platform() if system_name == platform.system() else "Windows",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": accepted,
        "screenshots": copied,
        "numeric_reference": [
            {
                "path": (evidence / "numeric" / name).as_posix(),
                "sha256": _sha256(evidence / "numeric" / name),
                "claim": "internal_reference_only",
            }
            for name in REQUIRED_NUMERIC
        ],
        "note": note.strip(),
    }
    record_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out", type=Path, default=Path("windows-v1-acceptance"))
    prep.add_argument("--no-run-cases", action="store_true", help=argparse.SUPPRESS)

    rec = sub.add_parser("record")
    rec.add_argument("--evidence", type=Path, required=True)
    rec.add_argument("--accept-workflow", action="store_true")
    rec.add_argument("--accept-readability", action="store_true")
    rec.add_argument("--accept-results", action="store_true")
    rec.add_argument("--accept-save-reopen", action="store_true")
    rec.add_argument("--note", default="")

    args = parser.parse_args(argv)
    if args.command == "prepare":
        path = prepare(args.out, run_cases=not args.no_run_cases)
        print(f"Prepared Windows acceptance checklist: {path}")
        return 0
    payload = record(
        args.evidence,
        accept_workflow=args.accept_workflow,
        accept_readability=args.accept_readability,
        accept_results=args.accept_results,
        accept_save_reopen=args.accept_save_reopen,
        note=args.note,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
