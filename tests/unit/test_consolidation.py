"""Terzaghi 1D consolidation analytical verification and input contract."""

import math

import pytest

from slipsurface.fe2d.analysis.consolidation import ConsolidationInput


def sample(drainage="double"):
    return ConsolidationInput(
        thickness=4.0, sigma_initial=100.0, delta_sigma=100.0,
        compression_index=0.2, void_ratio=1.0, cv=0.01, drainage=drainage
    )


def test_primary_settlement_uses_oedometer_log_stress():
    case = sample()
    expected = 4.0 * 0.2 / 2.0 * math.log10(2.0)
    assert case.final_settlement() == pytest.approx(expected)
    assert case.settlement(0) == 0


def test_drainage_controls_rate_not_final_settlement():
    double = sample("double")
    single = sample("single")
    assert single.final_settlement() == pytest.approx(double.final_settlement())
    assert single.time_to_90() == pytest.approx(4 * double.time_to_90())
    assert double.degree(double.time_to_90()) == pytest.approx(0.90, abs=0.001)


def test_consolidation_monotonic_and_asymptotic():
    case = sample()
    times = [0.0, 10.0, 50.0, 100.0, 200.0, 1000.0]
    degrees = [case.degree(t) for t in times]
    assert degrees == sorted(degrees)
    assert degrees[0] == 0
    assert 0.99 < degrees[-1] <= 1
    assert case.settlement(1000.0) == pytest.approx(case.final_settlement(), rel=0.01)


def test_zero_stress_increment_is_zero_settlement():
    case = sample()
    zero = ConsolidationInput(
        case.thickness, case.sigma_initial, 0.0, case.compression_index,
        case.void_ratio, case.cv
    )
    assert zero.final_settlement() == 0.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("thickness", 0), ("sigma_initial", 0), ("cv", 0),
        ("void_ratio", -1), ("compression_index", -0.1),
        ("delta_sigma", -100), ("cv", float("nan")),
    ],
)
def test_reject_invalid_parameters(field, value):
    kwargs = {
        "thickness": 4.0, "sigma_initial": 100.0, "delta_sigma": 50.0,
        "compression_index": 0.2, "void_ratio": 1.0, "cv": 0.01
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        ConsolidationInput(**kwargs)


def test_reject_negative_elapsed_time():
    with pytest.raises(ValueError):
        sample().settlement(-1)
