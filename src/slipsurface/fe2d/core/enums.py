"""Enumerations shared by every layer (L0)."""

from __future__ import annotations

from enum import Enum, IntEnum


class ElemType(IntEnum):
    """Element type codes. Values are stable and are written to project/result files."""

    T3 = 1
    T6 = 2
    Q4 = 3
    Q8 = 4
    BEAM2 = 10
    BAR2 = 20
    IFACE4 = 30
    IFACE6 = 31

    @property
    def nen(self) -> int:
        return _NEN[self]

    @property
    def nodes_per_edge(self) -> int:
        return 3 if self in (ElemType.T6, ElemType.Q8) else 2


_NEN = {
    ElemType.T3: 3,
    ElemType.T6: 6,
    ElemType.Q4: 4,
    ElemType.Q8: 8,
    ElemType.BEAM2: 2,
    ElemType.BAR2: 2,
    ElemType.IFACE4: 4,
    ElemType.IFACE6: 6,
}


class Analysis(Enum):
    PLANE_STRAIN = "plane_strain"
    AXISYMMETRIC = "axisymmetric"


class Drainage(Enum):
    DRAINED = "drained"
    UNDRAINED_A = "A"
    UNDRAINED_B = "B"
    UNDRAINED_C = "C"


class PlasticFlag(IntEnum):
    """Gauss point state written to results (uint8)."""

    ELASTIC = 0
    SHEAR = 1
    TENSION = 2
    APEX = 3
