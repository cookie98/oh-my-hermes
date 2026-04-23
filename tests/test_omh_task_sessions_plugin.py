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

    for dep in ['atlas_state', 'omh_plan', 'omh_start_work', 'omh_status', 'task_sessions']:
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


def test_transition_task_session_completes_current_and_activates_next_pending_task():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    task_module = _load_module('task_sessions')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        payload = start_module.build_start_work_payload('', workspace=workspace)
        state = payload['state']

        first_slug, second_slug = list(state['task_sessions'].keys())[:2]
        next_state = task_module.transition_task_session(
            state,
            task_slug=first_slug,
            next_status='completed',
            now='2026-04-19T15:00:00Z',
        )

        assert next_state['task_sessions'][first_slug]['status'] == 'completed'
        assert next_state['task_sessions'][first_slug]['completed_at'] == '2026-04-19T15:00:00Z'
        assert next_state['task_sessions'][second_slug]['status'] == 'in_progress'
        # Wave is now lineage-aware; second task may be in same or next wave
        assert next_state['task_sessions'][second_slug]['wave'] >= 1
        assert next_state['task_sessions'][second_slug]['started_at'] == '2026-04-19T15:00:00Z'
        assert next_state['current_stage'] == 'exec'
        # current_wave advances only when all tasks in current wave are done
        assert next_state['current_wave'] >= 1
        assert next_state['status'] == 'active'
        assert next_state['updated_at'] == '2026-04-19T15:00:00Z'


def test_transition_task_session_moves_exec_to_verify_after_last_task_completion():
    task_module = _load_module('task_sessions')

    state = {
        'status': 'active',
        'current_stage': 'exec',
        'current_wave': 1,
        'updated_at': '2026-04-19T14:59:00Z',
        'task_sessions': {
            'only-task': {
                'task_slug': 'only-task',
                'label': 'Only task',
                'status': 'in_progress',
                'wave': 1,
                'started_at': '2026-04-19T14:55:00Z',
            }
        },
    }

    next_state = task_module.transition_task_session(
        state,
        task_slug='only-task',
        next_status='completed',
        now='2026-04-19T15:00:00Z',
    )

    assert next_state['task_sessions']['only-task']['status'] == 'completed'
    assert next_state['current_stage'] == 'verify'
    assert next_state['current_wave'] == 1
    assert next_state['status'] == 'active'


def test_build_status_payload_reports_current_task_and_task_status_counts():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        start_payload = start_module.build_start_work_payload('', workspace=workspace)
        state = start_payload['state']
        payload = status_module.build_status_payload(workspace=workspace)

        assert payload['task_sessions']['count'] == 22
        assert payload['task_sessions']['by_status']['in_progress'] == 1
        assert payload['task_sessions']['by_status']['pending'] == 21
        expected_current_slug = list(state['task_sessions'].keys())[0]
        assert payload['task_sessions']['current_task_slug'] == expected_current_slug
        assert payload['active_task_slugs'][0] == expected_current_slug
