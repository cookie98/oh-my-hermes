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

    for dep in ['atlas_state']:
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


def test_handle_omh_start_work_returns_usage_on_empty_args_when_no_plan_can_be_inferred():
    module = _load_module('omh_start_work')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_start_work_command('', workspace=workspace)
        assert 'No canonical OMH plan found for this request.' in result
        assert 'Run `omh-plan` first, then retry `omh-start-work`.' in result


def test_handle_omh_start_work_still_refuses_when_only_a_draft_exists():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_start_work')
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_draft_plan_payload('add auth middleware', workspace=workspace)

        result = module.handle_omh_start_work_command('', workspace=workspace)

        assert 'No canonical OMH plan found for this request.' in result
        assert 'Run `omh-plan` first, then retry `omh-start-work`.' in result


def test_handle_omh_start_work_bootstraps_after_draft_is_finalized():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_draft_plan_payload('add auth middleware', workspace=workspace)
        plan_module.finalize_draft_plan_payload('add-auth-middleware', workspace=workspace)

        payload = start_module.build_start_work_payload('', workspace=workspace)

        assert payload['mode'] == 'fresh-start'
        assert payload['plan']['name'] == 'add-auth-middleware'


def test_handle_omh_start_work_bootstraps_state_from_single_canonical_plan():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        payload = start_module.build_start_work_payload('', workspace=workspace)

        assert payload['mode'] == 'fresh-start'
        assert payload['plan']['name'] == 'add-auth-middleware'
        state_path = Path(payload['state_path'])
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding='utf-8'))
        assert state['plan_name'] == 'add-auth-middleware'
        assert state['status'] == 'active'
        assert state['current_stage'] == 'exec'
        assert state['current_wave'] == 1
        assert state['worktree_path'] is None
        task_sessions = state['task_sessions']
        first_task_key = 'T1' if 'T1' in task_sessions else list(task_sessions.keys())[0]
        second_task_key = 'T2' if 'T2' in task_sessions else list(task_sessions.keys())[1]
        if 'T1' in task_sessions:
            assert {'T1', 'T2'} <= set(task_sessions.keys())
        else:
            assert len(task_sessions) >= 3
        first_task = task_sessions[first_task_key]
        assert first_task['status'] == 'in_progress'
        assert first_task['wave'] == 1
        assert first_task['started_at'] == state['started_at']
        assert state['worker_orchestration'] == {
            'active_worker_id': None,
            'current_task_slug': None,
            'mode': 'idle',
            'backend': 'hermes-native',
            'worker_sessions': {},
        }


def test_handle_omh_start_work_resumes_matching_active_state():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

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

        payload = start_module.build_start_work_payload('', workspace=workspace)
        assert payload['mode'] == 'resume'
        assert payload['plan']['name'] == 'add-auth-middleware'
        assert payload['state']['current_stage'] == 'exec'
        assert payload['state']['current_wave'] == 2
