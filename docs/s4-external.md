# S4 external comparison — independent evidence required

S4 is not externally verified until an equivalent RS2 or PLAXIS/PLAXIS2D model is
solved and its final excavation-stage wall results are committed. Internal SlipSurface,
Winkler, Rankine or copied values are not external evidence.

The locked physical problem is defined by `docs/data/s4/case.json` and
`docs/s4-comparison.md`. The current refined SlipSurface reference used for comparison
is the h=0.125 m T6+Q8 run.

## Required files

Copy the templates before entering results:

```text
docs/data/s4/external-template.csv
docs/data/s4/external-meta-template.json
```

The completed evidence files must be named:

```text
docs/data/s4/external.csv
docs/data/s4/external-meta.json
```

### external.csv

Required columns:

```text
depth_m,M_kNm_per_m,u_top_mm,source
```

- `depth_m`: positive downward from the wall head, 0 to 10.5 m.
- `M_kNm_per_m`: signed bending moment converted to the common upward-axis
  convention used by the `M_up_kNm_per_m` field in the S4 record.
- `u_top_mm`: horizontal wall-head displacement, positive to the right. Supply it
  exactly once on the depth=0 row.
- `source`: `RS2`, `PLAXIS` or `PLAXIS2D`, consistent with the metadata.

The moment profile must contain at least eight unique depths, cover the wall head and
toe, and have no gap greater than 1.0 m. This prevents a sparse export from missing the
independent solution's peak moment.

### external-meta.json

The metadata records the independent program version, convergence and explicit input
equivalence. `case_sha256` must match the locked physical-input digest already stored
for the h=0.125 m run. Every `input_match` flag must be checked true only after
verifying the external model:

- geometry and excavation;
- soil model and parameters;
- wall stiffness;
- both wall-soil interfaces;
- K0 initial stress;
- boundary restraints;
- installation/excavation stages;
- shared/tied translation at the wall tip;
- zero-tension Rankine cut-off / equivalent tensile treatment.

A different tip condition, interface penalty, wall stiffness, flow rule or excavation
history is a different benchmark and cannot close S4.

## Quantitative comparison

Run:

```bash
python scripts/s4_external_compare.py \
  --json s4-external-report.json \
  --markdown s4-external-report.md
```

The command is informational by default. For a release gate:

```bash
python scripts/s4_external_compare.py --require-pass
```

The existing S4 acceptance criterion is unchanged:

```text
abs(M_SlipSurface,max - M_external,max) / abs(M_external,max) <= 0.10
```

The signed moment field and wall-head horizontal displacement are also reported.
Their signs must use the documented common convention. Field maximum difference,
normalized RMSE and head-displacement difference are diagnostics; this PR does not
invent an additional magnitude tolerance for them.

If `external.csv` is absent, `tests/verification/test_s4_external.py` skips and
explicitly states that the skip is not a verification pass. Once external evidence is
committed, the test requires the metadata and quantitative comparison to pass.

## Exact model reminder

The external model must reproduce the fixed problem in `s4-comparison.md`:

- small-strain plane strain, 1 m out-of-plane width;
- domain -20 <= x <= 20 m and -20 <= y <= 0 m;
- 10.5 m weightless sheet pile at x=0;
- 5 m excavation on the right;
- dry drained Mohr-Coulomb sand: E=30000 kPa, nu=0.30, c=0, phi=30 deg,
  psi=0, gamma=18 kN/m3;
- associated zero-tension Rankine treatment at the apex;
- wall EA=2e7 kN/m, EI=2e5 kN m2/m, GA=8e6 kN/m;
- two-sided interfaces kn=403846.153846 kPa/m and
  ks=115384.615385 kPa/m, c=0, phi=30 deg, psi=0, tensile strength=0;
- bottom fixed x/y; side boundaries fixed horizontally;
- K0=0.5 initial field, stress-free wall installation, then full excavation release;
- wall-tip translation shared with the soil, rotation free.

Do not replace these with software defaults merely because they are common for a
sheet-pile tutorial.
