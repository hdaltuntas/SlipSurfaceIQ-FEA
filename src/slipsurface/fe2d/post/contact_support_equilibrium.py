"""Independent history audit for temporary normal-contact model restraints.

Stage Displacement entries can add/remove prescribed translation DOFs. Permanent
Model.fixities remain permanent. Reconstruct retained release from preceding
stresses and CURRENT-active contact, not from a copied previous reaction vector.
"""

from .contact_activation_equilibrium import _contact_history_equilibrium

_SCOPE = (
    "Dry drained stress-free zero-gravity normal contact; fixed active continuum "
    "covering every node. Stage prescribed translation DOFs and contact activity "
    "may change. Effective transition equilibrium is separate from physical-only "
    "equilibrium. No excavation, gravity, water, friction, beams/bars, restart or "
    "independent software/design certification. Model.fixities are permanent."
)


def contact_support_equilibrium_by_stage(
    result, *, origin=(0.0, 0.0), force_atol=1e-8, moment_atol=1e-8,
    traction_atol=1e-8, gap_atol=1e-10, rtol=1e-8,
):
    """Audit removal/reintroduction of stage displacement restraints explicitly.

    H_i=(1-alpha_i)*P_free_current*(I0_i-F_previous). The projection is
    onto the CURRENT free DOFs, including newly released ones. A restraint
    reintroduced at value d uses u_i=(1-alpha)*u_previous+alpha*d.
    A missing restraint does not prescribe zero displacement. Result snapshots
    contain accepted states, not nonlinear restart checkpoints.
    """
    return _contact_history_equilibrium(
        result, origin=origin, force_atol=force_atol, moment_atol=moment_atol,
        traction_atol=traction_atol, gap_atol=gap_atol, rtol=rtol,
        support_changes=True, scope=_SCOPE,
    )
