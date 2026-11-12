# B5 unbonded + bonded tieback series mechanics

This feature adds the unbonded tieback length and wall/head connector in series with the
previously verified BOND4 bonded tail. It is still a bounded mechanics prerequisite for
the RS2 Anchored Sheet Pile Wall case, not the external B5 pass.

## Topology

`add_tieback_series(mesh, node_head, bonded_edge_set, tag, bond_start_node=...)` creates:

- `<tag>:free`: one TIE3 element for the complete unbonded length;
- `<tag>:bond`: the existing BOND4 chain for the bonded length.

TIE3 connectivity is `[head, host_bond_start, scalar_bond_start]`. The tendon
displacement at its bonded end is

    u_t = e · u_host + s

using exactly the first scalar tendon-slip coordinate of the BOND4 tail. Therefore the
two regions are mechanically in series and the transition does not introduce a false
soil anchorage.

The helper requires the free length and first bonded segment to be straight and forward
continuous, matching the current straight-tieback scope.

## Unbonded element

The TIE3 strain measure is

    Delta = e · (u_host - u_head) + s_start

and its axial force uses the existing BoltSpec contract:

    N_trial = N_n + (EA / L_u / spacing) * Delta

with the existing tensile-capacity clamp and pretension initial force.

## Independent series verification

Run:

    PYTHONPATH=src python scripts/b5_tieback_series_benchmark.py --require-pass

For a fixed host, the bonded-tail head stiffness is

    K_b = EA * lambda * tanh(lambda * L_b)
    lambda = sqrt(k_b / EA)

and the unbonded stiffness is

    K_u = EA / L_u

so the exact series stiffness is

    K_series = K_u * K_b / (K_u + K_b).

The dedicated `b5-tieback-series` workflow compares the FE head reaction against this
closed-form reference over 4, 8, 16 and 32 bonded segments and checks force continuity
between TIE3 and the first BOND4 segment. Unit tests also verify TIE3 pretension
initialization and JSON/HDF5 persistence.

## RS2 correspondence and remaining gap

RS2 documents a tieback as one unbonded element plus a bonded length divided by mesh
intersections. The new TIE3+BOND4 topology follows that decomposition.

RS2 also provides **Constant Force in Install Stage**: when enabled, the installation
stage ends with the bolt force held at the specified pretension and rock stresses do not
change that bolt force during the install stage. The current SlipSurface pretension
contract remains an initial axial force that can evolve during the same stage.

Therefore this PR does not claim equivalence to the tutorial's pretension staging.

## Deliberate limits

- plane strain only;
- straight tieback axis;
- no joint-shear interaction along the unbonded length;
- no constant-force installation-stage controller yet;
- no completed RS2 wall/tieback staged model;
- Material 1 Young's modulus and friction angle are still unresolved from the public
  tutorial pages.
