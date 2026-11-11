"""Presentation/export must preserve the numerical audit's exact verdicts."""

from __future__ import annotations

import copy
import json
import pickle
import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from slipsurface.fe2d import api
from slipsurface.fe2d.io.contact_audit_json import export_contact_audit_json
from slipsurface.fe2d.post.contact_audit_report import (
    audit_rows,
    audit_summary,
    prepare_contact_audit,
    validate_document,
)
from slipsurface.fe2d.post.contact_topology_equilibrium import contact_topology_equilibrium_by_stage

_B = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts'
                       / 'f7_contact_topology_benchmark.py'))


@pytest.fixture(scope='module', params=['IFACE4', 'IFACE6'])
def native(request):
    return api.run(_B['asymmetric_model'](element_type=request.param))


def test_complete_envelope_preserves_raw_audit_and_indices(native):
    doc = prepare_contact_audit(native)
    assert doc['audit'] == contact_topology_equilibrium_by_stage(native)
    rows = audit_rows(doc)
    assert len(rows) == len(native.stages) + 1
    assert rows[0].snapshot_index == 0
    assert rows[0].fraction is None
    assert rows[0].physical == 'not assessed'
    assert [r.name for r in rows[1:]] == [s.name for s in native.stages]
    for i, row in enumerate(rows[1:]):
        assert row.snapshot_index == i + 1
        assert row.physical == doc['audit']['stages'][i]['physical_equilibrium']['status']


def test_partial_release_is_not_physical_pass(native):
    doc = prepare_contact_audit(native)
    counts = audit_summary(doc)
    assert counts['transition_passed'] == len(native.stages)
    assert counts['physical_not_balanced'] > 0
    assert counts['physical_not_assessed'] == 0
    rows = [r for r in audit_rows(doc) if r.physical == 'failed']
    assert all(r.transition == 'passed' and r.retained_max > 0 for r in rows)


def test_no_solver_or_source_mutation_during_audit(native, monkeypatch):
    from slipsurface.fe2d.fem.static import StaticSolver

    def forbidden(*a, **kw):
        raise AssertionError('read-only audit must not solve')
    before = pickle.dumps(native)
    monkeypatch.setattr(api, 'run', forbidden)
    monkeypatch.setattr(StaticSolver, 'run', forbidden)
    prepare_contact_audit(native)
    assert pickle.dumps(native) == before


@pytest.mark.parametrize('damage', ['missing_gap', 'stress', 'initial', 'incomplete'])
def test_bad_evidence_is_visible_and_never_a_physical_pass(native, damage):
    result = copy.deepcopy(native)
    if damage == 'missing_gap':
        result.stages[1].contact_gap.clear()
    elif damage == 'stress':
        tag = next(iter(result.stages[1].sig))
        result.stages[1].sig[tag][0, 0, 2] += 5.0
    elif damage == 'initial':
        result.initial.reactions[0, 0] = 2.0
    else:
        result.stages.pop()
    doc = prepare_contact_audit(result)
    assert doc['audit']['status'] == 'failed'
    rows = audit_rows(doc)
    assert any(r.transition in ('invalid', 'failed', 'blocked') for r in rows)
    assert all(r.physical == 'not assessed' for r in rows
               if r.transition in ('invalid', 'failed', 'blocked'))


def test_unsupported_material_is_not_generic_success(native):
    result = copy.deepcopy(native)
    tag = next(iter(result.model.materials))
    result.model.materials[tag] = api.MaterialSpec.mohr_coulomb(tag, 2000, 0.25, 10, 30)
    doc = prepare_contact_audit(result)
    assert audit_rows(doc)[0].transition == 'unsupported'
    assert 'reason' in doc['audit']
    assert audit_summary(doc)['physical_not_assessed'] == len(result.stages)


