"""Pseudo-static stage coefficient validation and project serialization tests."""

from dataclasses import replace

import pytest

from slipsurface.fe2d.model.stages import Stage


@pytest.mark.parametrize("kh,kv", [(0.15, 0.0), (-0.2, 0.1), (0.0, -0.3)])
def test_valid_pseudostatic_coefficients(kh, kv):
    stage = Stage("Seismic", seismic_kh=kh, seismic_kv=kv)
    assert stage.seismic_kh == kh
    assert stage.seismic_kv == kv


@pytest.mark.parametrize("kh,kv", [(float("nan"), 0), (float("inf"), 0),
                                    (1.01, 0), (0, -1.01)])
def test_invalid_pseudostatic_coefficients(kh, kv):
    with pytest.raises(ValueError, match="Seismic coefficients"):
        Stage("Invalid", seismic_kh=kh, seismic_kv=kv)


def test_stage_replace_retains_seismic_data():
    stage = Stage("Excavation", seismic_kh=0.13, seismic_kv=-0.04)
    updated = replace(stage, name="Excavation 2")
    assert (updated.seismic_kh, updated.seismic_kv) == (0.13, -0.04)
