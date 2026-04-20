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

    for dep in ['atlas_state', 'omh_plan']:
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


def test_handle_omh_resume_command_rejects_unexpected_args():
    module = _load_module('omh_resume')
    result = module.handle_omh_resume_command('extra args')
    assert result == 'Usage: `/omh-resume`'


def test_handle_omh_resume_command_fails_when_state_missing():
    module = _load_module('omh_resume')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_resume_command('', workspace=workspace)
        assert 'No resumable OMH execution state was found.' in result
        assert 'Run `omh-start-work` to begin work from a canonical OMH plan.' in result


def test_handle_omh_resume_command_fails_when_state_complete():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_resume')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'complete',
            'current_stage': 'verify',
            'current_wave': 3,
            'session_ids': [],
            'session_origins': {},
            'worktree_path': None,
            'task_sessions': {},
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')
        result = module.handle_omh_resume_command('', workspace=workspace)
        assert 'The last OMH execution is not resumable (status: complete).' in result
        assert 'Use `omh-start-work` to begin a new execution session.' in result


def test_handle_omh_resume_command_resumes_active_state():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_resume')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')
        payload = module.build_resume_payload('', workspace=workspace)
        assert payload['mode'] == 'resume'
        assert payload['plan']['name'] == 'add-auth-middleware'
        assert payload['state']['current_stage'] == 'exec'
        assert payload['state']['current_wave'] == 2
        assert payload['active_task_slugs'] == ['auth-middleware']


def test_handle_omh_resume_command_mentions_recovered_worker_context():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_resume')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'worker_orchestration': {
                'worker_sessions': {
                    'worker-live': {
                        'worker_id': 'worker-live',
                        'task_slug': 'implement-auth',
                        'status': 'dispatching',
                        'updated_at': '2026-04-20T00:05:00Z',
                    }
                }
            },
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        result = module.handle_omh_resume_command('', workspace=workspace)

        assert 'Worker Reattachment: worker-live' in result
        assert 'Worker Status: dispatching' in result



def test_render_resume_text_mentions_detached_worker_supervision():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_resume')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'worker_orchestration': {
                'active_worker_id': 'worker-live',
                'current_task_slug': 'implement-auth',
                'mode': 'running',
                'worker_sessions': {
                    'worker-live': {
                        'worker_id': 'worker-live',
                        'task_slug': 'implement-auth',
                        'status': 'running',
                        'updated_at': '2026-04-20T00:05:00Z',
                        'supervision': {
                            'detached': True,
                            'session_id': 'proc-123',
                            'status': 'running'
                        }
                    }
                }
            },
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        result = module.handle_omh_resume_command('', workspace=workspace)

        assert 'Detached Worker Session: proc-123' in result
        assert 'Detached Worker Status: running' in result
