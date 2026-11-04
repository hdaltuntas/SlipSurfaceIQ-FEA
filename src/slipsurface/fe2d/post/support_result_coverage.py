"""F7 fail-closed support-result coverage for staged excavation.

A finite support peak or a balanced interface resultant is not evidence that
the intended pile, anchor and both skin interfaces were actually active.
This checks solver activity masks, output coverage and finite result fields.
It is a data-integrity audit, not independent mechanical validation.
"""

from __future__ import annotations

import numpy as np


def stage_support_result_coverage(model, stage, expected_active=None):
    """Check each declared structural element against its reported active mask.

    Expected activation is a set of structure tags from the stage design.
    Inactive results must be all NaN, active results all finite. Every
    declared structural block must appear with correct element dimensions.
    """
    specs = (
        ("beam", model.liners, stage.beams, (2, 3)),
        ("bar", model.bolts, stage.bars, ()),
        ("interface", model.interfaces, stage.interfaces, None),
    )
    expected_active = set(expected_active) if expected_active is not None else None
    declared = set(model.liners) | set(model.bolts) | set(model.interfaces)
    if expected_active is not None and not expected_active <= declared:
        raise ValueError("Expected active support is not declared in model")
    details = []
    for kind, properties, outputs, trailing in specs:
        for tag in sorted(properties):
            block = model.mesh.block(tag)
            active = stage.active.get(tag)
            values = outputs.get(tag)
            if active is None or values is None:
                details.append({
                    "kind": kind, "tag": tag, "status": "missing",
                    "reason": "Missing activity mask or structural output",
                })
                continue
            mask = np.asarray(active, dtype=bool)
            arr = np.asarray(values, dtype=float)
            if kind == "interface":
                trailing = (2 if block.etype.name == "IFACE4" else 3, 2)
            shape = (block.ne, *trailing)
            if mask.shape != (block.ne,) or arr.shape != shape:
                details.append({
                    "kind": kind, "tag": tag, "status": "failed",
                    "reason": f"Expected mask {(block.ne,)} and output {shape}",
                })
                continue
            enabled = int(np.count_nonzero(mask))
            nonfinite_active = enabled and not np.isfinite(arr[mask]).all()
            nonnan_inactive = np.any(~np.isnan(arr[~mask]))
            expected = expected_active is None or tag in expected_active
            # Excavation removes continuum on one side of a liner. The
            # corresponding skin interface is legitimately partly inactive,
            # even when its tag remains in Stage.active_structures.
            # Beam/bar installation still requires full element activation.
            wrong_activation = (
                expected_active is not None
                and (
                    (enabled == 0 if kind == "interface" else enabled != block.ne)
                    if expected else enabled != 0
                )
            )
            if nonfinite_active or nonnan_inactive or wrong_activation:
                status = "failed"
                reason = (
                    "Structural activation or finite/NaN output inconsistent "
                    "with expected stage"
                )
            else:
                status, reason = "passed", None
            details.append({
                "kind": kind, "tag": tag, "status": status,
                "active_elements": enabled, "total_elements": block.ne,
                "expected_active": expected,
                **({"reason": reason} if reason else {}),
            })
    failed = [item for item in details if item["status"] != "passed"]
    return {
        "status": "passed" if not failed and details else "failed",
        "declared_structures": len(declared),
        "checked_structures": len(details),
        "failed_structures": len(failed),
        "details": details,
        "warning": (
            "Structural output coverage is a necessary integrity check, "
            "not an independent soil-pile-anchor equilibrium benchmark."
        ),
    }
