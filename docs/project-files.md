# Project and result files

```python
from slipsurface.fe2d import api

result = api.run(model)
api.save_results(result, 'results.h5')
api.save_project(model, 'analysis.ssproj', results=result)

project = api.load_project('analysis.ssproj')
model = project.model
result = project.results           # None when the project has no results
api.export_vtu(result, 'last.vtu')  # post-processing without solving again

# Model only: result arrays are not read.
model = api.load_project('analysis.ssproj', include_results=False).model

# Large HDF5 file: the model/mesh open immediately; a stage is loaded only when requested.
with api.ResultsReader('results.h5') as reader:
    print(reader.stage_names)
    stage = reader.stage(-1)
# stage arrays are then independent of the file.

# Loads every result and the post-processing geometry into memory.
result = api.load_results('results.h5')
```

`save_model` / `load_model` keep the previous plain JSON format. The new APIs are
offered under separate names. The existing project JSON schema was not changed.

`.ssproj` is a ZIP file containing `model.json`, `mesh.h5`, and an optional `results.h5`.
The model JSON has `project_version=1`, the existing `schema_version`, and `mesh_file`;
coordinates and connectivity lists are not repeated inside the JSON. A saved result whose
model differs from the model is rejected. The reader reads only the fixed member names; it
does not extract the ZIP freely onto the file system.

HDF5 result format v1 contains `/mesh`, `/model`, `/initial`, and `/stages/<i>`. Mesh
blocks and field dictionaries are stored as numbered groups; user labels are attributes.
Names that contain `/`, and stages with the same name, are therefore preserved without
loss. Access by name returns the first match; access by index returns that exact stage.
Block order is numerical index order.

Each stage keeps `u`, `rotation`, `reactions`, `sig`, `q`, `plastic`, `active`, `pore`,
`beams`, `bars`, `interfaces`, `struct_flags`, the load factor, timings, and every step
record (including failed attempts). Arrays are stored with their NumPy dtype and NaN
values; empty arrays are supported; non-empty arrays are gzip-compressed. Metadata
includes the units, the tension-positive sign, the per-radian measure in axisymmetry,
and the solver version. Later schema versions are not interpreted silently; they are rejected.

Files are written to a temporary file in the same folder and replaced atomically after a
successful close. On a write error the existing file is kept. Result files are
post-processing snapshots; they do not support a nonlinear solver restart. What is
supported is a complete model/result record; SRF trial history and partial/failed solver
sessions are outside this format.
