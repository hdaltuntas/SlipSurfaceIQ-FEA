# F7 — Combined effective interface traction and hydrostatic water force/moment

This bounded verification bridges previously independent F7 studies:
the interface effective-traction transfer audit and the analytical
hydrostatic force/pressure-centre audit.

The two terms have different meanings in the FEM solver:

- The contact traction is an **internal** effective-stress interface
  force derived from the committed interface state.
- The water pressure is an **external** pore-pressure force acting on
  opposite faces of the zero-thickness joint.

The new `combined_joint_force_moment` routine assembles both terms using
the same real `InterfaceGroup` operators as the solver, and checks
the resulting face forces and moments about the global origin.

For the mechanical term, its reference is the explicitly integrated
effective interface traction and the corresponding first moment. This is
an **assembly consistency check**, not an external physical solution for
the effective stresses. The hydrostatic term has an independent exact
closed-form force and first-moment reference. The combined face-2
expected force and moment are the sums of these two distinct terms.

## Test cases

A four-metre straight vertical plane-strain joint has a uniform
nonzero effective shear/normal traction together with a full-head
hydrostatic pressure distribution. Its hydrostatic contributions
have absolute force 78.48 kN/m and absolute moment 209.28 kN m/m.

The IFACE6 case must satisfy the combined force and moment references
in both interface orientations.

The IFACE4 case is intentionally **failed** for first-moment accuracy:
trapezoidal nodal water-load integration reproduces the total
hydrostatic force but not its application point. Equal-and-opposite
interface face forces cannot make this physical error disappear.

Separate tests cover dry effective traction without water, an
element-interior water-table kink and invalid inactive/nonfinite
traction inputs.

## Limits and remaining F7 acceptance

The benchmark is restricted to straight vertical, fully active
IFACE4/IFACE6 plane-strain interfaces with a horizontal hydrostatic
head. The effective-traction reference is an internal consistency
check rather than an independent soil–support solution. It does
**not** demonstrate actual coupled soil stiffness, pile bending,
anchor force, excavation-induced stress transfer or whole-domain
support reaction equilibrium.

Further F7 work must run real supported excavation stages and
compare combined continuum, interface, liner, anchor, external
water and support-reaction budgets with independently derived
physical benchmarks. The full three-resolution excavation audit
has not been executed in this change.
