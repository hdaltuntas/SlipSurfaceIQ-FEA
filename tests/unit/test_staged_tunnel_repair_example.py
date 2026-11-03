"""Regression tests for the uploaded staged tunnel example correction."""

from copy import deepcopy
from pathlib import Path
import runpy

import pytest


REPAIR = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "examples" /
        "repair_staged_tunnel_project.py")
)["repair_document"]


def sample():
    stages = [
        {"name": name, "active_regions": regions, "active_structures": []}
        for name, regions in [
            ("CAD loading", [1, 3, 4]),
            ("Stage 2", [1, 4]),
            ("Stage 3", [1]),
            ("Stage 4", [1]),
        ]
    ]
    return {
        "stages": stages,
        "bolts": {
            **{f"cad_Bolt_Tunnel_SC_Head_{i}": {} for i in range(1, 17)},
            **{f"cad_Bolt_Tunnel_SC_Bench_{side}_{i}": {}
               for side in ("Left", "Right") for i in (1, 2)},
        },
        "liners": {name: {} for name in (
            "cad_Tunnel_SC_Head", "cad_Tunnel_SC_Bench_Left",
            "cad_Tunnel_SC_Bench_Right", "cad_Tunnel_SC_Inv",
            "cad_Tunnel_Bench", "cad_Tunnel_Inv",
        )},
        "fixities": [
            {"node_set": f"Region1:{i}", "ux": False, "uy": True}
            for i in (2, 3, 4)
        ],
        "geometry": {
            "entities": [{
                "name": "Region1",
                "points": [[28, 20], [102.5, 20], [102.5, -34], [28, -34]],
            }],
            "rules": [
                {"edge": f"Region1:{i}", "ux": False, "uy": True}
                for i in (2, 3, 4)
            ],
            "loading_name": "CAD loading",
            "sequence": [{"name": f"Stage {i}"} for i in (2, 3, 4)],
            "material_assignments": [
                {"stage": "Stage 2", "region": "Tunnel_Bench", "material": None}
            ],
            "supports": [{"entity": "Tunnel_SC_Head", "active": False}],
        },
    }


def test_example_staged_support_activation_and_roller_boundaries():
    original = sample()
    before = deepcopy(original)
    output = REPAIR(original)
    assert original == before
    assert [len(s["active_structures"]) for s in output["stages"]] == [
        17, 23, 24, 24
    ]
    assert all(
        "cad_Tunnel_Bench" not in s["active_structures"]
        and "cad_Tunnel_Inv" not in s["active_structures"]
        for s in output["stages"]
    )
    expected = {
        "Region1:2": (True, False),
        "Region1:3": (True, True),
        "Region1:4": (True, False),
    }
    assert {
        f["node_set"]: (f["ux"], f["uy"]) for f in output["fixities"]
    } == expected
    assert output["geometry"]["material_assignments"][0]["stage"] == (
        output["stages"][1]["name"]
    )
    assert output["geometry"]["supports"][0]["active"]


def test_unrelated_boundary_geometry_is_rejected():
    model = sample()
    model["geometry"]["entities"][0]["points"][0] = [0, 0]
    with pytest.raises(ValueError, match="Unexpected outer boundary"):
        REPAIR(model)


def test_unrelated_stage_topology_is_rejected():
    model = sample()
    model["stages"][0]["active_regions"] = [1]
    with pytest.raises(ValueError, match="Example repair expects"):
        REPAIR(model)
