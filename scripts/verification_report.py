"""Turn pytest JUnit evidence into a readable report without reclassifying skips."""

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

source, destination = map(Path, sys.argv[1:3])
root = ET.parse(source).getroot()
rows = []
counts = Counter()
for case in root.iter("testcase"):
    status, reason = "PASS", ""
    for key, label in [("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP/XFAIL")]:
        event = case.find(key)
        if event is not None:
            status, reason = label, event.get("message", "")
            break
    counts[status] += 1
    if ".verification." in case.get("classname", ""):
        name = case.get("classname", "") + "::" + case.get("name", "")
        rows.append(f"| {name} | {status} | {reason.replace('|', '/').replace(chr(10), ' ')} |")
text = [
    "# Verification evidence",
    "",
    f"Source: {source.name}",
    "",
    "Counts include unit and verification cases present in this JUnit file.",
    "Deselected tests are not counted; skipped/xfail cases are never reported as passed.",
    "",
    "| Result | Count |",
    "|---|---|",
]
text += [f"| {label} | {counts[label]} |" for label in ["PASS", "FAIL", "ERROR", "SKIP/XFAIL"]]
text += [
    "",
    "## Analytical and verification cases",
    "",
    "| Case | Result | Reason |",
    "|---|---|---|",
    *rows,
    "",
    "S4 external RS2/PLAXIS comparison remains deferred by user decision.",
    "Legacy uncut P4 is an expected local-return failure, not a physical collapse bound.",
    "",
]
destination.write_text("\n".join(text), encoding="utf-8")
