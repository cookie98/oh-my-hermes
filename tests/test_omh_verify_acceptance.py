from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path



def _load_module(module_name: str):
    root_pkg = 'hermes_plugins'
    sub_pkg = 'hermes_plugins.oh_my_hermes'
    plugin_dir = Path(__file__).resolve().parents[1]

    if root_pkg not in sys.modules:
        pkg = types.ModuleType(root_pkg)
        pkg.__path__ = []
        pkg.__package__ = root_pkg
        sys.modules[root_pkg] = pkg

    if sub_pkg not in sys.modules:
        pkg = types.ModuleType(sub_pkg)
        pkg.__path__ = [str(plugin_dir)]
        pkg.__package__ = sub_pkg
        sys.modules[sub_pkg] = pkg

    for dep in ['atlas_state', 'verify_fix']:
        full_dep = f'{sub_pkg}.{dep}'
        if full_dep not in sys.modules:
            dep_path = plugin_dir / f'{dep}.py'
            dep_spec = importlib.util.spec_from_file_location(full_dep, dep_path)
            dep_mod = importlib.util.module_from_spec(dep_spec)
            dep_mod.__package__ = sub_pkg
            sys.modules[full_dep] = dep_mod
            assert dep_spec.loader is not None
            dep_spec.loader.exec_module(dep_mod)

    full = f'{sub_pkg}.{module_name}'
    path = plugin_dir / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = sub_pkg
    sys.modules[full] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module



def _write_state(workspace: Path, state: dict) -> Path:
    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path



def test_verify_acceptance_criteria_returns_verified_when_all_items_match():
    module = _load_module('omh_verify')

    verdict = module._verify_acceptance_criteria(
        {
            'task_slug': 'auth-check',
            'acceptance': [
                'login returns 401 without token',
                'login returns 200 with valid token',
            ],
        },
        {
            'summary': 'verified login returns 401 without token and login returns 200 with valid token',
            'stdout': 'all acceptance items validated',
        },
    )

    assert verdict['status'] == 'VERIFIED'
    assert verdict['missing'] == []
    assert len(verdict['matched']) == 2
    assert verdict['evidence']



def test_verify_acceptance_criteria_returns_partial_when_only_some_items_match():
    module = _load_module('omh_verify')

    verdict = module._verify_acceptance_criteria(
        {
            'task_slug': 'auth-check',
            'acceptance': [
                'login returns 401 without token',
                'login returns 200 with valid token',
            ],
        },
        {
            'summary': 'verified login returns 401 without token only',
        },
    )

    assert verdict['status'] == 'PARTIAL'
    assert verdict['matched'] == ['login returns 401 without token']
    assert verdict['missing'] == ['login returns 200 with valid token']
    assert verdict['evidence']



def test_verify_acceptance_criteria_returns_failed_when_nothing_matches():
    module = _load_module('omh_verify')

    verdict = module._verify_acceptance_criteria(
        {
            'task_slug': 'auth-check',
            'acceptance': [
                'login returns 401 without token',
                'login returns 200 with valid token',
            ],
        },
        {
            'summary': 'updated docs and formatting only',
            'stderr': 'no auth checks executed',
        },
    )

    assert verdict['status'] == 'FAILED'
    assert verdict['matched'] == []
    assert len(verdict['missing']) == 2
    assert verdict['evidence']



def test_record_task_acceptance_verification_updates_task_session_and_escalates_after_repeat_failures():
    module = _load_module('omh_verify')

    state = {
        'status': 'active',
        'current_stage': 'verify',
        'current_wave': 2,
        'task_sessions': {
            'auth-check': {
                'task_slug': 'auth-check',
                'label': 'Auth check',
                'status': 'completed',
                'acceptance': [
                    'login returns 401 without token',
                    'login returns 200 with valid token',
                ],
            }
        },
    }

    first = module.record_task_acceptance_verification(
        state,
        task_slug='auth-check',
        result={'summary': 'verified login returns 401 without token only'},
        now='2026-04-22T06:30:00Z',
    )
    second = module.record_task_acceptance_verification(
        first,
        task_slug='auth-check',
        result={'summary': 'still missing successful login validation'},
        now='2026-04-22T06:31:00Z',
    )

    session = second['task_sessions']['auth-check']
    assert session['verification_status'] == 'FAILED'
    assert session['verification_retry_count'] == 2
    assert session['verification_escalation_required'] is True
    assert session['verification_updated_at'] == '2026-04-22T06:31:00Z'
    assert session['verification_evidence']



