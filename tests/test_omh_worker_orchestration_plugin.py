from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


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

    for dep in ['task_sessions', 'worker_orchestration', 'atlas_state']:
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


def test_normalize_worker_orchestration_applies_defaults_and_clamps_invalid_statuses():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'active_worker_id': 'worker-1',
            'current_task_slug': 'task-1',
            'mode': 'running',
            'backend': 'custom-backend',
            'worker_sessions': {
                'worker-a': {'status': 'bogus', 'notes': 'keep-me'},
                'worker-b': {'status': 'dispatch_ready', 'worker_id': 'worker-b'},
                'worker-c': 'not-a-dict',
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-1'
    assert normalized['current_task_slug'] == 'task-1'
    assert normalized['mode'] == 'running'
    assert normalized['backend'] == 'custom-backend'
    assert normalized['worker_sessions']['worker-a']['status'] == 'dispatch_ready'
    assert normalized['worker_sessions']['worker-a']['notes'] == 'keep-me'
    assert normalized['worker_sessions']['worker-b']['status'] == 'dispatch_ready'
    assert normalized['worker_sessions']['worker-c']['status'] == 'dispatch_ready'


def test_record_worker_result_rejects_unknown_outcomes():
    orchestration_module = _load_module('worker_orchestration')

    state = {
        'worker_orchestration': orchestration_module.normalize_worker_orchestration(
            {
                'active_worker_id': 'worker-x',
                'current_task_slug': 'task-x',
                'worker_sessions': {
                    'worker-x': {'worker_id': 'worker-x', 'status': 'dispatching'},
                },
            }
        )
    }

    with pytest.raises(ValueError, match='Unknown worker outcome'):
        orchestration_module.record_worker_result(state, outcome='paused', summary='unexpected state')


def test_normalize_state_applies_worker_orchestration_normalization():
    atlas_state_module = _load_module('atlas_state')

    normalized = atlas_state_module._normalize_state(
        {
            'session_ids': [],
            'session_origins': {},
            'task_sessions': {},
            'worker_orchestration': {
                'mode': 'dispatch',
                'worker_sessions': {
                    'worker-z': {'status': 'unknown'},
                },
            },
        }
    )

    orchestration = normalized['worker_orchestration']
    assert orchestration['active_worker_id'] is None
    assert orchestration['current_task_slug'] is None
    assert orchestration['mode'] == 'dispatch'
    assert orchestration['backend'] == 'hermes-native'
    assert orchestration['worker_sessions']['worker-z']['status'] == 'dispatch_ready'


def test_normalize_worker_orchestration_preserves_duplicate_worker_ids():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'worker_sessions': {
                'session-a': {'worker_id': 'worker-x', 'status': 'active', 'notes': 'first'},
                'session-b': {'worker_id': 'worker-x', 'status': 'blocked', 'notes': 'second'},
            }
        }
    )

    worker_sessions = normalized['worker_sessions']
    assert list(worker_sessions) == ['worker-x', 'worker-x-2']
    assert worker_sessions['worker-x']['notes'] == 'first'
    assert worker_sessions['worker-x']['status'] == 'active'
    assert worker_sessions['worker-x-2']['notes'] == 'second'
    assert worker_sessions['worker-x-2']['status'] == 'blocked'
