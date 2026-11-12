from __future__ import annotations

import json
import runpy
from pathlib import Path

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "release_readiness.py")
)
assess = _MOD["assess"]
main = _MOD["main"]


def fixture(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "data" / "s4").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.9.0"\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "phase5-release.md").write_text(
        "source-only operation\npython main.py\n", encoding="utf-8"
    )
    return tmp_path


def test_current_style_repo_is_blocked_without_manual_and_external_acceptance(tmp_path):
    report = assess(fixture(tmp_path))
    assert report["ready_for_v1"] is False
    assert set(report["blockers"]) == {
        "manual_windows_acceptance", "external_s4_validation"
    }
    assert report["version"] == "0.9.0"


def test_release_ready_requires_real_external_source_and_windows_acceptance(tmp_path):
    root = fixture(tmp_path)
    (root / "docs" / "data" / "s4" / "external.csv").write_text(
        "depth_m,M_kNm_per_m,u_top_mm,source\n0,10,2.1,RS2\n5,20,3.4,plaxis2d\n",
        encoding="utf-8",
    )
    (root / "docs" / "release-acceptance.json").write_text(
        json.dumps({"phase5_user_acceptance": True, "platform": "Windows 11"}),
        encoding="utf-8",
    )
    report = assess(root)
    assert report["ready_for_v1"] is True
    assert report["blockers"] == []
    assert "1.0.0" in report["release_actions"][0]


def test_internal_or_unknown_external_source_cannot_close_gate(tmp_path):
    root = fixture(tmp_path)
    (root / "docs" / "data" / "s4" / "external.csv").write_text(
        "depth_m,M_kNm_per_m,u_top_mm,source\n0,10,2.1,winkler\n", encoding="utf-8"
    )
    (root / "docs" / "release-acceptance.json").write_text(
        json.dumps({"phase5_user_acceptance": True, "platform": "Windows 11"}),
        encoding="utf-8",
    )
    report = assess(root)
    assert report["checks"]["external_s4_validation"]["status"] == "blocked"


def test_non_windows_manual_acceptance_does_not_close_gate(tmp_path):
    root = fixture(tmp_path)
    (root / "docs" / "release-acceptance.json").write_text(
        json.dumps({"phase5_user_acceptance": True, "platform": "Linux offscreen"}),
        encoding="utf-8",
    )
    assert assess(root)["checks"]["manual_windows_acceptance"]["status"] == "blocked"


def test_require_ready_is_opt_in(tmp_path):
    root = fixture(tmp_path)
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--require-ready"]) == 1


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