def test_build_verify_payload_records_acceptance_verification_metadata_for_target_task():
    module = _load_module('omh_verify')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = {
            'version': 1,
            'active_plan': str(workspace / '.omh' / 'plans' / 'sample.md'),
            'plan_name': 'sample',
            'started_at': '2026-04-22T06:00:00Z',
            'updated_at': '2026-04-22T06:00:00Z',
            'status': 'active',
            'current_stage': 'verify',
            'current_wave': 2,
            'task_sessions': {
                'auth-check': {
                    'task_slug': 'auth-check',
                    'label': 'Auth check',
                    'status': 'completed',
                    'completed_at': '2026-04-22T06:10:00Z',
                    'acceptance': [
                        'login returns 401 without token',
                    ],
                }
            },
        }
        state_path = _write_state(workspace, state)

        payload = module.build_verify_payload('pass verified login returns 401 without token', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        session = updated['task_sessions']['auth-check']

        assert payload['mode'] == 'recorded'
        assert session['verification_status'] == 'VERIFIED'
        assert session['verification_retry_count'] == 0
        assert session['verification_escalation_required'] is False
        assert session['verification_evidence']


def test_build_verify_payload_routes_pass_with_failed_task_acceptance_back_to_fix_stage():
    module = _load_module('omh_verify')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = {
            'version': 1,
            'active_plan': str(workspace / '.omh' / 'plans' / 'sample.md'),
            'plan_name': 'sample',
            'started_at': '2026-04-22T06:00:00Z',
            'updated_at': '2026-04-22T06:00:00Z',
            'status': 'active',
            'current_stage': 'verify',
            'current_wave': 2,
            'lineage': {'total_waves': 2},
            'task_sessions': {
                'auth-check': {
                    'task_slug': 'auth-check',
                    'label': 'Auth check',
                    'status': 'completed',
                    'completed_at': '2026-04-22T06:10:00Z',
                    'acceptance': [
                        'login returns 401 without token',
                    ],
                }
            },
        }
        state_path = _write_state(workspace, state)

        payload = module.build_verify_payload('pass docs only', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        session = updated['task_sessions']['auth-check']

        assert payload['mode'] == 'recorded'
        assert payload['outcome'] == 'fail'
        assert payload['verification_gate']['blocked'] is True
        assert session['verification_status'] == 'FAILED'
        assert updated['status'] == 'active'
        assert updated['current_stage'] == 'fix'
        assert updated['current_wave'] == 3
        assert 'verification_failed_at' in updated


def test_build_verify_payload_routes_pass_with_partial_task_acceptance_back_to_fix_stage():
    module = _load_module('omh_verify')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = {
            'version': 1,
            'active_plan': str(workspace / '.omh' / 'plans' / 'sample.md'),
            'plan_name': 'sample',
            'started_at': '2026-04-22T06:00:00Z',
            'updated_at': '2026-04-22T06:00:00Z',
            'status': 'active',
            'current_stage': 'verify',
            'current_wave': 2,
            'lineage': {'total_waves': 2},
            'task_sessions': {
                'auth-check': {
                    'task_slug': 'auth-check',
                    'label': 'Auth check',
                    'status': 'completed',
                    'completed_at': '2026-04-22T06:10:00Z',
                    'acceptance': [
                        'login returns 401 without token',
                        'login returns 200 with valid token',
                    ],
                }
            },
        }
        state_path = _write_state(workspace, state)

        payload = module.build_verify_payload('pass login returns 401 without token', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        session = updated['task_sessions']['auth-check']

        assert payload['mode'] == 'recorded'
        assert payload['outcome'] == 'fail'
        assert payload['verification_gate']['blocked'] is True
        assert session['verification_status'] == 'PARTIAL'
        assert updated['status'] == 'active'
        assert updated['current_stage'] == 'fix'
