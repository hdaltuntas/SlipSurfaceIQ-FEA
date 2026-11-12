from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "windows_release_acceptance.py")
)
prepare = _MOD["prepare"]
record = _MOD["record"]
SCREENSHOTS = _MOD["SCREENSHOTS"]
REQUIRED_NUMERIC = _MOD["REQUIRED_NUMERIC"]


def evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    numeric = root / "numeric"
    numeric.mkdir(parents=True)
    for name in REQUIRED_NUMERIC:
        (numeric / name).write_text(f"{name}\n", encoding="utf-8")
    for name in SCREENSHOTS:
        (root / name).write_bytes(b"png-evidence-" + name.encode())
    return root


def test_prepare_without_solves_writes_manual_checklist(tmp_path):
    checklist = prepare(tmp_path / "accept", run_cases=False)
    text = checklist.read_text(encoding="utf-8")
    assert "manual product acceptance" in text
    assert "tunnel-ui.png" in text
    assert "sheet-pile-ui.png" in text
    assert not (tmp_path / "accept" / "numeric" / "tunnel-log.txt").exists()


def test_record_rejects_non_windows_even_with_complete_evidence(tmp_path):
    with pytest.raises(RuntimeError, match="Windows"):
        record(
            evidence(tmp_path),
            accept_workflow=True,
            accept_readability=True,
            accept_results=True,
            accept_save_reopen=True,
            note="ok",
            root=tmp_path / "repo",
            system_name="Linux",
        )


def test_record_requires_every_explicit_acceptance_check(tmp_path):
    with pytest.raises(ValueError, match="readability"):
        record(
            evidence(tmp_path),
            accept_workflow=True,
            accept_readability=False,
            accept_results=True,
            accept_save_reopen=True,
            note="",
            root=tmp_path / "repo",
            system_name="Windows",
        )


def test_record_requires_numeric_and_screenshot_evidence(tmp_path):
    root = evidence(tmp_path)
    (root / "sheet-pile-ui.png").unlink()
    with pytest.raises(FileNotFoundError, match="sheet-pile-ui.png"):
        record(
            root,
            accept_workflow=True,
            accept_readability=True,
            accept_results=True,
            accept_save_reopen=True,
            note="",
            root=tmp_path / "repo",
            system_name="Windows",
        )


def test_record_copies_screenshots_and_writes_release_acceptance(tmp_path):
    repo = tmp_path / "repo"
    payload = record(
        evidence(tmp_path),
        accept_workflow=True,
        accept_readability=True,
        accept_results=True,
        accept_save_reopen=True,
        note="Accepted for v1",
        root=repo,
        system_name="Windows",
    )
    assert payload["phase5_user_acceptance"] is True
    assert payload["platform"].startswith("Windows")
    assert all(payload["checks"].values())
    assert len(payload["screenshots"]) == 2
    for item in payload["screenshots"]:
        assert len(item["sha256"]) == 64
        assert (repo / item["path"]).is_file()
    stored = json.loads((repo / "docs" / "release-acceptance.json").read_text())
    assert stored["note"] == "Accepted for v1"
    assert all(item["claim"] == "internal_reference_only" for item in stored["numeric_reference"])


def test_record_does_not_claim_external_validation(tmp_path):
    repo = tmp_path / "repo"
    payload = record(
        evidence(tmp_path),
        accept_workflow=True,
        accept_readability=True,
        accept_results=True,
        accept_save_reopen=True,
        note="ok",
        root=repo,
        system_name="Windows",
    )
    text = json.dumps(payload)
    assert "rs2" not in text.lower()
    assert "plaxis" not in text.lower()
