from __future__ import annotations

import asyncio
import importlib.util
import os
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

    for dep in [
        'task_sessions',
        'worker_orchestration',
        'atlas_state',
        'verify_fix',
        'omh_fix',
        'omh_verify',
    ]:
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



def test_compute_waves_topologically_sorts_lineage_dag():
    module = _load_module('omh_exec')

    waves = module._compute_waves(
        {
            'T0': {'blockedBy': []},
            'T1': {'blockedBy': ['T0']},
            'T2': {'blockedBy': ['T0']},
            'T3': {'blockedBy': ['T1', 'T2']},
        }
    )

    assert waves == [['T0'], ['T1', 'T2'], ['T3']]



def test_compute_waves_falls_back_to_single_wave_when_lineage_is_missing():
    module = _load_module('omh_exec')

    waves = module._compute_waves(
        {
            'T1': {'label': 'first task'},
            'T2': {'label': 'second task'},
            'T3': {'label': 'third task'},
        }
    )

    assert waves == [['T1', 'T2', 'T3']]



def test_run_wave_uses_configured_parallelism(monkeypatch):
    module = _load_module('omh_exec')
    active = 0
    max_seen = 0
    seen: list[str] = []

    async def fake_runner(task_slug: str):
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        seen.append(task_slug)
        await asyncio.sleep(0.01)
        active -= 1
        return {'task_slug': task_slug, 'status': 'completed'}

    monkeypatch.setenv('OMH_MAX_PARALLEL_TASKS', '2')
    result = asyncio.run(module._run_wave(['T1', 'T2', 'T3', 'T4'], fake_runner))

    assert [item['task_slug'] for item in result['results']] == ['T1', 'T2', 'T3', 'T4']
    assert max_seen == 2
    assert sorted(seen) == ['T1', 'T2', 'T3', 'T4']
    assert result['failed_tasks'] == []



def test_run_wave_stops_scheduling_after_failure_when_fail_fast_is_enabled(monkeypatch):
    module = _load_module('omh_exec')
    seen: list[str] = []

    async def fake_runner(task_slug: str):
        seen.append(task_slug)
        if task_slug == 'T2':
            return {'task_slug': task_slug, 'status': 'failed', 'error': 'boom'}
        return {'task_slug': task_slug, 'status': 'completed'}

    monkeypatch.setenv('OMH_MAX_PARALLEL_TASKS', '1')
    result = asyncio.run(module._run_wave(['T1', 'T2', 'T3'], fake_runner, fail_fast=True))

    assert seen == ['T1', 'T2']
    assert result['failed_tasks'] == ['T2']
    assert result['stopped_early'] is True



def test_apply_wave_results_updates_state_atomically_and_promotes_next_ready_wave():
    module = _load_module('omh_exec')

    state = {
        'status': 'active',
        'current_stage': 'exec',
        'current_wave': 1,
        'task_sessions': {
            'T0': {'task_slug': 'T0', 'status': 'in_progress', 'wave': 1, 'blockedBy': []},
            'T1': {'task_slug': 'T1', 'status': 'pending', 'wave': 2, 'blockedBy': ['T0']},
            'T2': {'task_slug': 'T2', 'status': 'pending', 'wave': 2, 'blockedBy': ['T0']},
            'T3': {'task_slug': 'T3', 'status': 'pending', 'wave': 3, 'blockedBy': ['T1', 'T2']},
        },
        'lineage': {
            'waves': [['T0'], ['T1', 'T2'], ['T3']],
            'total_waves': 3,
        },
    }

    next_state = module._apply_wave_results(
        state,
        [
            {'task_slug': 'T0', 'status': 'completed'},
        ],
        now='2026-04-22T07:00:00Z',
    )

    assert next_state['task_sessions']['T0']['status'] == 'completed'
    assert next_state['task_sessions']['T1']['status'] == 'in_progress'
    assert next_state['task_sessions']['T2']['status'] == 'in_progress'
    assert next_state['task_sessions']['T3']['status'] == 'pending'
    assert next_state['current_wave'] == 2
    assert next_state['current_stage'] == 'exec'



def test_apply_wave_results_blocks_execution_when_wave_fails_with_fail_fast():
    module = _load_module('omh_exec')

    state = {
        'status': 'active',
        'current_stage': 'exec',
        'current_wave': 2,
        'task_sessions': {
            'T1': {'task_slug': 'T1', 'status': 'in_progress', 'wave': 2, 'blockedBy': ['T0']},
            'T2': {'task_slug': 'T2', 'status': 'in_progress', 'wave': 2, 'blockedBy': ['T0']},
            'T3': {'task_slug': 'T3', 'status': 'pending', 'wave': 3, 'blockedBy': ['T1', 'T2']},
        },
        'lineage': {
            'waves': [['T0'], ['T1', 'T2'], ['T3']],
            'total_waves': 3,
        },
    }

    next_state = module._apply_wave_results(
        state,
        [
            {'task_slug': 'T1', 'status': 'completed'},
            {'task_slug': 'T2', 'status': 'failed', 'error': 'boom'},
        ],
        now='2026-04-22T07:05:00Z',
        fail_fast=True,
    )

    assert next_state['task_sessions']['T1']['status'] == 'completed'
    assert next_state['task_sessions']['T2']['status'] == 'blocked'
    assert next_state['task_sessions']['T3']['status'] == 'pending'
    assert next_state['status'] == 'blocked'
    assert next_state['current_stage'] == 'exec'
