# F7/V5 — Plastic cavity radius, displacement and mesh sensitivity

The F7 plastic cavity verification extends the elastic Kirsch tests
(PR #29) and the existing Salençon 1969 verification in
`tests/verification/test_p3_salencon_tunnel.py`.

## Independent physical reference

The quarter-domain model has a=1 m, L=25 m, E=10,000 kPa,
nu=0.25, cohesion c=10 kPa, friction phi=30 degrees,
initial isotropic stress -p0=-100 kPa and cavity support
pressure pi=10 kPa. Stresses are tension positive; pressures
are positive into the ground. The solution is a plane-strain
Mohr–Coulomb stress-release benchmark, not a Hoek–Brown
or supported NATM tunnel.

The reference threshold and plastic radius are

    k = (1+sin phi)/(1-sin phi)
    H = c / tan phi
    sc = 2*c*sqrt(k)
    pcr = (2*p0-sc)/(1+k)
    Rplastic/a = [2*(p0+H)/((1+k)*(pi+H))]**(1/(k-1))

For pi >= pcr the entire problem remains elastic; wall
displacement is -(p0-pi)*a/(2G), G=E/(2*(1+nu)).
For pi < pcr the independent plastic-wall displacement
is calculated by integrating the non-associated radial
flow equation in the yielded annulus. The plastic radius
is independent of dilation psi, while the wall displacement
depends on psi.

## Three-mesh numerical audit (optional)

Run after installing the core dependencies:

    python examples/f7_salencon_mesh_audit.py --psi 15 --resolutions 24x24 40x32 60x48 --output-dir f7_salencon

Output includes `salencon_mesh_audit.json` and
`salencon_mesh_audit.csv`, with node/element counts,
wall displacement and nonuniformity, estimated plastic
radius and their relative errors against independent
references. It records accepted/rejected load steps,
Newton iteration counts, last accepted force residual,
and any failed solve with exception details.

The reported plastic front is a Gauss-point bracket:
halfway between the farthest yielded and nearest
unyielded Gauss-point radius. That estimator is approximate
and must not be treated as a mathematically exact front
location. The finite square is not an infinite domain.
The three-mesh solve is intentionally *not* run as a
routine CI job because it is nonlinear and potentially
expensive; only the fast analytical and report extraction
checks are run automatically.

## Acceptance gates before engineering sign-off

- Run all three mesh levels and compare wall displacement,
  plastic radius and circumferential dispersion against
  the analytical values. Do not declare convergence if
  an intermediate mesh fails or successive results oscillate.
- Compare different dilation angles (0°, 15°, 30°),
  including the possibility of zero-dilation apex
  obstruction and proper solver failure diagnostics.
- Review accepted/rejected Newton increments, rollback,
  material state invariants, and sensitivity to the
  specified tolerances and load increment schedules.
- Test support activation and excavation pressure release
  separately from the unsupported plastic cavity.
- Add independently assembled stage force balance and
  field tests for beam/bolt/liner actions.

Successful CI confirms only the scoped analytical formulas
and report helpers. It does not demonstrate that the
optional audit has passed or that RS2/PLAXIS numerical
agreement has been established.
