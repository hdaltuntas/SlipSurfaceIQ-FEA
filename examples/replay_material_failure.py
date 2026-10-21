"""Replay bounded local inputs from diagnose_sheet_pile.py without a global solve.

PYTHONPATH=src python examples/replay_material_failure.py diagnostic.json
Equal strain subdivisions use the original material and committed state. They
are a diagnostic, not a replacement integrator or its algorithmic tangent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from slipsurface.fe2d.core.errors import MaterialIntegrationError
from slipsurface.fe2d.fem.materials import MohrCoulomb


def replay(details, subdivisions=(1, 2, 8, 32, 128)):
    """Return independent, JSON-safe results for every retained failing point."""
    material = MohrCoulomb(**details["params"])
    results = []
    for point in details["points"]:
        attempts = []
        for count in subdivisions:
            if count < 1:
                raise ValueError("subdivisions must be positive")
            sig = np.array([point["sig_n"]], dtype=float)
            q = np.array([point["q_n"]], dtype=float)
            deps = np.array([point["deps"]], dtype=float) / count
            completed = 0
            try:
                for _ in range(count):
                    sig, q, _, _ = material.integrate(sig, deps, q)
                    completed += 1
            except MaterialIntegrationError as exc:
                attempts.append(
                    {
                        "subdivisions": count,
                        "completed": completed,
                        "converged": False,
                        "failure": exc.details,
                    }
                )
            else:
                attempts.append(
                    {
                        "subdivisions": count,
                        "completed": completed,
                        "converged": True,
                        "sig": sig[0].tolist(),
                        "yield": float(material.yield_function(sig)[0]),
                    }
                )
        results.append({"input": point, "attempts": attempts})
    return {"params": details["params"], "block": details.get("block"), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostic", type=Path)
    parser.add_argument("--which", choices=["first", "last"], default="last")
    args = parser.parse_args()
    record = json.loads(args.diagnostic.read_text(encoding="utf-8"))
    failure = record.get(f"material_failure_{args.which}")
    if failure is None or failure.get("details") is None:
        parser.error("diagnostic contains no replayable local failure")
    print(json.dumps(replay(failure["details"]), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
