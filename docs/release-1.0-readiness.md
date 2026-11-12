# SlipSurfaceIQ-FEA 1.0 release readiness

This document defines the **finish line** for the first stable source release.
It is intentionally narrower than “match every capability of RS2/PLAXIS”.
New features are not release blockers unless they are explicitly added to this gate.

Run:

```bash
python scripts/release_readiness.py
```

The command is informational by default and exits successfully even while blockers remain.
For a final release check:

```bash
python scripts/release_readiness.py --require-ready \
  --json release-readiness.json --markdown release-readiness.md
```

## Required gates

1. **Manual Windows usability acceptance.** A real Windows end-to-end model workflow must
   be accepted by the user. Record it in `docs/release-acceptance.json` with
   `phase5_user_acceptance: true` and a Windows platform description.
   Automated/offscreen Qt tests do not satisfy this gate.
2. **Independent S4 structural comparison.** `docs/data/s4/external.csv` must contain
   actual RS2 or PLAXIS/PLAXIS2D comparison rows with `depth_m`, `M_kNm_per_m`,
   `u_top_mm`, and `source`. Internal Winkler or copied SlipSurface results are not
   accepted as external evidence.
3. **Source-only distribution policy.** The first stable release remains a source release
   run with `python main.py`; installer/PyPI work is not required for v1.0 unless the
   product decision changes.

## Release action after all gates pass

Keep the project at `0.9.0` while any blocker remains. Once all gates pass on the chosen
release commit, update the package version to `1.0.0`, update the release notes/status
text, run the complete CI matrix, and tag that exact commit.

## Explicitly not required for v1.0

Dynamic analysis, liner plasticity, full consolidation, general physical
backfill/deposition/remeshing, and feature parity with commercial programs remain outside
the first-release gate unless separately promoted into scope. The release notes must
continue to state supported and unsupported analysis types accurately.
