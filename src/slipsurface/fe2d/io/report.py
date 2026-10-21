"""Portable CSV and HTML reports from accepted stage snapshots."""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

import numpy as np

from ..post.result_fields import recovered_stress, stage_result
from .results_h5 import _atomic_write


def export_csv(result, path, stage=None):
    """Nodal displacement/recovered stress; inactive values remain empty, never zero."""
    st = stage_result(result, stage)
    stress = recovered_stress(result, st)
    rows = np.column_stack(
        [np.arange(result.model.mesh.nn), result.model.mesh.coords, st.u, stress]
    )

    def write(tmp):
        with open(tmp, "w", newline="", encoding="utf-8") as stream:
            out = csv.writer(stream)
            out.writerow(
                ["node", "x_m", "y_m", "ux_m", "uy_m", "sxx_kPa", "syy_kPa", "szz_kPa", "txy_kPa"]
            )
            for row in rows:
                out.writerow(
                    [int(row[0]), *[format(v, ".17g") if np.isfinite(v) else "" for v in row[1:]]]
                )

    return _atomic_write(path, write)


def export_beam_csv(result, path, stage=None):
    """Raw local N/V/M at each active beam end. Shared ends are not averaged."""
    st = stage_result(result, stage)

    def write(tmp):
        with open(tmp, "w", newline="", encoding="utf-8") as stream:
            out = csv.writer(stream)
            out.writerow(
                [
                    "block",
                    "element",
                    "end",
                    "node",
                    "x_m",
                    "y_m",
                    "N_kN_per_m",
                    "V_kN_per_m",
                    "M_kNm_per_m",
                ]
            )
            for tag, forces in st.beams.items():
                block = result.model.mesh.block(tag)
                for e in np.flatnonzero(st.active.get(tag, np.ones(block.ne, bool))):
                    for end, node in enumerate(block.conn[e]):
                        out.writerow(
                            [
                                tag,
                                int(e),
                                end,
                                int(node),
                                *result.model.mesh.coords[node],
                                *forces[e, end],
                            ]
                        )

    return _atomic_write(path, write)


def export_html(result, path):
    """Self-contained engineering summary; no external assets or validation claims."""
    records = []
    for st in [result.initial, *result.stages]:
        displacement = np.linalg.norm(st.u, axis=1)
        finite = displacement[np.isfinite(displacement)]
        maximum = f"{finite.max():.8g}" if finite.size else "—"
        attempts = len(st.history.steps) if st.history else 0
        rejected = sum(not s.converged for s in st.history.steps) if st.history else 0
        records.append(
            f"<tr><td>{escape(st.name)}</td><td>{st.lam:.6g}</td>"
            f"<td>{maximum}</td><td>{attempts}</td><td>{rejected}</td></tr>"
        )
    html = """<!doctype html><html lang="tr"><meta charset="utf-8">
<title>SlipSurfaceIQ · Analiz raporu</title><style>
body{font:16px system-ui;max-width:1000px;margin:48px auto;color:#213547;padding:24px}
h1{color:#155e75}table{border-collapse:collapse;width:100%;margin:24px 0}
th,td{text-align:left;padding:12px;border-bottom:1px solid #ddd}th{background:#edf6f8}
</style><h1>SlipSurfaceIQ-FEA</h1><p>Aşamalı analiz sonuç özeti</p>"""
    html += (
        f"<p>Analiz: {escape(result.model.analysis.value)} · "
        f"Düğüm: {result.model.mesh.nn} · "
        f"Eleman: {sum(b.ne for b in result.model.mesh.blocks)}</p>"
    )
    html += "<p>Birimler: kN, m, kPa. Gerilme işareti: çekme pozitif. "
    html += "Eksenel simetride kuvvetler radyan başınadır.</p>"
    html += "<table><tr><th>Aşama</th><th>λ</th><th>En büyük |u| (m)</th>"
    html += "<th>Adım denemesi</th><th>Reddedilen deneme</th></tr>"
    html += "".join(records) + "</table>"
    html += (
        "<p>λ, aşamanın yük/serbest bırakma çarpanıdır; güvenlik katsayısı değildir. "
        "Bu rapor kayıtlı çözümleri özetler; bağımsız mühendislik doğrulaması içermez. "
        "S4 dış karşılaştırması ertelenmiştir.</p></html>"
    )
    return _atomic_write(path, lambda tmp: Path(tmp).write_text(html, encoding="utf-8"))
