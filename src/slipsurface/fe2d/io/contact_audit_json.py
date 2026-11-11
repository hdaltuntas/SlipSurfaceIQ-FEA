"""Atomic strict-JSON export of a completed read-only contact audit document."""

import json
from pathlib import Path

from ..post.contact_audit_report import validate_document
from .results_h5 import _atomic_write


def export_contact_audit_json(document, path):
    """Export exactly the displayed complete report; never re-solve or re-audit."""
    data = validate_document(document)
    payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    return _atomic_write(path, lambda tmp: Path(tmp).write_text(payload, encoding="utf-8"))
