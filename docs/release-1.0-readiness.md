# SlipSurfaceIQ-FEA 1.0 release readiness

This document defines the **finish line** for the first stable source release.
It is intentionally narrower than “match every capability of RS2/PLAXIS”.
New features are not release blockers unless explicitly promoted into this gate.

Run:

```bash
python scripts/release_readiness.py
```

The command is informational by default. For the final release check:

```bash
python scripts/release_readiness.py --require-ready \
  --json release-readiness.json --markdown release-readiness.md
```

## Required gates

1. **Manual Windows usability acceptance.** A real Windows end-to-end workflow must be
   accepted by the user. Automated/offscreen Qt tests do not satisfy this gate.
2. **Official external benchmark suite.** Four independent benchmark jobs are strict
   `--require-pass` gates:
   - B1 RS2 Introduction / Surface Excavation;
   - B2 PLAXIS Tutorial 01A / circular footing;
   - B3 PLAXIS phi-c reduction / Bishop;
   - B4 PLAXIS Drain / Dupuit groundwater flow.
   The final release commit must pass `external-benchmarks`,
   `plaxis-drain-benchmark` and the complete standard CI suite.
3. **Source-only distribution policy.** The first stable release remains a source
   release run with `python main.py`; installer/PyPI work is not required for v1.0
   unless the product decision changes.

The exact custom S4 sheet-pile comparison remains valuable **advanced external
validation**, but is no longer the sole v1 release blocker. It stays open until a
like-for-like RS2/PLAXIS result is available and must never be described as passed
using internal Winkler or tutorial cases.

## Windows acceptance procedure

Prepare the manual acceptance evidence on a real Windows machine:

    python scripts/windows_release_acceptance.py prepare --out windows-v1-acceptance

Follow the generated checklist, capture `tunnel-ui.png` and `sheet-pile-ui.png`,
and record acceptance only when all four usability checks are genuinely accepted:

    python scripts/windows_release_acceptance.py record --evidence windows-v1-acceptance --accept-workflow --accept-readability --accept-results --accept-save-reopen --note "Accepted for SlipSurfaceIQ-FEA 1.0 usability"

The recorder copies screenshots into `docs/data/release-acceptance/` and writes
`docs/release-acceptance.json`. The readiness gate verifies the Windows platform,
all four explicit checks and the recorded screenshot evidence.

## Release action after all gates pass

Keep the project at `0.9.0` while any blocker remains. Once all gates pass on the
chosen release commit:

1. run `python scripts/release_readiness.py --require-ready`;
2. require standard CI, `external-benchmarks`, and `plaxis-drain-benchmark` green;
3. update package version to `1.0.0` and update release notes/status text;
4. rerun all required workflows on that exact release commit;
5. tag that exact commit.

## Explicitly not required for v1.0

Dynamic analysis, liner plasticity, full consolidation, general physical
backfill/deposition/remeshing, exact custom S4 closure, RS2 anchored-sheet-pile B5,
and feature parity with commercial programs remain outside the first-release gate
unless separately promoted into scope. Release notes must continue to state supported
and unsupported analysis types accurately.
