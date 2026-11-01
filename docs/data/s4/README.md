# S4 sample outputs

`results.json` contains SlipSurfaceIQ-FEA runs in which the embedded tip is closed
on both interfaces. The starting commit and the SHA-256 digests of the changed source
files are in the result file. Earlier results with an asymmetric tip that depended on
insertion order are preserved at commit
[5f0c4eb](https://github.com/hdaltuntas/SlipSurfaceIQ-FEA/tree/5f0c4eba64b1ad72ad01f9d8db52eace9f31446f/docs/data/s4);
they are not a substitute for the current results.

- `h050`, `h025`, `h0125`: 0.5/0.25/0.125 m local T6+Q8 mesh, high integration.
- `h050-half-steps`: initial/maximum step 0.05/0.25 on the 0.5 m mesh.
- `h050-split-release`: 50% of the same excavation load, then the remainder, in separate solution stages.
- `h050-right-first`: the interfaces of the same physical model are added in reverse order.
- For each run, `wall-end-forces.csv` keeps both end values;
  `wall-displacements.csv` contains the individual wall nodes.
- The physical inputs of every run are the same as `case.json`; the SHA-256 digest
  is in the result record. Full-mesh `model.json` files are produced by the replay tool.

Source commands, signs, criteria, and scope are in the [S4 protocol](../../s4-comparison.md).
Results from an independent sheet-pile program are **absent** from this directory. That
absence is not a deferral note; it is a product boundary: internal Winkler agreement is
not an RS2/PLAXIS pass.
External table format: [s4-external.md](../../s4-external.md).
