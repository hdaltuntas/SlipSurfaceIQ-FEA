# CAD, piles, tunnels, and supports in the main window

The FEA main window was rearranged after the [Modeler layout](https://github.com/hdaltuntas/SlipSurfaceIQ-LE/blob/main/slipsurface/ui/modeler.py)
and the CAD area of SlipSurfaceIQ-LE were reviewed: menus and the workflow are at the
top, object/fixity/support tabs are on the left, the ruled drawing is in the centre, and
coordinate entry and SNAP / GRID / ORTHO / OSNAP are at the bottom. CAD does not open a
separate window. The modeller and the most recently generated mesh/result view switch
inside the same main window.

![Integrated modeller](images/integrated-modeler.png)

## Drawing and calculation flow

1. **New** starts with an empty drawing. Draw a region from the **Geometry** menu; points
   can be entered with the mouse or as `x,y`, `@dx,dy`, `@length<angle`.
2. From the **Structures** step or the **Support** menu, choose a pile, a tunnel, a liner,
   or an anchor/soil nail. A pile and an anchor are completed with two ends. For a liner,
   enter the points and finish with Enter. For a tunnel, pick the centre and a radius point.
3. Select the object from the drawing. On the **Support** tab at the left, change the
   section, stiffness, and activation values and use **Apply support to the selected object**.
4. On the **Fixity / load** tab, define the fixities that prevent rigid-body motion of the
   soil, and the edge pressures. **Generate mesh** turns the drawing into a real FEM mesh.
5. Check the materials and the stages and start the analysis with **Solve**. **F6** shows
   the last generated mesh/results; **Geometry / CAD** shows the current drawing.

| Tool | Geometry | Analysis counterpart |
|---|---|---|
| Pile | Two-point line | BEAM2 sharing nodes with the soil; E, A, I, and As per metre |
| Tunnel | Centre + radius; 32 straight edges | A void, or a separate excavation region |
| Tunnel lining | Around the tunnel | BEAM2 along the perimeter |
| Liner | A polyline, or a selected closed boundary | BEAM2 along the line/boundary |
| Anchor / soil nail | Two-point line | Fully bonded BAR2 along the line; EA and capacity of one nail, made 2D-equivalent by the spacing |

If **staged excavation region** is selected, the tunnel starts full, as a newly numbered
material region. Excavate it by deactivating that region in the stage editor; also select
the liner’s activation in the relevant stage. If it is not selected, the tunnel is a void
from the start.

New supports are active by default in the **CAD installation** stage; they can be created
passive from the panel. The pile default section is D = 0.8 m and the out-of-plane spacing
is 2 m; the liner thickness is t = 0.3 m. Edit these starting values for your own project.

Drawn supports are fully bonded to the soil. Slip/separation interfaces and end-anchored
bolts are defined from the advanced structure editor on the existing mesh. The tunnel tool
approximates a circular section with a polygon; other sections are made with the
polygon/coordinate editor.

## Save, undo, and remeshing

- `.sscad.json` stores the drawing, the fixities/loads, and the support definitions. The
  new format is v2; old v1 drawings are also read. **Save** opens the drawing record when
  there is a draft that still needs a mesh; it saves a completed model as `.ssproj`.
- The `geometry` entry inside `.ssproj` carries the drawing together with its supports.
  On reopen, the CAD and the real FEM support properties are kept. Changing or deleting
  the property of a CAD-linked support in the advanced editor is reflected in the drawing
  definition as well.
- Geometry/support edits can be undone. Mesh generation does not clear the drawing undo
  history. Unsaved drawings are protected when the window closes.
- Once the drawing changes, solving against the old mesh and saving `.ssproj` are blocked.
  The mesh must be generated again first, or the draft must be saved separately.
- Remeshing transfers the current model’s definitions onto the new mesh (`cad/transfer.py`).
  The drawing is authoritative for what it defines itself: regions, CAD supports, edge
  fixities, and CAD pressures. Everything else is matched by name: the material library
  and region assignments, the initial stress, the solver settings, the stages (load, water,
  region/structure activity, material change), extra fixities, and interfaces/liners/bolts
  added by the advanced editor. Interfaces and structures are rebuilt on the named edge
  they were attached to. Point loads and bolt ends tied to a node move to the nearest new
  node. Newly drawn regions and supports start active in every stage. Definitions that no
  longer have a target are removed and listed one by one in the **Solution log**. Results
  are deleted because they are invalid on the new mesh. Old projects that have no CAD input
  open, but geometry is not extracted automatically from the existing mesh.

## Workflow bar and layout

The full-width row under the menus shows eight numbered steps: Geometry › Supports ›
Fixity / load › Mesh › Materials › Stages › Solve › Results. Completed steps are green
with a ✓; the active step is dark blue; the text on the right states the next step.
Clicking a step opens the related drawing tab or editor. **Mesh** generates the mesh;
**Solve** starts the solution. Editors at the mesh-set level are in the **Model** menu.

The project panel and the convergence/log panel are opened and closed from the **View**
menu. **Reset layout** returns to the default arrangement. Window size, panel choices,
and splitter positions are saved to the user settings (INI) on close. The theme stays
light regardless of Windows dark mode: the Qt ≥ 6.8 colour scheme is pinned to light,
and `QT_QPA_PLATFORM=windows:darkmode=0` is used on Windows. Palette and style pairs
pass the WCAG AA (≥ 4.5:1) contrast test.

![Guided workflow](images/workflow-guided.png)

## Controls

| Action | Shortcut |
|---|---|
| Last generated mesh/result | F6 |
| Fit the drawing or the mesh | F2 |
| Snap to grid | F9 / SNAP |
| Grid visibility | F7 / GRID |
| Horizontal/vertical drawing | F8 / ORTHO |
| End/midpoint snap | F3 / OSNAP |
| Pan / zoom | Middle button / wheel |
| Undo / redo | Ctrl+Z / Ctrl+Y |

![Support properties](images/integrated-support-properties.png)

![1200 × 800 view](images/integrated-modeler-compact.png)

## Verification

Full repository run: **493 passed, 1 known xfail** (2 performance tests out of scope).
Ruff and diff whitespace checks are clean. The last keyboard/default-button fix was tested separately.

`test_integrated_modeler.py`: embedding in the main window and a visible mesh button,
support drawing with real mouse events, mesh connectivity and an elastic solve, staged
excavation with a liner, support properties/rename/delete/undo, the drawing and project
save round trip, the block on solving/saving against an old mesh, protection of an unsaved
drawing, v1 compatibility, independence of SNAP/OSNAP, and consistency of the support
definition with the advanced editor.

The images were taken from real Qt widgets in a Linux offscreen environment.
Windows high-DPI visual acceptance and the user review are not finished yet.
Release publication is closed.
