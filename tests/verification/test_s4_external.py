"""S4 external comparison gate.

The gate remains skipped while independent RS2/PLAXIS evidence is absent. Once
external.csv is committed, the locked-case metadata and quantitative comparison
must pass; a file existing by itself is not verification.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = ROOT / "docs" / "data" / "s4" / "external.csv"
META = ROOT / "docs" / "data" / "s4" / "external-meta.json"
INTERNAL_PROFILE = ROOT / "docs" / "data" / "s4" / "h0125-wall-end-forces.csv"
INTERNAL_RESULTS = ROOT / "docs" / "data" / "s4" / "results.json"
_MOD = runpy.run_path(str(ROOT / "scripts" / "s4_external_compare.py"))
compare = _MOD["compare"]


def test_external_s4_is_quantitatively_verified_when_evidence_exists():
    if not EXTERNAL.exists():
        pytest.skip(
            "RS2/PLAXIS S4 evidence is absent. Skip is not a verification pass."
        )
    assert META.exists(), "external.csv requires external-meta.json from the independent model"
    report = compare(EXTERNAL, META, INTERNAL_PROFILE, INTERNAL_RESULTS)
    assert report["status"] == "passed", report
    assert report["checks"]["peak_moment_within_10_percent"] is True
