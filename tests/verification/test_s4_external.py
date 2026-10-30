"""S4 external comparison is a closed gate, not a postponed pass.

An RS2 or PLAXIS table may be dropped at ``docs/data/s4/external.csv``. Until that
file exists this test skips: skipping is not a verification. Copying the internal
Winkler moments into that file is not accepted either; the column ``source`` must
name the external program.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXTERNAL = Path(__file__).resolve().parents[2] / "docs" / "data" / "s4" / "external.csv"
REQUIRED = ("depth_m", "M_kNm_per_m", "u_top_mm", "source")


def test_external_table_is_not_shipped_as_a_pass():
    if not EXTERNAL.exists():
        pytest.skip(
            "RS2/PLAXIS M(z) and head displacement are not in the repository. "
            "S4 is not externally verified; the internal Winkler model is not a substitute."
        )
    header = EXTERNAL.read_text(encoding="utf-8").splitlines()[0].strip().split(",")
    missing = [name for name in REQUIRED if name not in header]
    assert not missing, f"external.csv is missing columns {missing}"
    source = header.index("source")
    body = [
        line.split(",")[source].strip().lower()
        for line in EXTERNAL.read_text(encoding="utf-8").splitlines()[1:]
        if line.strip()
    ]
    assert body, "external.csv has no data rows"
    assert all(item in {"plaxis", "rs2", "plaxis2d"} for item in body), (
        "source must be PLAXIS or RS2; do not paste the internal Winkler result"
    )
