"""Atomic per-interface contact-action export from accepted stage snapshots."""

import csv
import math
from numbers import Real

from ..post.contact_resultants import contact_resultants, moment_origin
from ..post.contact_results import normal_contact_tags
from .results_h5 import _atomic_write


def export_contact_resultants_csv(result, path, *, stage_index=None, tag=None, origin=(0.0, 0.0)):
    """None exports initial + all stages; an integer chooses one exact snapshot.

    Stage index, not name or lambda, disambiguates duplicate stage names. Origin
    in original global coordinates; actions and internal contributions have
    explicitly opposite signs. Validate every stage before replacing a file.
    """
    from numbers import Integral

    if not normal_contact_tags(result.model):
        raise ValueError("No unilateral normal-contact interfaces in this result")
    origin = moment_origin(origin)
    stages = [result.initial, *result.stages]
    if stage_index is not None and (
        isinstance(stage_index, bool) or not isinstance(stage_index, Integral)
        or not 0 <= stage_index < len(stages)
    ):
        raise ValueError("Invalid contact snapshot index")
    indices = range(len(stages)) if stage_index is None else [stage_index]
    batches = []
    for index in indices:
        st = stages[index]
        if (not isinstance(st.name, str) or isinstance(st.lam, bool)
                or not isinstance(st.lam, Real) or not math.isfinite(st.lam)
                or not 0 <= st.lam <= 1):
            raise ValueError(f"Stage {index}: invalid accepted snapshot metadata")
        batches.append((index, st, contact_resultants(result, st, tag, origin=origin)))

    def value(number):
        return "" if number is None else format(number, ".17g")

    def write(tmp):
        with open(tmp, "w", newline="", encoding="utf-8") as stream:
            out = csv.writer(stream)
            fields = [f"face{face}_{kind}_{component}_{unit}"
                      for kind in ("action", "internal") for face in (1, 2)
                      for component, unit in (("Fx", "kN_per_m"), ("Fy", "kN_per_m"),
                                               ("Mz", "kNm_per_m"))]
            out.writerow([
                "stage_index", "stage", "load_factor", "tag", "availability",
                "origin_x_m", "origin_y_m", "elements", "active_elements",
                "available_points", "unavailable_points", "inactive_points",
                "total_length_m", "active_length_m", "pressure_integral_kN_per_m", *fields,
            ])
            for index, st, summaries in batches:
                for row in summaries:
                    forces = [value(None if face is None else sign*getattr(face, component))
                              for sign in (1, -1) for face in (row.face1, row.face2)
                              for component in ("fx", "fy", "moment")]
                    out.writerow([
                        index, st.name, value(st.lam), row.tag, row.availability,
                        *map(value, row.origin_m), row.element_count, row.active_elements,
                        row.available_points, row.unavailable_points, row.inactive_points,
                        value(row.total_length_m), value(row.active_length_m),
                        value(row.pressure_integral), *forces,
                    ])
    return _atomic_write(path, write)
