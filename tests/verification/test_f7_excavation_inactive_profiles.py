"""Inactive anchors are absent from profile sampling, not from reporting."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def check(mask, force):
    script = Path(__file__).resolve().parents[2] / "examples"
    fun = runpy.run_path(str(script / "f7_excavation_mesh_audit.py"))[
        "active_support_profile_available"
    ]
    state = SimpleNamespace(
        active={"anchor": np.array(mask, dtype=bool)},
        bars={"anchor": np.asarray(force, dtype=float)},
        beams={},
    )
    return fun(state, "anchor", "bar")


def test_nan_values_of_fully_inactive_anchor_are_skipped():
    assert check([False, False], [np.nan, np.nan]) is False


def test_active_anchor_with_finite_result_is_included():
    assert check([True, True], [3., 4.]) is True


def test_active_anchor_with_nan_force_still_fails():
    with pytest.raises(ValueError, match="nonfinite active"):
        check([True, True], [3., np.nan])


def test_partially_active_anchor_is_not_silently_skipped():
    with pytest.raises(ValueError, match="partially active"):
        check([True, False], [3., np.nan])
