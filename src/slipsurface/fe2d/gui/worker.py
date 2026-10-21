"""Native Qt worker. All widgets stay in the main thread."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from .. import api
from ..io.project_json import model_from_dict, model_to_dict


class SolveWorker(QThread):
    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        # Freeze the input before the worker starts; GUI edits cannot affect a solve.
        self.model = model_from_dict(model_to_dict(model))

    def run(self):
        try:
            result = api.run(
                self.model, progress=self.progress.emit, cancel=self.isInterruptionRequested
            )
        except api.SolveCancelled:
            self.cancelled.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.succeeded.emit(result)