def test_duplicate_names_remain_separate(native):
    result = copy.deepcopy(native)
    result.model.stages = [replace(s, name='repeat') for s in result.model.stages]
    for snapshot in result.stages:
        snapshot.name = 'repeat'
    rows = audit_rows(prepare_contact_audit(result))[1:]
    assert all(r.name == 'repeat' for r in rows)
    assert len({r.snapshot_index for r in rows}) == len(rows)


@pytest.mark.parametrize('origin', [(2., -3.), (0., 0.)])
def test_origin_export_and_defaults_preserved(native, origin):
    doc = prepare_contact_audit(native, origin=origin)
    assert tuple(doc['origin_m']) == origin
    assert doc['audit'] == contact_topology_equilibrium_by_stage(native, origin=origin)
    assert doc['audit']['tolerances']['force_atol'] == 1e-8


@pytest.mark.parametrize('origin', [(float('nan'), 0), (0, float('inf')), (0,), (True, 0)])
def test_invalid_origins_rejected(native, origin):
    with pytest.raises((ValueError, TypeError)):
        prepare_contact_audit(native, origin=origin)


def test_atomic_export_matches_displayed_document_without_reaudit(native, tmp_path, monkeypatch):
    import slipsurface.fe2d.post.contact_audit_report as report

    doc = prepare_contact_audit(native)
    def forbidden(*a, **kw):
        raise AssertionError('do not recalculate during export')
    monkeypatch.setattr(report, 'contact_topology_equilibrium_by_stage', forbidden)
    path = tmp_path / 'audit.json'
    export_contact_audit_json(doc, path)
    assert json.loads(path.read_text()) == doc
    assert len(json.loads(path.read_text())['audit']['stages']) == len(native.stages)


@pytest.mark.parametrize('damage', ['nan', 'status', 'schema', 'cardinality', 'identity'])
def test_malformed_export_never_replaces_existing_file(native, tmp_path, damage):
    doc = prepare_contact_audit(native)
    if damage == 'nan':
        doc['origin_m'][0] = float('nan')
    elif damage == 'status':
        doc['audit']['status'] = 'failed'
    elif damage == 'schema':
        doc['schema'] = 'unsupported'
    elif damage == 'cardinality':
        doc['audit']['stages'].pop()
    else:
        doc['audit']['stages'][0]['stage_index'] = True
    path = tmp_path / 'audit.json'
    path.write_bytes(b'preserve original')
    with pytest.raises((ValueError, TypeError)):
        export_contact_audit_json(doc, path)
    assert path.read_bytes() == b'preserve original'
    assert len(list(tmp_path.iterdir())) == 1


def test_failed_and_unsupported_reports_are_exportable(native, tmp_path):
    result = copy.deepcopy(native)
    result.last.contact_gap.clear()
    doc = prepare_contact_audit(result)
    path = export_contact_audit_json(doc, tmp_path / 'failed.json')
    assert json.loads(path.read_text())['audit']['status'] == 'failed'


def test_atomic_replacement_failure_preserves_original(native, tmp_path, monkeypatch):
    import slipsurface.fe2d.io.results_h5 as h5

    path = tmp_path / 'audit.json'
    path.write_bytes(b'original')
    def fail(*args):
        raise OSError('intentional replace failure')
    monkeypatch.setattr(h5.os, 'replace', fail)
    with pytest.raises(OSError):
        export_contact_audit_json(prepare_contact_audit(native), path)
    assert path.read_bytes() == b'original'
    assert len(list(tmp_path.iterdir())) == 1


def test_validation_detaches_mutable_arrays(native):
    doc = prepare_contact_audit(native)
    detached = validate_document(doc)
    detached['origin_m'][0] = 99.
    assert doc['origin_m'][0] == 0.


def test_restored_saved_history_has_same_audit(native, tmp_path):
    path = tmp_path / 'audit.ssproj'
    api.save_project(native.model, path, native)
    restored = api.load_project(path).results
    assert prepare_contact_audit(restored) == prepare_contact_audit(native)


def test_no_result_rejected():
    with pytest.raises(ValueError, match='Stored'):
        prepare_contact_audit(None)
