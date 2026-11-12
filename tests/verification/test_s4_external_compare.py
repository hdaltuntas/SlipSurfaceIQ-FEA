from __future__ import annotations

import csv
import json
import math
import runpy
from pathlib import Path

import pytest

_MOD = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "s4_external_compare.py")
)
compare = _MOD["compare"]
main = _MOD["main"]
REQUIRED_INPUT_MATCH = _MOD["REQUIRED_INPUT_MATCH"]


def fixture(tmp_path: Path, *, scale: float = 0.95, source: str = "RS2"):
    internal_profile = tmp_path / "internal.csv"
    with internal_profile.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["depth_m", "M_up_kNm_per_m"])
        for i in range(22):
            depth = i * 0.5
            moment = -100.0 * math.exp(-((depth - 6.0) / 2.0) ** 2)
            writer.writerow([depth, moment])

    internal_results = tmp_path / "results.json"
    internal_results.write_text(
        json.dumps(
            {
                "runs": {
                    "h0125": {
                        "case_sha256": "locked-case",
                        "max_abs_moment_kNm_per_m": 100.0,
                        "wall_top_ux_m": 0.03,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    meta = tmp_path / "external-meta.json"
    meta.write_text(
        json.dumps(
            {
                "schema": "slipsurface.s4-external.v1",
                "source": source,
                "program_version": "test-version",
                "case_sha256": "locked-case",
                "analysis": "plane_strain",
                "stage": "excavate",
                "converged": True,
                "input_match": {name: True for name in REQUIRED_INPUT_MATCH},
            }
        ),
        encoding="utf-8",
    )

    external = tmp_path / "external.csv"
    with external.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["depth_m", "M_kNm_per_m", "u_top_mm", "source"])
        for i in range(22):
            depth = i * 0.5
            moment = -100.0 * scale * math.exp(-((depth - 6.0) / 2.0) ** 2)
            writer.writerow([depth, moment, 32.0 if i == 0 else "", source])

    return external, meta, internal_profile, internal_results


def test_equivalent_external_solution_passes_existing_ten_percent_peak_criterion(tmp_path):
    report = compare(*fixture(tmp_path, scale=0.95))
    assert report["status"] == "passed"
    assert report["checks"]["peak_moment_within_10_percent"] is True
    assert report["metrics"]["peak_moment_relative_error"] == pytest.approx(5 / 95)
    assert report["metrics"]["external_top_ux_mm"] == 32.0


def test_peak_moment_outside_ten_percent_fails(tmp_path):
    report = compare(*fixture(tmp_path, scale=0.75))
    assert report["status"] == "failed"
    assert report["checks"]["peak_moment_within_10_percent"] is False


def test_reversed_moment_sign_is_not_silently_accepted(tmp_path):
    external, meta, internal, results = fixture(tmp_path)
    rows = list(csv.reader(external.read_text(encoding="utf-8").splitlines()))
    for row in rows[1:]:
        row[1] = str(-float(row[1]))
    with external.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    report = compare(external, meta, internal, results)
    assert report["status"] == "failed"
    assert report["checks"]["moment_sign_convention"] is False


def test_metadata_must_match_locked_case(tmp_path):
    external, meta, internal, results = fixture(tmp_path)
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["case_sha256"] = "other-case"
    meta.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="locked S4 case"):
        compare(external, meta, internal, results)


def test_input_equivalence_must_be_explicit(tmp_path):
    external, meta, internal, results = fixture(tmp_path)
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["input_match"]["tip_connection"] = False
    meta.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="tip_connection"):
        compare(external, meta, internal, results)


def test_profile_must_cover_wall_with_dense_enough_output(tmp_path):
    external, meta, internal, results = fixture(tmp_path)
    rows = list(csv.reader(external.read_text(encoding="utf-8").splitlines()))
    sparse = [rows[0], rows[1], rows[5], rows[9], rows[13], rows[17], rows[21], rows[-1]]
    with external.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(sparse)
    with pytest.raises(ValueError, match="gap|at least"):
        compare(external, meta, internal, results)


def test_top_displacement_is_required_only_at_wall_head(tmp_path):
    external, meta, internal, results = fixture(tmp_path)
    rows = list(csv.reader(external.read_text(encoding="utf-8").splitlines()))
    rows[1][2] = ""
    rows[2][2] = "32"
    with external.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    with pytest.raises(ValueError, match="depth 0"):
        compare(external, meta, internal, results)


def test_cli_require_pass_is_opt_in(tmp_path):
    external, meta, internal, results = fixture(tmp_path, scale=0.75)
    args = [
        "--external", str(external),
        "--meta", str(meta),
        "--internal-profile", str(internal),
        "--internal-results", str(results),
    ]
    assert main(args) == 0
    assert main(args + ["--require-pass"]) == 1
