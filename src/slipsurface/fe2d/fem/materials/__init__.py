"""Constitutive models and the factory turning a :class:`MaterialSpec` into a model."""

from __future__ import annotations

from ...model.materials import MaterialSpec
from .base import ConstitutiveModel
from .elastic import LinearElastic, isotropic_D


def build(spec: MaterialSpec) -> ConstitutiveModel:
    p = spec.params
    if spec.model == "elastic":
        return LinearElastic(p["E"], p["nu"], p.get("phi"))
    raise NotImplementedError(
        f"material model '{spec.model}' is planned for a later phase (see roadmap)"
    )


__all__ = ["ConstitutiveModel", "LinearElastic", "build", "isotropic_D"]
