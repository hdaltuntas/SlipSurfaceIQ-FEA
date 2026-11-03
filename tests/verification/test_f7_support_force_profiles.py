"""F7 synthetic structural profiles: order invariance and missing-support checks."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from slipsurface.fe2d.post.support_audit import compare_profiles, sample_support_profile


def mesh_with_beam(order=(0, 1)):
    coords = np.array([[0., 0.], [1., 0.], [2., 0.]])
    blocks = {"pile": SimpleNamespace(
        ne=2, conn=np.array([[0, 1], [1, 2]])[list(order)]
    )}
    return SimpleNamespace(coords=coords, block=blocks.__getitem__)


def test_beam_moment_distribution_independent_of_mesh_element_order():
    a = mesh_with_beam()
    stage = SimpleNamespace(beams={"pile": np.array([
        [[0., 0., 0.], [0., 0., 1.]],
        [[0., 0., 1.], [0., 0., 2.]],
    ])}, bars={})
    before = sample_support_profile(
        a, stage, "pile", [(0., 0.), (2., 0.)], count=5
    )
    assert np.asarray(before["components"])[:, 2] == pytest.approx(
        [0., 0.5, 1., 1.5, 2.]
    )
    reordered = mesh_with_beam((1, 0))
    shuffled = SimpleNamespace(
        beams={"pile": stage.beams["pile"][[1, 0]]}, bars={},
    )
    after = sample_support_profile(
        reordered, shuffled, "pile", [(0., 0.), (2., 0.)], count=5
    )
    assert compare_profiles(before, after) == pytest.approx([0., 0., 0.])


def test_bolt_profile_remesh_comparison_uses_common_axis():
    mesh = SimpleNamespace(
        coords=np.array([[0., 0.], [1., 0.], [2., 0.]]),
        block=lambda _tag: SimpleNamespace(
            conn=np.array([[0, 1], [1, 2]]), ne=2,
        ),
    )
    one = SimpleNamespace(beams={}, bars={"bolt": np.array([10., 20.])})
    two = SimpleNamespace(beams={}, bars={"bolt": np.array([10., 20.])})
    lhs = sample_support_profile(mesh, one, "bolt", [(0., 0.), (2., 0.)], kind="bar")
    rhs = sample_support_profile(mesh, two, "bolt", [(0., 0.), (2., 0.)], kind="bar")
    assert compare_profiles(lhs, rhs) == pytest.approx([0.])
    rhs["components"] = (np.asarray(rhs["components"]) * 1.1).tolist()
    assert compare_profiles(lhs, rhs)[0] == pytest.approx(1.0 / 11.0)


def test_missing_support_and_invalid_geometry_are_not_silently_zeroed():
    mesh = mesh_with_beam()
    stage = SimpleNamespace(beams={}, bars={})
    with pytest.raises(KeyError, match="Missing active beam"):
        sample_support_profile(mesh, stage, "pile", [(0., 0.), (2., 0.)])
    populated = SimpleNamespace(
        beams={"pile": np.zeros((2, 2, 3))}, bars={},
    )
    with pytest.raises(ValueError, match="distinct"):
        sample_support_profile(mesh, populated, "pile", [(0., 0.), (0., 0.)])
    with pytest.raises(ValueError, match="At least two"):
        sample_support_profile(mesh, populated, "pile", [(0., 0.), (2., 0.)], count=1)


def test_comparison_rejects_nonmatching_tags_or_sampling_grid():
    sample = {"tag": "pile", "kind": "beam", "s": [0., 1.],
              "components": [[1., 2., 3.], [2., 3., 4.]]}
    with pytest.raises(ValueError, match="identities"):
        compare_profiles(sample, {**sample, "tag": "other"})
    with pytest.raises(ValueError, match="stations"):
        compare_profiles(sample, {**sample, "s": [0., 0.5]})


def test_signed_beam_profile_preserves_negative_moment_and_shear():
    mesh = mesh_with_beam()
    stage = SimpleNamespace(beams={"pile": np.array([
        [[0., -2., -4.], [0., -2., -3.]],
        [[0., -2., -3.], [0., -2., -1.]],
    ])}, bars={})
    signed = sample_support_profile(
        mesh, stage, "pile", [(0., 0.), (2., 0.)], count=5, signed=True
    )
    magnitude = sample_support_profile(
        mesh, stage, "pile", [(0., 0.), (2., 0.)], count=5
    )
    assert signed["mode"] == "signed_local"
    assert np.asarray(signed["components"])[:, 2] == pytest.approx(
        [-4., -3.5, -3., -2., -1.]
    )
    assert np.asarray(signed["components"])[:, 1] == pytest.approx([-2.] * 5)
    assert np.asarray(magnitude["components"])[:, 2] == pytest.approx(
        [4., 3.5, 3., 2., 1.]
    )
    with pytest.raises(ValueError, match="signed and magnitude"):
        compare_profiles(signed, magnitude)


def test_signed_beam_rejects_reversed_element_orientation():
    mesh = mesh_with_beam((1, 0))
    stage = SimpleNamespace(beams={"pile": np.zeros((2, 2, 3))}, bars={})
    # Reverse a single element's *node order*, not just its mesh index.
    mesh.block("pile").conn[0] = mesh.block("pile").conn[0, ::-1]
    with pytest.raises(ValueError, match="consistent CAD orientation"):
        sample_support_profile(
            mesh, stage, "pile", [(0., 0.), (2., 0.)], signed=True
        )
    # Legacy unsigned reporting remains orientation-agnostic.
    report = sample_support_profile(
        mesh, stage, "pile", [(0., 0.), (2., 0.)]
    )
    assert report["mode"] == "magnitude"


def test_signed_bar_preserves_axial_compression():
    mesh = SimpleNamespace(
        coords=np.array([[0., 0.], [1., 0.], [2., 0.]]),
        block=lambda _tag: SimpleNamespace(
            ne=2, conn=np.array([[0, 1], [1, 2]])
        ),
    )
    stage = SimpleNamespace(beams={}, bars={"bolt": np.array([-8., -12.])})
    signed = sample_support_profile(
        mesh, stage, "bolt", [(0., 0.), (2., 0.)], kind="bar",
        signed=True, count=3,
    )
    assert np.asarray(signed["components"])[:, 0] == pytest.approx(
        [-8., -10., -12.]
    )
