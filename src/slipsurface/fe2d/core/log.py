"""Package logger (L0). The library never configures handlers itself."""

from __future__ import annotations

import logging

logger = logging.getLogger("slipsurface.fe2d")
logger.addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    return logger.getChild(name)
