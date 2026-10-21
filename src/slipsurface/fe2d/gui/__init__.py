"""L6 — optional graphical front-ends.

Native desktop: ``python -m slipsurface.fe2d.gui`` (install ``[gui]``).
"""

from .results_view import show_result, to_pyvista

__all__ = ["show_result", "to_pyvista"]
