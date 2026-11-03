"""Independent one-dimensional Terzaghi primary consolidation settlement calculator.

This is an oedometer-based engineering estimate, NOT a coupled u-p FEM solution.
Units: metres, kPa, days, and square metres per day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

T90 = 0.848  # average degree of consolidation 90%, Terzaghi 1D


@dataclass(frozen=True)
class ConsolidationInput:
    thickness: float
    sigma_initial: float
    delta_sigma: float
    compression_index: float
    void_ratio: float
    cv: float
    drainage: str = "double"
    method: str = "cc"
    mv: float | None = None  # m²/kN = 1/kPa

    def __post_init__(self) -> None:
        values = (self.thickness, self.sigma_initial, self.delta_sigma,
                  self.compression_index, self.void_ratio, self.cv)
        if not all(math.isfinite(x) for x in values):
            raise ValueError("All consolidation inputs must be finite.")
        if (self.thickness <= 0 or self.sigma_initial <= 0
                or self.sigma_initial + self.delta_sigma <= 0
                or self.compression_index < 0 or self.void_ratio < 0 or self.cv <= 0):
            raise ValueError("Invalid layer, stress, compression or consolidation coefficient.")
        if self.drainage not in ("single", "double"):
            raise ValueError("Drainage must be 'single' or 'double'.")
        if self.method not in ("cc", "mv"):
            raise ValueError("Method must be cc or mv.")
        if self.method == "mv" and self.mv is None:
            raise ValueError("mv is required for the mv method.")
        if self.mv is not None and (not math.isfinite(self.mv) or self.mv < 0):
            raise ValueError("mv must be finite and nonnegative (1/kPa).")

    @property
    def drainage_path(self) -> float:
        return self.thickness / (2 if self.drainage == "double" else 1)

    def final_settlement(self) -> float:
        """Normally consolidated layer: signed primary settlement, metres.

        Positive delta_sigma gives settlement; negative gives rebound according
        to the same Cc approximation. No separate recompression index is used.
        """
        if self.method == "mv":
            assert self.mv is not None
            return self.mv * self.delta_sigma * self.thickness
        return (self.thickness * self.compression_index / (1 + self.void_ratio)
                * math.log10((self.sigma_initial + self.delta_sigma)
                             / self.sigma_initial))

    def time_factor(self, days: float) -> float:
        if not math.isfinite(days) or days < 0:
            raise ValueError("Elapsed time must be finite and nonnegative.")
        return self.cv * days / self.drainage_path**2

    def degree(self, days: float) -> float:
        """Average degree of consolidation from the classical Fourier series."""
        tv = self.time_factor(days)
        if tv == 0:
            return 0.0
        # Short-time approximation avoids catastrophic cancellation at Tv ~ 0.
        if tv < 0.01:
            return min(1.0, 2 * math.sqrt(tv / math.pi))
        residual = 0.0
        for n in range(80):
            odd = 2 * n + 1
            term = (8 / math.pi**2) * math.exp(
                -(odd**2) * math.pi**2 * tv / 4
            ) / odd**2
            residual += term
            if term < 1e-14:
                break
        return max(0.0, min(1.0, 1 - residual))

    def settlement(self, days: float) -> float:
        return self.final_settlement() * self.degree(days)

    def time_to_90(self) -> float:
        return T90 * self.drainage_path**2 / self.cv
