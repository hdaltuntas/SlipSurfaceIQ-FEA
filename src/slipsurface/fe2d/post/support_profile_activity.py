"""Validate installed structural support profiles without GUI or CAD dependencies."""

from __future__ import annotations

import numpy as np


def active_support_profile_available(stage, tag, kind):
    """Skip wholly inactive supports, but never silently skip invalid active data.

    Only an explicitly all-False activity mask permits skipping a profile.
    Partially active beam/bar profiles are not supported by this sampler.
    """
    if kind not in ("bar", "beam"):
        raise ValueError(f"Unsupported structural support kind: {kind}")
    mask = stage.active.get(tag)
    if mask is None:
        raise ValueError(f"{tag}: missing support activation mask")
    active = np.asarray(mask, dtype=bool)
    if active.ndim != 1 or active.size == 0:
        raise ValueError(f"{tag}: invalid support activation mask")
    if not active.any():
        return False
    if not active.all():
        raise ValueError(f"{tag}: partially active support profile unsupported")
    sources = stage.bars if kind == "bar" else stage.beams
    if tag not in sources:
        raise ValueError(f"{tag}: active support forces missing")
    forces = np.asarray(sources[tag], dtype=float)
    if forces.shape[0] != active.size or not np.isfinite(forces).all():
        raise ValueError(f"{tag}: nonfinite active support forces or shape")
    return True
