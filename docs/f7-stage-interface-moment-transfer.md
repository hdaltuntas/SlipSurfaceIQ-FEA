# F7 — Stage-wise effective interface force and moment transfer

The existing optional three-resolution pile/anchor excavation audit checks
signed effective interface force resultants and their nodal assembly.
This increment also computes the **out-of-plane first moment** of the
effective traction acting on the two interface faces.

The new `stage_effective_interface_moment_audit` reads the actual
`StageResult.interfaces` arrays, using the same mesh geometry and
activation data as the FEM result. For every active zero-thickness
interface element, the effective local shear/normal tractions are
independently rotated to global coordinates and integrated into
face-force and moment references. These quantities are compared to
the nodal internal forces assembled by `InterfaceGroup._assemble`.

The moment convention is `Mz=x*Fy-y*Fx` about the global origin
(kN·m/m in plane strain). Each face's integrated moment is checked
against its own nodal moment. When geometrically coincident faces
carry an equal/opposite traction, both the net force and moment
must vanish. Physically separated faces must not be mistaken for
zero-moment action/reaction merely because their net force is zero.

Completely inactive (all-NaN) interface traction blocks are reported
as `unsupported`, not `passed`; partially nonfinite active blocks
are rejected.

The existing optional `examples/f7_excavation_mesh_audit.py` now
records `interface_moment_transfer` per stage and mesh resolution
and includes it as a separate JSON section in the final report.

This is **an assembly consistency verification**, not an independent
soil–support physics reference. It does not validate external
hydrostatic loads, pile bending from soil tractions, bolt force
transfer, or the continuum–structure global equilibrium. Those
still require independent physical benchmarks and the full
three-mesh supported excavation run.
