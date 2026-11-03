"""F7: independently computed Mohr-Coulomb and Hoek-Brown yield boundaries.

Stresses are tension-positive (kPa), with principal s1 >= s3. The reference
equations below are evaluated independently of each model's yield_function.
These checks do not replace plastic-return/tangent tests elsewhere in the suite.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from slipsurface.fe2d.fem.materials import HoekBrown, MohrCoulomb, hb_parameters


@pytest.mark.parametrize("phi,c,s1", [
    (0.0, 12.0, 0.0),
    (20.0, 25.0, -120.0),
    (30.0, 10.0, -250.0),
    (40.0, 2.0, -80.0),
])
def test_mc_exact_principal_yield_boundary(phi, c, s1):
    """Compression-negative MC: k*s1 - s3 - 2*c*sqrt(k) = 0."""
    sin_phi = math.sin(math.radians(phi))
    k = (1.0 + sin_phi) / (1.0 - sin_phi)
    strength = 2.0 * c * math.sqrt(k)
    s3 = k * s1 - strength
    assert s1 >= s3
    mc = MohrCoulomb(30000.0, 0.25, c, phi, 0.0)
    boundary = np.array([[s1, s3, s3, 0.0]])
    assert mc.yield_function(boundary)[0] == pytest.approx(0.0, abs=1e-9)
    # More compressive minor principal stress moves inside the yield surface;
    # less compressive minor principal stress moves outside.
    inside = boundary.copy()
    inside[0, 1:3] -= 1.0
    outside = boundary.copy()
    outside[0, 1:3] += 1.0
    assert mc.yield_function(inside)[0] < 0.0
    assert mc.yield_function(outside)[0] > 0.0


@pytest.mark.parametrize("gsi,mi,disturbance,s1", [
    (30.0, 8.0, 0.0, 0.0),
    (50.0, 12.0, 0.5, -100.0),
    (75.0, 25.0, 0.0, -1000.0),
    (100.0, 15.0, 0.0, -200.0),
])
def test_hb_exact_generalized_principal_yield_boundary(gsi, mi, disturbance, s1):
    """HB: s1 - s3 = sigci*(s-mb*s1/sigci)^a in tension-positive signs."""
    sigci = 60000.0
    mb = mi * math.exp((gsi - 100.0) / (28.0 - 14.0 * disturbance))
    s = math.exp((gsi - 100.0) / (9.0 - 3.0 * disturbance))
    a = 0.5 + (
        math.exp(-gsi / 15.0) - math.exp(-20.0 / 3.0)
    ) / 6.0
    assert hb_parameters(gsi, mi, disturbance) == pytest.approx((mb, s, a))
    s3 = s1 - sigci * (s - mb * s1 / sigci) ** a
    hb = HoekBrown(50000.0, 0.25, sigci, mb, s, a)
    boundary = np.array([[s1, s3, s3, 0.0]])
    assert hb.yield_function(boundary)[0] == pytest.approx(0.0, abs=1e-7)
    inside = boundary.copy()
    inside[0, 1:3] -= 1.0
    outside = boundary.copy()
    outside[0, 1:3] += 1.0
    assert hb.yield_function(inside)[0] < 0.0
    assert hb.yield_function(outside)[0] > 0.0


@pytest.mark.parametrize("gsi,mi", [(35.0, 10.0), (65.0, 20.0)])
def test_hb_disturbance_reduces_compressive_strength(gsi, mi):
    """At s1=0, compressive minor-principal strength is sigci*s**a."""
    sigci = 50000.0
    strengths = []
    for disturbance in (0.0, 0.5, 1.0):
        mb, s, a = hb_parameters(gsi, mi, disturbance)
        strengths.append(sigci * s**a)
        hb = HoekBrown(50000.0, 0.25, sigci, mb, s, a)
        assert hb.yield_function(
            np.array([[0.0, -strengths[-1], -strengths[-1], 0.0]])
        )[0] == pytest.approx(0.0, abs=1e-7)
    assert strengths[0] > strengths[1] > strengths[2]


def test_mc_apex_is_independently_c_cot_phi():
    phi, cohesion = 35.0, 15.0
    mc = MohrCoulomb(30000.0, 0.3, cohesion, phi, psi=0.0)
    expected = cohesion / math.tan(math.radians(phi))
    assert mc.apex == pytest.approx(expected, rel=1e-12)
    hydrostatic = np.array([[expected, expected, expected, 0.0]])
    assert mc.yield_function(hydrostatic)[0] == pytest.approx(0.0, abs=1e-10)
