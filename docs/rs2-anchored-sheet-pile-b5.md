# RS2 Anchored Sheet Pile Wall — B5 input lock and capability gap

This document records only inputs that are publicly visible in the current Rocscience
RS2 **Anchored Sheet Pile Wall** tutorial or its scripting variant. It is a prerequisite
for external benchmark B5, not a benchmark pass.

Official sources:

- https://www.rocscience.com/help/rs2/tutorials/support/anchored-sheet-pile-wall
- https://www.rocscience.com/help/rs2/tutorials/scripting/anchored-sheet-pile-wall

## Published response targets

The current online tutorial reports approximately:

- lower tieback maximum axial force: **59 kN**;
- sheet-pile maximum bending moment: **71 kNm**.

These values are comparison targets only after the same model has been reproduced.
They must not be used to tune unknown inputs.

## Geometry and stages

The published tutorial defines:

- model domain: 30 m by 18 m;
- material boundary: y = 14 m;
- excavation boundary at x = 10 m / y = 10 m;
- wall: (10, 18) to (10, 8);
- upper tieback: (10, 17) to (18, 14), installed in Stage 3;
- lower tieback: (10, 13) to (18, 10), installed in Stage 4;
- 10 kPa surface surcharge in Stage 5;
- graded mesh with 3-noded triangles, approximately 120 elements;
- bottom fixed in x and y, vertical sides fixed in x, top surface free.

The wall is installed in Stage 2. The tutorial uses a structural interface made from
joints on the wall faces.

## Publicly visible support properties

### Sheet-pile liner

The tutorial property image shows:

- standard beam;
- E = 30,000,000 kPa;
- Poisson ratio = 0.2;
- thickness = 0.2 m;
- elastic response;
- Timoshenko formulation;
- self-weight excluded.

For a unit out-of-plane rectangular section, the direct geometric mapping is
A = 0.2 m2/m and I = 0.2^3 / 12 = 6.6666667e-4 m4/m. Any shear-area mapping used for
a strict comparison must be documented explicitly rather than silently tuned.

### Wall joints

The joint property image shows:

- Mohr-Coulomb slip;
- kn = 100,000 kPa/m;
- ks = 10,000 kPa/m;
- cohesion = 0 kPa;
- friction angle = 35 degrees;
- tensile strength = 0 kPa;
- initial joint deformation enabled.

### Upper tieback

The property image shows:

- diameter = 19 mm;
- E = 200,000,000 kPa;
- tensile capacity = 100 kN;
- spacing = 1 m;
- bond shear stiffness = 10,000 kN/m2;
- bond strength = 5,000 kN/m;
- borehole diameter = 50 mm;
- pretension = 20 kN;
- bond percentage = 40%;
- constant pretensioning force in the installation stage.

The corresponding steel axial stiffness from the published diameter and E is about
56,705.75 kN per tieback.

### Lower tieback

The lower tieback uses the same published properties except pretension = **50 kN**.
Its bond percentage is also 40%.

## Soil properties visible in the scripting tutorial

The scripting tutorial exposes the following edits to the starting model.

Material 1:

- unit weight = 17 kN/m3;
- Poisson ratio = 0.25;
- plastic material;
- peak cohesion = 1 kPa;
- residual cohesion = 1 kPa.

Material 2 ("Clay"):

- unit weight = 20 kN/m3;
- Poisson ratio = 0.25;
- E = 15,000 kPa;
- plastic material;
- peak and residual friction angle = 25 degrees;
- peak and residual cohesion = 10 kPa.

The current public scripting page does **not** set Material 1 Young's modulus or
friction angle; those values are inherited from the installed starting model. They are
therefore still unresolved for a strict independent reproduction.

## Delivered topology prerequisite

SlipSurfaceIQ-FEA now provides
`add_bar_with_bonded_tail(mesh, node_head, bond_start_node, bonded_edge_set, tag)`.

It creates:

1. one free-length BAR2 from the anchor head to the start of the bonded zone; and
2. a BAR2 chain along the named bonded edge set, sharing continuum nodes.

The helper validates that the bonded edge set is one connected, non-branching open chain
and that the bond-start node is its endpoint. For the RS2 geometry, a 40% bonded tail can
therefore be represented geometrically without replacing the free length by a fully
bonded bar.

## Finite bond-slip status

The helper above is deliberately a **perfect-bond topology**. Shared continuum/bar nodes
impose zero relative displacement in the bonded tail.

The local axial grout law is now implemented and independently characterized as a
symmetric elastic-perfectly-plastic relation. The RS2 documentation defines bond strength
as force per unit bonded length and bond shear stiffness as force per length per length;
the tutorial values are therefore recorded as 5,000 kN/m and 10,000 kN/m2 respectively.
See [b5-bond-slip-law.md](b5-bond-slip-law.md).

The solver-level bonded-length transfer is now implemented as BOND4 without a guessed
normal penalty. Host continuum motion is combined with an internal scalar tendon-slip
field, and the verified bond law is integrated at two Gauss points. The dedicated
`b5-embedded-bond` workflow passes an independent elastic shear-lag comparison; the
32-segment head-reaction error is approximately 0.0217%.
See [b5-embedded-bond-transfer.md](b5-embedded-bond-transfer.md).

This closes the **bonded tail** mechanics prerequisite only. The RS2 tieback also contains
an unbonded length in series with the bonded length and a pretensioned wall-head
connection. Those pieces must be assembled and verified before the tutorial response can
be compared.

Therefore B5 remains **BLOCKED / NOT A PASS** until both conditions are met:

1. the exact Material 1 E and friction angle from the official starting model are
   captured from an authoritative source; and
2. an independently verified unbonded tendon / wall-head connector is assembled in
   series with the verified BOND4 bonded tail, including pretension staging.

Only after those blockers are closed should the 59 kN / 71 kNm response targets and
full-model mesh-convergence tolerances be promoted into a strict CI gate.
