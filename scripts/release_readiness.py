from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

BENCHMARK_GATES = (
    (
        "B1 RS2 Introduction",
        ".github/workflows/external-benchmarks.yml",
        "scripts/rs2_introduction_benchmark.py",
    ),
    (
        "B2 PLAXIS Tutorial 01A",
        ".github/workflows/external-benchmarks.yml",
        "scripts/plaxis_tutorial01a_benchmark.py",
    ),
    (
        "B3 PLAXIS phi-c/Bishop",
        ".github/workflows/external-benchmarks.yml",
        "scripts/plaxis_phi_c_bishop_benchmark.py",
    ),
    (
        "B4 PLAXIS Drain/Dupuit",
        ".github/workflows/plaxis-drain-benchmark.yml",
        "scripts/plaxis_drain_benchmark.py",
    ),
)


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


def _external_tutorial_suite(root: Path) -> tuple[bool, str]:
    problems = []
    workflow_cache = {}
    for label, workflow_name, script in BENCHMARK_GATES:
        script_path = root / script
        if not script_path.is_file():
            problems.append(f"{label}: missing {script}")
            continue
        workflow = root / workflow_name
        if not workflow.is_file():
            problems.append(f"{label}: missing {workflow_name}")
            continue
        if workflow_name not in workflow_cache:
            workflow_cache[workflow_name] = workflow.read_text(encoding="utf-8")
        text = workflow_cache[workflow_name]
        marker = f"python {script}"
        position = text.find(marker)
        if position < 0:
            problems.append(f"{label}: workflow does not run {script}")
            continue
        step_end = text.find("\n      - name:", position + len(marker))
        if step_end < 0:
            step_end = len(text)
        command_block = text[position:step_end]
        if "--require-pass" not in command_block:
            problems.append(f"{label}: benchmark is not a strict --require-pass gate")
    if problems:
        return False, "; ".join(problems)
    return True, (
        "B1 RS2 Introduction, B2 PLAXIS Tutorial 01A, B3 PLAXIS phi-c/Bishop "
        "and B4 PLAXIS Drain/Dupuit are mandatory --require-pass CI gates. "
        "Final release also requires all workflows to be green on the selected commit."
    )


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
    checks = data.get("checks")
    required = ("workflow", "readability", "results", "save_reopen")
    if not isinstance(checks, dict) or not all(checks.get(name) is True for name in required):
        return False, "Windows acceptance must explicitly pass all four usability checks."
    screenshots = data.get("screenshots")
    if not isinstance(screenshots, list) or len(screenshots) < 2:
        return False, "Windows acceptance must include at least two recorded screenshots."
    for item in screenshots:
        if not isinstance(item, dict):
            return False, "Windows acceptance screenshot entries must be objects."
        rel = str(item.get("path", ""))
        digest = str(item.get("sha256", ""))
        target = root / rel
        if not rel or not target.is_file() or len(digest) != 64:
            return False, "Windows acceptance screenshot evidence is missing or incomplete."
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
    benchmark_ok, benchmark_detail = _external_tutorial_suite(root)
    acceptance_ok, acceptance_detail = _user_acceptance(root)
    source_ok, source_detail = _source_only_policy(root)
    checks = {
        "manual_windows_acceptance": {
            "status": "pass" if acceptance_ok else "blocked",
            "detail": acceptance_detail,
        },
        "external_tutorial_suite": {
            "status": "pass" if benchmark_ok else "blocked",
            "detail": benchmark_detail,
        },
        "source_only_distribution": {
            "status": "pass" if source_ok else "blocked",
            "detail": source_detail,
        },
    }
    blockers = [key for key, item in checks.items() if item["status"] != "pass"]
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
        "schema": "slipsurface.release-readiness.v3",
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
