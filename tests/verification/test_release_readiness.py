from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "release_readiness.py")
)
assess = _MOD["assess"]
main = _MOD["main"]

GATES = (
    (
        ".github/workflows/external-benchmarks.yml",
        "scripts/rs2_introduction_benchmark.py",
    ),
    (
        ".github/workflows/external-benchmarks.yml",
        "scripts/plaxis_tutorial01a_benchmark.py",
    ),
    (
        ".github/workflows/external-benchmarks.yml",
        "scripts/plaxis_phi_c_bishop_benchmark.py",
    ),
    (
        ".github/workflows/plaxis-drain-benchmark.yml",
        "scripts/plaxis_drain_benchmark.py",
    ),
)


def fixture(tmp_path: Path) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.9.0"\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "phase5-release.md").write_text(
        "source-only operation\npython main.py\n", encoding="utf-8"
    )
    grouped = {}
    for workflow, script in GATES:
        (tmp_path / script).write_text("# benchmark\n", encoding="utf-8")
        grouped.setdefault(workflow, []).append(script)
    for workflow, scripts in grouped.items():
        commands = "\n".join(
            f"          python {script} --require-pass\n      - name: next"
            for script in scripts
        )
        path = tmp_path / workflow
        path.write_text(
            "name: benchmark\njobs:\n  verify:\n    steps:\n" + commands + "\n",
            encoding="utf-8",
        )
    return tmp_path


def write_acceptance(root: Path, *, platform: str = "Windows 11") -> None:
    evidence = root / "docs" / "data" / "release-acceptance"
    evidence.mkdir(parents=True, exist_ok=True)
    screenshots = []
    for name in ("tunnel-ui.png", "sheet-pile-ui.png"):
        path = evidence / name
        path.write_bytes(b"png")
        screenshots.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (root / "docs" / "release-acceptance.json").write_text(
        json.dumps({
            "phase5_user_acceptance": True,
            "platform": platform,
            "checks": {
                "workflow": True,
                "readability": True,
                "results": True,
                "save_reopen": True,
            },
            "screenshots": screenshots,
        }),
        encoding="utf-8",
    )


def test_current_main_style_is_blocked_only_by_manual_windows_acceptance(tmp_path):
    report = assess(fixture(tmp_path))
    assert report["ready_for_v1"] is False
    assert report["blockers"] == ["manual_windows_acceptance"]
    assert report["checks"]["external_tutorial_suite"]["status"] == "pass"
    assert report["version"] == "0.9.0"


def test_release_ready_after_manual_acceptance_when_four_strict_benchmarks_exist(tmp_path):
    root = fixture(tmp_path)
    write_acceptance(root)
    report = assess(root)
    assert report["ready_for_v1"] is True
    assert report["blockers"] == []
    assert "1.0.0" in report["release_actions"][0]


def test_each_benchmark_requires_its_own_require_pass(tmp_path):
    for workflow_name, script in GATES:
        root = fixture(tmp_path / script.replace("/", "_"))
        workflow = root / workflow_name
        text = workflow.read_text(encoding="utf-8")
        text = text.replace(
            f"python {script} --require-pass",
            f"python {script}",
            1,
        )
        workflow.write_text(text, encoding="utf-8")
        report = assess(root)
        assert report["checks"]["external_tutorial_suite"]["status"] == "blocked"
        assert "external_tutorial_suite" in report["blockers"]


def test_missing_benchmark_script_keeps_external_suite_blocked(tmp_path):
    root = fixture(tmp_path)
    (root / "scripts" / "plaxis_drain_benchmark.py").unlink()
    report = assess(root)
    assert report["checks"]["external_tutorial_suite"]["status"] == "blocked"


def test_custom_s4_external_files_are_not_required_for_v1(tmp_path):
    root = fixture(tmp_path)
    write_acceptance(root)
    assert not (root / "docs" / "data" / "s4" / "external.csv").exists()
    assert assess(root)["ready_for_v1"] is True



def test_modified_screenshot_does_not_close_windows_acceptance(tmp_path):
    root = fixture(tmp_path)
    write_acceptance(root)
    screenshot = root / "docs" / "data" / "release-acceptance" / "tunnel-ui.png"
    screenshot.write_bytes(b"changed")
    report = assess(root)
    assert report["checks"]["manual_windows_acceptance"]["status"] == "blocked"
    assert "hash" in report["checks"]["manual_windows_acceptance"]["detail"].lower()

def test_non_windows_manual_acceptance_does_not_close_gate(tmp_path):
    root = fixture(tmp_path)
    write_acceptance(root, platform="Linux offscreen")
    assert assess(root)["checks"]["manual_windows_acceptance"]["status"] == "blocked"


def test_incomplete_windows_acceptance_does_not_close_gate(tmp_path):
    root = fixture(tmp_path)
    (root / "docs" / "release-acceptance.json").write_text(
        json.dumps({
            "phase5_user_acceptance": True,
            "platform": "Windows 11",
            "checks": {"workflow": True},
            "screenshots": [],
        }),
        encoding="utf-8",
    )
    assert assess(root)["checks"]["manual_windows_acceptance"]["status"] == "blocked"


def test_require_ready_is_opt_in(tmp_path):
    root = fixture(tmp_path)
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--require-ready"]) == 1
    write_acceptance(root)
    assert main(["--root", str(root), "--require-ready"]) == 0


def test_reports_can_be_written_without_changing_verdict(tmp_path):
    root = fixture(tmp_path)
    j = tmp_path / "out" / "readiness.json"
    m = tmp_path / "out" / "readiness.md"
    assert main([
        "--root", str(root), "--json", str(j), "--markdown", str(m)
    ]) == 0
    data = json.loads(j.read_text(encoding="utf-8"))
    assert data["ready_for_v1"] is False
    assert "Ready for v1.0.0: **NO**" in m.read_text(encoding="utf-8")
