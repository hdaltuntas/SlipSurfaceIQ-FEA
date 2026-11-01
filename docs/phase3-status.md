# Phase 3 — previous work record

**Current status:** the Phase 4 fixes were merged and Phase 5.1 has started.
The numbers below are the historical record of PR #1. [Current plan](next-steps.md).

Reference: *SlipSurface 2D — Technical Architecture and Roadmap*, Phase 3 and Appendix A.

**21 October 2026 user decision:** the S4 work was closed, and the independent
RS2/PLAXIS comparison was deferred. The S4 external verification and the Gate 3
verification criterion are not considered passed. Phase 4 was not started; at this
point only the existing fixes, the results, and [what remains to be done](next-steps.md)
were recorded.

| Item / verification | Status | Evidence / remaining work |
|---|---|---|
| Active set, excavation, load split, activation, and u_ref | Present, S3 verified | Single/multi-stage, three relaxation ratios, backfill |
| S1 lined elastic tunnel | No-slip scope verified | Four mesh/boundary trials, signed N/M fields within 5% |
| S2 pretensioned anchor | Verified | Independent series-spring equilibrium at three anchor spacings |
| Goodman interface | Verified in the defined scope | Yield/tension/combined return, tangent, two-sided node separation, water force, and state preservation |
| Stage-wise piezometric water, material change | Present | Water and static unit tests |
| HDF5 and .ssproj | Present, record tests exist | Per-stage read, mixed-element/plastic output round trip, atomic save |
| S4 cantilever sheet pile | **Work record closed; external verification deferred** | Independent Timoshenko/Winkler and Rankine checks passed; mesh/integration comparisons were renewed with the local MC return guard; no full verification |
| S4 external-comparison preparation | Model and wall-field outputs are ready | On 0.5/0.25/0.125 m mixed meshes, M=163.730/168.058/168.912; step/stage sensitivity was measured; a shared tip was kept on both interfaces; independence of insertion order was verified; an external reference is awaited |
| P4 explicit Rankine-apex | **Defined model scope verified** | h=1.5 exact/1e-6 and h=1.0 exact tangent: 3% Bishop, bracket, mechanism, and stress admissibility; the model completion is selected explicitly |
| P4 legacy uncut model / general Gate 2 scope | **Open limit kept** | The legacy test is a strict xfail; a local rejection cannot be counted as a collapse bound; the old unguarded FE factors have been withdrawn |
| Replay of the local-rejection inputs | The cause was separated for two records | Sheet pile/P4: ψ=0, no Rankine, trial mean above the apex; the total increment is still not completed with 128 local pieces; no claim of global non-existence |
| Explicit Rankine cut-off / common apex | Local scope verified | Analytical stress/tangent and T3/T6/Q4/Q8 load–unload; four high sheet-pile runs completed with explicit σt=0; independent S4 is still open |
| Gate 3 verification criterion | **Not complete** | S4 external evidence was deferred; Phase 4 was not started, by user instruction |
| T3+Q4 / T6+Q8 mixed mesh | Experimental | Patch, cantilever, plastic compression, stage, water, interface, and record checks passed; nonlinear sheet-pile integration/mesh sensitivity is open |

Method, reference links, numerical error tables, and limits:
[phase3-verification.md](phase3-verification.md).
Project/result API: [project-files.md](project-files.md).
Mixed-mesh API and the comparison on the same sheet-pile model: [mixed-mesh.md](mixed-mesh.md).
Local material error and the diagnostic API: [nonlinear-diagnostics.md](nonlinear-diagnostics.md).
Coincident tension/apex behaviour: [coincident-tension-cutoff.md](coincident-tension-cutoff.md).
S4 inputs and signed wall outputs: [s4-comparison.md](s4-comparison.md).
Comparison of geometry, conditioning, and Newton methods at the same load:
[convergence-audit.md](convergence-audit.md).

## Bugs that were fixed

- Treating the inner section as an outer boundary when the second interface was added,
  and splitting the embedded tip: in the boundary query only open interface pairs are
  treated as identical; real DOFs are not merged. Ten regression tests for the T3/T6/Q4/Q8
  inner tip and the asymmetric soil response failed on the old code and pass after the
  fix; the plastic S4 reverse-order repeat also gives the same moment/displacement to
  rounding level.
