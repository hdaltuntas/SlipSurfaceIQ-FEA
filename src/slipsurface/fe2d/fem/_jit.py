"""Optional Numba JIT. Without Numba the kernels run as plain (slow) Python."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

try:  # pragma: no cover - exercised implicitly
    import numba as _nb

    HAVE_NUMBA = True

    def njit(*args: Any, **kw: Any) -> Any:
        # Frozen PYZ functions have no source locator for the on-disk Numba cache.
        kw.setdefault("cache", not getattr(sys, "frozen", False))
        kw.setdefault("fastmath", False)
        return _nb.njit(*args, **kw)

    prange = _nb.prange
except Exception:  # pragma: no cover
    HAVE_NUMBA = False

    def njit(*args: Any, **kw: Any) -> Any:
        if args and callable(args[0]):
            return args[0]

        def deco(fn: Callable) -> Callable:
            return fn

        return deco

    prange = range
