"""Element kernels. ``KERNELS`` maps an :class:`ElemType` to its kernel instance."""

from ...core.enums import ElemType
from .base import ElementKernel, GeomCache, IsoElement
from .tri3 import Tri3
from .tri6 import Tri6

KERNELS: dict[ElemType, IsoElement] = {
    ElemType.T3: Tri3(),
    ElemType.T6: Tri6(),
}


def kernel(etype: ElemType) -> IsoElement:
    try:
        return KERNELS[etype]
    except KeyError:
        raise NotImplementedError(f"element type {etype.name} is not implemented yet") from None


__all__ = ["KERNELS", "ElementKernel", "GeomCache", "IsoElement", "Tri3", "Tri6", "kernel"]
