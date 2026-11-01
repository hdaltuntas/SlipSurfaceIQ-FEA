# Phase 5 — release withdrawn, package version 0.9.0

**22 October 2026: the user found the interface not usable; v1.0.0 is not accepted as ready.**
The GitHub release list is empty; the v1.0.0 publication has been removed. The package is
deliberately **0.9.0**. Automatic package publication and the PyPI upload step were stopped.
The results below are historical technical test evidence; they do not mean user acceptance
or that Phase 5 is closed.

Priority: Windows theme/contrast problems, invisible tool labels, panel layout, and a
clear modelling workflow. A new publication will be considered separately after user
acceptance. [Open work](next-steps.md).

Native PySide6 desktop: CAD/DXF → T6 mesh; material/region, liner/bolt/interface,
mechanical boundary, and stage water/load/displacement editors; a stage timeline;
background solve/cancel; contours, the deformed mesh, plastic Gauss points, and in-plane
principal arrows; query lines and oriented liner N–V–M plots; project/CSV/VTU/HTML save.

![Four-stage tunnel](images/phase5-tunnel.png)

![Liner moment plot](images/phase5-liner.png)

## Automated GUI/API equality test — not user acceptance

`test_phase5_acceptance.py` builds a 16-sided circular tunnel approximation, the
surrounding rock region, and the crown bolt line from an empty CAD form. Initial stress
→ 40% relaxation → shotcrete to a total of 70% → completion of the bolt and the
remaining excavation. Across every stage, u, stress, liner/bolt forces, the plastic
flag, water, and the activation sequences of the GUI worker and of the independent
Domain/API model match exactly. Queries inside the excavation void stay NaN; the saved
project opens again.

This is a GUI/API equality acceptance; it does not replace an independent tunnel
verification. S1–S3 and the other existing analytical verifications are separate CI tests.

Local full regression: **472 passed, 1 strict xfail, 2 benchmarks excluded** (108.27 s).
The source smoke check succeeded for four states, save, DXF, export, and Numba.
The [verification dump generated from JUnit](phase5-verification.md) does not count the xfail as a pass.
Linux/Windows, Python 3.10–3.13, and two native GUI jobs: **10/10 passed**
([CI evidence](https://github.com/hdaltuntas/SlipSurfaceIQ-FEA/actions/runs/39674914899)).

## Numerical and usage limits

- There is no RS2/PLAXIS comparison for S4. Internal Winkler agreement does not close that gap.
- The legacy P4 without a tension cut-off is kept as a strict xfail. A local constitutive
  return error is not counted as proof of physical collapse or as an SRF upper bound.
  Explicit Rankine-apex flow is a separate option.
- Linear 2D DXF is supported; DWG and curve/block DXF are not included in this version.
- CAD remeshing transfers existing FE definitions by name; those with no remaining target
  are listed in the solution log ([detail](integrated-modeler.md)).
- Result contours are element averages. Query-line stresses are computed by Gauss-point
  extrapolation inside the element; a region filter selects the side at a material boundary.
- Principal arrows show the two in-plane stresses; the 3D principal values ordered with
  szz are separate contour fields. If the number of plastic points/arrows is thinned on a
  large model, that is shown on screen. The query line uses the undeformed coordinates.
- Liner local x is along the path; local y is 90° counterclockwise. N is positive in tension.
  N/V/M is the negative local nodal action at the start and the positive local action at
  the end. On an element whose path reverses, the end order is reversed and the sign of M
  changes. Shared ends are not averaged.
- Deleting an interface merges coincident paired nodes; a deletion that would completely
  close another interface is rejected. Unused node ids are kept.
- Liner plasticity, dynamic analysis, and full consolidation are outside the v1 scope.

## Package and publication

The portable (PyInstaller onedir) package was removed: `packaging/` and
`.github/workflows/portable.yml` were deleted. The application runs only with
`python main.py`. A wheel and an sdist are still built and checked with
`scripts/check_distributions.py`.

The first independent Windows package test **passed**:
[`39674915048`](https://github.com/hdaltuntas/SlipSurfaceIQ-FEA/actions/runs/39674915048),
`5c4dcb8`; `frozen=true`, `numba_enabled=true`, 2141 nodes, four states,
maximum displacement 0.02792259577890792 m. The NumPy inside the package was used.
A pre-release review removed the build environment from the sdist; the source package
was limited to an allow-list. Every build checks file contents and the 20 MB size limit.

The PyPI attempt failed with `invalid-publisher`; there is no successful PyPI publication.
`publish.yml` is now only a manually invoked package check: the PyPI upload job, the
OIDC permission, and the release trigger were removed, and `portable.yml` was removed too.
No GitHub release is created and no files are uploaded.
