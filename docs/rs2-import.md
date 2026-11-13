# RS2 FEA/FEZ import

SlipSurfaceIQ-FEA can open RS2 `.fea` files and `.fez` archives from **File → Open**.
The first importer pass is intentionally conservative and is designed to make an RS2
model inspectable without claiming solver equivalence.

## Transferred data

- Plane-strain, 3-node triangular continuum mesh (RS2 node IDs are remapped to zero-based IDs).
- Metric MPa Mohr-Coulomb peak properties, converted to the SlipSurface kPa / kN/m3 unit system.
- Element-wise initial stresses, stored as constant stress at each continuum element's integration points.
- Stage names, continuum element deletion, continuum material reassignment, and nodal fixities.
- RS2 Euler-Bernoulli beam segments, activation stages, and stage-specific section changes.

## Explicit limitations

The importer report lists unsupported content. In particular, bonded-bolt grout transfer,
RS2 beam joint parameters, residual-property differences, and non-uniform beam activation
histories within one material group are not silently approximated. RS2 body-force fields
are transferred cumulatively by stage.
An imported model with any unsupported feature is a preview-only model: the desktop app blocks
solving and saving it as a native `.ssproj` until those mappings are implemented. RS2
`.r##` result files are not loaded as SlipSurface solver results.

Use the public API to inspect the import report:

```python
from slipsurface.fe2d import api

imported = api.import_rs2("model.fez")
print(imported.report)
print("analysis ready:", imported.report.analysis_ready)
```

The importer currently accepts RS2 plane-strain models using the Metric MPa unit system
and linear triangular continuum elements. Unsupported unit systems and missing core mesh
sections are rejected rather than guessed.