- A residual at machine precision causing a false non-convergence in an unloaded stage
  that holds pretension: a rounding threshold tied to the force scale.
- Plastic cell data in a mixed VTU not matching the length of the structural cells:
  an array that covers every exported cell, and data-length checks.
- Sequential clipping of dilatant slip and the tension cut-off on an interface: an
  active-set return and its full derivative that check admissibility and the sign of
  the plastic multipliers together.
- The unreliable SLSQP reference in the Python 3.10 CI: an independent linearly
  constrained QP whose success and constraints are checked. Production material
  tolerances were not changed.
- A reverse dependency of the mesh layer on the post-processing layer for boundary
  nodes: the shared topology function was moved to L2; the existing post-processing
  import was kept.

- Wrong reuse of active-element tangents in plastic stages while the block name stayed
  the same: a cache keyed by the full system.
- Reshaping an empty DOF array, and a missing tangent key, when a separate element
  block was removed entirely: empty-block support was fixed.
- Accepting an elastic trial flagged `255` when the MC return could not be found:
  now a local error, rollback, and step cutting; in SRF this error is not counted as collapse.
- Ignoring an explicit `sig_t=apex`: the associated Rankine potential is kept; nine
  potentials are checked at the common corner. The fixed corner tangent is exactly zero.
  The first predictor for unloading from a singular previous tangent may use the elastic
  matrix; the later Newton tangent is not replaced by default. The optional
  `apex_stiffness_ratio` is applied only to the iteration matrix.

## Where the work was left

The explicit Rankine-apex model, the P4 regressions, the two-sided interface tip fix,
and the six internal S4 comparison runs were completed. The legacy uncut P4 limit is
kept. A new external solution for S4 will not be requested in this session; the
comparison was left for later. No Phase 4 code was added. The order of the next work
and the acceptance criteria are in [next-steps.md](next-steps.md); that list is not an
implemented feature.

Record files are post-processing snapshots; they are not a nonlinear solver restart
format. The GUI and the hardware-dependent performance gate are outside the scope of
this work.

## Last verification

- **53 targeted tests passed** in the interface, stress-recovery, and global algorithmic
  tangent files (they overlap the full run). Six runs in soil — three meshes, step
  halving, release in two stages, and reverse interface order — reached λ=1; the local
  rejection count is 0 in all of them. An external reference is awaited.
- Linux / Python 3.12: **318 passed** in the full run excluding benchmarks, **1 strict
  xfail for the legacy uncut P4**; this expected failure is not counted as a pass.
  The viewer module was **1 skipped** because PyVista is missing, and performance tests
  were **2 excluded**.
- In the previous NumPy 2.2.6 / SciPy 1.15.3 run, **50 passed, P4 1 strict xfail** in
  the material, common-apex, Newton-diagnostic, analytical load-path, Newton-convergence,
  and P4 files (overlaps the main total).
- Additional diagnostic/matrix/rollback checks **passed 23** in the same old
  NumPy/SciPy environment (overlaps the main total).
- The eight mixed continuum/beam/interface cases of the global algorithmic tangent,
  together with Newton convergence, **passed 12** in the same old environment
  (overlaps the main total).
- Explicit Rankine-apex, non-negative multipliers, the approximate iteration matrix,
  and load–unload checks **passed 39** in the old NumPy/SciPy environment
  (overlaps the main total).
- The real sheet-pile/P4 rejection inputs, the 128-piece local replay, the physical
  Gauss-point mapping, the history/SRF error data, and the old HDF5 defaults were checked.
- Current Ruff and `git diff --check` succeeded. The previous wheel build and the
  API/topology import check from a wheel installed in a separate folder also succeeded.
- At the end of the full run, BLAS `DTRSV`/`DGEMV` parameter diagnostics were also
  written; the process exit code is 0 and the test result is as above. The same
  messages were already present in the earlier apex runs; the cause will be separated
  later and was not tied to the new tip fix.
- Failures of the example in soil were not added to these test totals as successes;
  they are kept as an open problem above and in the verification report.
