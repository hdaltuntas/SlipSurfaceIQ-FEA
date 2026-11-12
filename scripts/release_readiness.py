from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re

REQUIRED_EXTERNAL_COLUMNS = ("depth_m", "M_kNm_per_m", "u_top_mm", "source")
ALLOWED_EXTERNAL_SOURCES = {"plaxis", "plaxis2d", "rs2"}


def _project_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    in_project = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if in_project:
            match = re.fullmatch(r'version\s*=\s*"([^"]+)"\s*(?:#.*)?', line)
            if match:
                return match.group(1)
    raise ValueError("pyproject.toml has no [project] version")


def _external_validation(root: Path) -> tuple[bool, str]:
    path = root / "docs" / "data" / "s4" / "external.csv"
    if not path.exists():
        return False, "Missing docs/data/s4/external.csv (RS2/PLAXIS comparison)."
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        missing = [name for name in REQUIRED_EXTERNAL_COLUMNS if name not in fields]
        if missing:
            return False, f"external.csv missing columns: {', '.join(missing)}"
        rows = list(reader)
    if not rows:
        return False, "external.csv contains no comparison rows."
    sources = {str(row.get("source", "")).strip().lower() for row in rows}
    if not sources or not sources <= ALLOWED_EXTERNAL_SOURCES:
        return False, "external.csv source must be RS2 or PLAXIS/PLAXIS2D."
    sources_text = ", ".join(sorted(sources))
    return True, f"External comparison present ({len(rows)} rows; {sources_text})."


def _user_acceptance(root: Path) -> tuple[bool, str]:
    path = root / "docs" / "release-acceptance.json"
    if not path.exists():
        return False, "Missing docs/release-acceptance.json manual Windows usability acceptance."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"release-acceptance.json is invalid JSON: {exc.msg}."
    if data.get("phase5_user_acceptance") is not True:
        return False, "phase5_user_acceptance must be true."
    platform = str(data.get("platform", "")).strip().lower()
    if "windows" not in platform:
        return False, "Manual acceptance must record a Windows test platform."
    note = str(data.get("note", "")).strip()
    detail = f"Manual usability acceptance recorded for {data.get('platform')}."
    return True, detail + (f" {note}" if note else "")


def _source_only_policy(root: Path) -> tuple[bool, str]:
    path = root / "docs" / "phase5-release.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    ok = "source-only operation" in text and "python main.py" in text
    return ok, (
        "Source-only distribution policy is explicitly documented."
        if ok else "Source-only distribution policy is missing from docs/phase5-release.md."
    )


def assess(root: Path) -> dict:
    version = _project_version(root)
    external_ok, external_detail = _external_validation(root)
    acceptance_ok, acceptance_detail = _user_acceptance(root)
    source_ok, source_detail = _source_only_policy(root)
    blockers = []
    checks = {
        "manual_windows_acceptance": {
            "status": "pass" if acceptance_ok else "blocked",
            "detail": acceptance_detail,
        },
        "external_s4_validation": {
            "status": "pass" if external_ok else "blocked",
            "detail": external_detail,
        },
        "source_only_distribution": {
            "status": "pass" if source_ok else "blocked",
            "detail": source_detail,
        },
    }
    for key, item in checks.items():
        if item["status"] != "pass":
            blockers.append(key)
    ready = not blockers
    release_actions = []
    if ready and version != "1.0.0":
        release_actions.append(
            f"Bump project version from {version} to 1.0.0 after final release commit is selected."
        )
    elif not ready:
        release_actions.append(
            f"Keep version at {version}; do not publish v1.0.0 while blockers remain."
        )
    return {
        "schema": "slipsurface.release-readiness.v1",
        "version": version,
        "ready_for_v1": ready,
        "blockers": blockers,
        "checks": checks,
        "release_actions": release_actions,
    }


def _markdown(report: dict) -> str:
    lines = [
        "# SlipSurfaceIQ-FEA 1.0 readiness",
        "",
        f"Current version: `{report['version']}`",
        f"Ready for v1.0.0: **{'YES' if report['ready_for_v1'] else 'NO'}**",
        "",
        "| Gate | Status | Detail |",
        "|---|---|---|",
    ]
    for name, item in report["checks"].items():
        lines.append(f"| `{name}` | {item['status'].upper()} | {item['detail']} |")
    lines.extend(["", "## Release actions", ""])
    lines.extend(f"- {item}" for item in report["release_actions"])
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report explicit SlipSurfaceIQ-FEA v1.0 release gates."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    report = assess(args.root)
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(payload, end="")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(payload, encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(_markdown(report), encoding="utf-8")
    return 1 if args.require_ready and not report["ready_for_v1"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
