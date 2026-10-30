"""Write solve logs and N-V-M tables for the two Phase 5 acceptance cases.

    PYTHONPATH=src python scripts/phase5_cases.py --out /tmp/phase5
    PYTHONPATH=src python scripts/phase5_cases.py --out /tmp/phase5 --sheet-pile

Cases
-----
* four-state circular tunnel (initial field + three construction stages)
* S4 cantilever sheet pile, only with ``--sheet-pile`` (plastic, slower)

This does **not** close Phase 5. A Windows screenshot of the same two models,
with the solve log and the N-V-M diagram visible, is still required. Linux
offscreen output is not that acceptance.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))


def _write_beams(path: Path, mesh, result, tag: str) -> None:
    block = mesh.block(tag)
    forces = result.beams[tag]  # (ne, 2, 3) = N, V, M
    coords = mesh.coords[block.conn]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["element", "end", "x_m", "y_m", "N_kN_per_m", "V_kN_per_m", "M_kNm_per_m"]
        )
        for element in range(forces.shape[0]):
            for end in range(2):
                x, y = coords[element, end]
                n, v, m = forces[element, end]
                writer.writerow(
                    [element, end, f"{x:.6g}", f"{y:.6g}", f"{n:.8g}", f"{v:.8g}", f"{m:.8g}"]
                )


def _log_stage(lines: list[str], stage) -> None:
    hist = stage.history
    steps = hist.n_steps if hist is not None else 0
    iters = hist.n_iterations if hist is not None else 0
    finite = np.isfinite(stage.u[:, :2])
    peak = float(np.max(np.abs(stage.u[:, :2][finite]))) if finite.any() else float("nan")
    lines.append(f"{stage.name}: steps={steps} iterations={iters} max_|u|={peak:.6g} m")


def tunnel_case(out: Path) -> None:
    from slipsurface.fe2d import api
    from slipsurface.fe2d.gui.demo import tunnel_model

    model = tunnel_model()
    result = api.run(model)
    lines = [
        "case: four-state tunnel",
        "claim: GUI/API parity case, not an external tunnel benchmark",
    ]
    _log_stage(lines, result.initial)
    for stage in result.stages:
        _log_stage(lines, stage)
        if "shotcrete" in stage.beams:
            stem = stage.name.split()[0]
            _write_beams(out / f"tunnel-{stem}-nvm.csv", model.mesh, stage, "shotcrete")
    (out / "tunnel-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sheet_pile_case(out: Path) -> None:
    import sheet_pile_staged as staged

    from slipsurface.fe2d import api

    result = api.run(staged.model)
    lines = [
        "case: S4 cantilever sheet pile",
        "claim: internal model only. Not an RS2/PLAXIS comparison.",
    ]
    _log_stage(lines, result.initial)
    for stage in result.stages:
        _log_stage(lines, stage)
    moment = np.nanmax(np.abs(result.last.beams["wall"][:, :, 2]))
    lines.append(f"M_max={moment:.6g} kNm/m")
    (out / "sheet-pile-log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_beams(out / "sheet-pile-nvm.csv", staged.mesh, result.last, "wall")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("phase5-acceptance"))
    parser.add_argument("--sheet-pile", action="store_true", help="also run the plastic S4 wall")
    parser.add_argument("--tunnel", action="store_true", help="run the four-state tunnel (default)")
    args = parser.parse_args()
    if not args.tunnel and not args.sheet_pile:
        args.tunnel = True
    args.out.mkdir(parents=True, exist_ok=True)
    note = (
        "Phase 5 is not closed. These files are numbers only. "
        "Windows screenshots of the tunnel and the sheet pile still have to be accepted.\n"
    )
    (args.out / "NOT-ACCEPTED.txt").write_text(note, encoding="utf-8")
    if args.tunnel:
        tunnel_case(args.out)
    if args.sheet_pile:
        sheet_pile_case(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
