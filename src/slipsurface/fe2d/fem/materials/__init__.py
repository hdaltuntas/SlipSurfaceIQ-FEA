"""Constitutive models and the factory turning a :class:`MaterialSpec` into a model."""

from __future__ import annotations

from ...model.materials import DP_MATCH, MaterialSpec
from .base import ConstitutiveModel
from .drucker_prager import DruckerPrager, VonMises
from .elastic import LinearElastic, isotropic_D
from .mohr_coulomb import MohrCoulomb


def build(spec: MaterialSpec) -> ConstitutiveModel:
    p = spec.params
    if spec.model == "elastic":
        return LinearElastic(p["E"], p["nu"], p.get("phi"))
    if spec.model == "mohr_coulomb":
        return MohrCoulomb(p["E"], p["nu"], p["c"], p["phi"], p.get("psi", 0.0), p.get("sig_t"))
    if spec.model == "drucker_prager":
        match = DP_MATCH[int(p.get("match", 0))]
        return DruckerPrager.from_mc(p["E"], p["nu"], p["c"], p["phi"], p.get("psi", 0.0), match)
    if spec.model == "von_mises":
        return VonMises(p["E"], p["nu"], p["sy"], p.get("H", 0.0))
    raise NotImplementedError(
        f"material model '{spec.model}' is planned for a later phase (see roadmap)"
    )


__all__ = [
    "ConstitutiveModel",
    "DruckerPrager",
    "LinearElastic",
    "MohrCoulomb",
    "VonMises",
    "build",
    "isotropic_D",
]
