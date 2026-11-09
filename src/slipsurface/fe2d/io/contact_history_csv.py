"""Atomic CSV export of a selected stored contact point history."""

import csv

from .results_h5 import _atomic_write


def export_contact_history_csv(result, path, tag, element, point):
    """Atomic, ordered history for one mesh point; gaps in metres, no missing zeros."""
    from ..post.contact_history import contact_point_history

    history = contact_point_history(result, tag, element, point)

    def value(number):
        return "" if number is None else format(number, ".17g")

    def write(tmp):
        with open(tmp, "w", newline="", encoding="utf-8") as stream:
            out = csv.writer(stream)
            out.writerow([
                "stage_index", "stage", "load_factor", "tag", "element", "point",
                "face1_node", "face2_node", "x_m", "y_m", "active", "availability",
                "gap_m", "normal_traction_kPa", "pressure_kPa", "status_code", "status",
            ])
            for sample in history:
                p = sample.contact
                out.writerow([
                    sample.stage_index, sample.stage_name, value(sample.load_factor), p.tag,
                    p.element, p.point, p.face1_node, p.face2_node, value(p.x_m), value(p.y_m),
                    int(p.active), p.availability, value(p.gap_m), value(p.normal_traction_kpa),
                    value(p.pressure_kpa), "" if p.status_code is None else p.status_code, p.status,
                ])

    return _atomic_write(path, write)
