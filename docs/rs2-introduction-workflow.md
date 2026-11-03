# RS2 introduction tutorial → SlipSurfaceIQ-FEA implementation contract

Reference: https://www.rocscience.com/help/rs2/tutorials/introduction/introduction-to-rs2

Goal: reproduce the **engineering workflow and observable behaviours**, not copied
Rocscience artwork, proprietary iconography, branded UI, or source code.
SlipSurfaceIQ remains a native PySide6 desktop application. The CAD canvas
remains embedded. Interpret opens as a separate window.

## Expected user workflow

1. **Project Settings**: metric/SI display units, analysis type, construction stage
   count and unique names. Stages are managed in the Project Properties *Stages*
   tab (no additional floating stage manager).
2. **Geometry**: external boundary, circle/tunnel excavation, rectangular trench.
   All inputs are CAD-native: mouse pick, typed coordinates, snaps and fit view.
3. **Materials & staging**: materials can be assigned before meshing. At each
   stage, clicking a region can change it to Excavated or a material, and the
   drawing immediately reflects that stage's geometry.
4. **Loading**: pick a model edge, assign a uniform load and editable per-stage
   factors (0 until loading stage; 1 at final stage in the reference tutorial).
   Initial gravitational stresses must distinguish body force and pre-existing
   field stress to prevent double counting.
5. **Mesh**: discretization controls, local refinement near excavations, quality
   diagnostics including minimum element area, Jacobians and aspect ratios.
   Generation should not obscure CAD structure/bolt objects.
6. **Restraints**: select edges/nodes on the canvas to apply Free, X only, Y only,
   and X/Y. Side boundaries are X-fixed, bottom is Y-fixed with both corners
   X/Y fixed in the reference case. The symbols and stage assignment must be
   visible without opening an unrelated fixity dialog.
7. **Analysis**: Analysis > Compute triggers the existing worker, showing
   stage name, progress, load factor, nonlinear iteration and residual.
8. **Interpret**: independent window with stage tabs, contour field dropdown,
   legend, deformation scale and principal-stress overlay. Future additions:
   strength factor (validated constitutive definition), stage animation,
   contour interval controls, material point/line queries and stage-comparison
   graphs.

## Reference case acceptance conditions

The RS2 *Introduction* example uses an external box from (-10,-8) to (15,4),
a tunnel excavation centred on (0,0), a trench with corners at (4.5,4),
(4.5,-1), (6.5,-1), (6.5,4), and three construction stages:
Excavate Tunnel, Excavate Trench, Surface Load. The sample load magnitude is
0.2 MPa, equivalent to 200 kPa in this project's internal units.

- Stage 1: tunnel excavated, trench intact, load absent.
- Stage 2: tunnel + trench excavated, load absent.
- Stage 3: same excavations, surface load applied (stage factor 1).
- Initial state: gravity field with K0=0.5, overburden unit weight 20 kN/m³,
  assuming the model's conventions are reconciled explicitly.
- External boundaries: top free, left/right ux fixed, bottom uy fixed,
  two bottom corners ux and uy fixed.

**Do not hard-code tutorial output displacements as solver acceptance values**:
they depend on constitutive formulations, stress-convention conversions,
mesh discretization, load application and convergence tolerances. Validate
mesh and load/result equilibrium independently before comparison to RS2.

## Current implementation mapping

| Workflow | Current implementation | Missing / next task |
| --- | --- | --- |
| Project Settings | Model > Project properties with Stages tab | Units and consolidated settings grid |
| Geometry | Embedded CAD, tunnel designer, region draw | More consistent excavation tools |
| Materials | Material editor + prem esh region assignments | Stage-aware direct-pick material palette |
| Loading | CAD boundary table and stage loads | Direct edge-pick stage factor editor |
| Mesh | CAD mesh workflow, T6 | Discretize preview, local grading controls |
| Restraints | CAD edge pick ux/uy | Free / X / Y / XY presets and node symbols |
| Compute | Async worker + progress dialog | Structured step-type and per-stage progress |
| Interpret | Separate window + stage tabs and stress/displacement dropdown | Queries, animations, contour controls |

## First UI patch

This patch adds an **Analysis** menu (Project Settings, Compute, Interpret),
removes duplicate Interpret menu items, and improves the independent Interpret
window to contain result fields, bottom stage tabs, deformation scale and a
principal-stress toggle. All pre-existing toolbar labels remain unchanged
to avoid changing shortcut and mouse-workflow contracts. This is a
foundation, not an assertion that RS2 workflow parity is complete.

No automatic mesh quality or FEM numerical equivalence is claimed.
