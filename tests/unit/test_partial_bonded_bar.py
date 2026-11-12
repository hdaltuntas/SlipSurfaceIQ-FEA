from __future__ import annotations

import numpy as np
import pytest

from slipsurface.fe2d.core.enums import ElemType
from slipsurface.fe2d.core.errors import MeshError
from slipsurface.fe2d.mesh.structures import add_bar_with_bonded_tail
from slipsurface.fe2d.model import Mesh


def _mesh(edges, *, coords=None):
    if coords is None:
        coords = [[float(i), 0.0] for i in range(6)]
    return Mesh(
        np.asarray(coords, dtype=float),
        (),
        {},
        {"bond": np.asarray(edges, dtype=np.int64)},
    )


def test_free_length_plus_linear_bonded_tail_share_one_bar_tag():
    source = _mesh([[1, 2], [2, 3]])
    result = add_bar_with_bonded_tail(source, 0, 1, "bond", "tieback")

    assert source.blocks == ()
    block = result.block("tieback")
    assert block.etype is ElemType.BAR2
    assert block.conn.tolist() == [[0, 1], [1, 2], [2, 3]]
    assert block.region.tolist() == [0, 0, 0]


def test_quadratic_bond_edge_is_split_into_linear_bar_segments():
    source = _mesh([[1, 3, 2]], coords=[[0, 0], [1, 0], [2, 0], [3, 0]])
    result = add_bar_with_bonded_tail(source, 0, 1, "bond", "tieback")
    assert result.block("tieback").conn.tolist() == [[0, 1], [1, 2], [2, 3]]


@pytest.mark.parametrize(
    ("edges", "head", "start", "message"),
    [
        ([[1, 2], [2, 3], [2, 4]], 0, 1, "non-branching open chain"),
        ([[1, 2], [3, 4]], 0, 1, "non-branching open chain"),
        ([[1, 2], [2, 3]], 0, 2, "endpoint"),
        ([[1, 2], [2, 3]], 3, 1, "outside the bonded edge chain"),
        ([[1, 1]], 0, 1, "zero-length"),
    ],
)
def test_invalid_bonded_tail_topologies_are_rejected(edges, head, start, message):
    with pytest.raises(MeshError, match=message):
        add_bar_with_bonded_tail(_mesh(edges), head, start, "bond", "tieback")


def test_existing_structure_tag_is_not_overwritten():
    source = _mesh([[1, 2], [2, 3]])
    result = add_bar_with_bonded_tail(source, 0, 1, "bond", "tieback")
    with pytest.raises(MeshError, match="already exists"):
        add_bar_with_bonded_tail(result, 4, 1, "bond", "tieback")
