"""Interface form parsing must preserve the explicit law without Qt or CAD imports."""

from dataclasses import asdict

import pytest

from slipsurface.fe2d.core.errors import ModelError
from slipsurface.fe2d.gui.interface_authoring import interface_spec_from_fields
from slipsurface.fe2d.model.materials import InterfaceSpec


def fields():
    return dict(kn="2000", ks="1000", c="5", phi="30", psi="10", sig_t="1",
                initial_gap="0.002")


def test_existing_normal_contact_is_not_silently_replaced_by_goodman():
    old = InterfaceSpec.unilateral_normal("contact", 2000.0, initial_gap=0.002)
    raw = {key: str(value) for key, value in asdict(old).items()}
    new = interface_spec_from_fields(old.name, old.law, raw, original=old)
    assert new == old
    assert new is not old


def test_old_goodman_spec_is_unchanged_without_an_explicit_law_switch():
    old = InterfaceSpec("legacy", 2000, 1000, 5, 30, 10, 1)
    new = interface_spec_from_fields(old.name, old.law, fields(), original=old)
    assert new == old
    assert new.initial_gap == 0


def test_explicit_normal_law_ignores_disabled_strength_fields():
    raw = fields()
    for key in ("ks", "c", "phi", "psi", "sig_t"):
        raw[key] = "invalid disabled text"
    spec = interface_spec_from_fields("contact", "unilateral_normal", raw)
    assert spec == InterfaceSpec.unilateral_normal("contact", 2000, initial_gap=0.002)


def test_explicit_goodman_law_ignores_disabled_clearance():
    raw = fields()
    raw["initial_gap"] = "invalid disabled text"
    spec = interface_spec_from_fields("joint", "goodman", raw)
    assert spec.initial_gap == 0
    assert spec.phi == 30 and spec.psi == 10


@pytest.mark.parametrize("law,key", [
    ("goodman", "kn"), ("goodman", "ks"), ("goodman", "c"),
    ("goodman", "phi"), ("goodman", "psi"), ("goodman", "sig_t"),
    ("unilateral_normal", "kn"), ("unilateral_normal", "initial_gap"),
])
@pytest.mark.parametrize("bad", ["", "nan", "inf", True, None])
def test_active_fields_fail_closed(law, key, bad):
    raw = fields()
    raw[key] = bad
    with pytest.raises(ValueError, match=key):
        interface_spec_from_fields("contact", law, raw)


@pytest.mark.parametrize("law,patch", [
    ("unilateral_normal", {"kn": "0"}),
    ("unilateral_normal", {"initial_gap": "-0.001"}),
    ("goodman", {"phi": "90"}), ("goodman", {"psi": "40"}),
    ("goodman", {"c": "-1"}),
])
def test_native_property_validation_is_not_bypassed(law, patch):
    with pytest.raises(ModelError):
        interface_spec_from_fields("contact", law, {**fields(), **patch})


@pytest.mark.parametrize("name,law", [("", "goodman"), ("  ", "unilateral_normal"),
                                      ("joint", "unknown"), ("joint", None)])
def test_invalid_identity_or_selector_rejected(name, law):
    with pytest.raises(ValueError):
        interface_spec_from_fields(name, law, fields())


def test_switching_a_copy_does_not_mutate_original_spec():
    old = InterfaceSpec("joint", 2000, 1000, 5, 30, 10, 1)
    snapshot = asdict(old)
    edited = interface_spec_from_fields("joint", "unilateral_normal", fields(), original=old)
    assert edited.law == "unilateral_normal"
    assert asdict(old) == snapshot
