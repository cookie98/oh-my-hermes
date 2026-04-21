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

    for dep in ['task_sessions', 'worker_orchestration', 'atlas_state', 'omh_plan', 'omh_start_work']:
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


def _write_running_detached_state(workspace: Path) -> Path:
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    plan_module.build_plan_payload('add auth middleware', workspace=workspace)
    state = start_module.build_start_work_payload('', workspace=workspace)['state']
    state['worker_orchestration'] = {
        **state['worker_orchestration'],
        'active_worker_id': 'worker-live',
        'current_task_slug': 'implement-auth',
        'mode': 'running',
        'worker_sessions': {
            'worker-live': {
                'worker_id': 'worker-live',
                'task_slug': 'implement-auth',
                'status': 'running',
                'mode': 'running',
                'updated_at': '2026-04-20T00:05:00Z',
                'supervision': {
                    'detached': True,
                    'session_id': 'proc-123',
                    'status': 'running',
                    'command': 'codex exec worker lane',
                    'attached_at': '2026-04-20T00:05:00Z',
                    'last_polled_at': '2026-04-20T00:05:00Z',
                },
            }
        },
    }
    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def test_refresh_detached_worker_supervision_persists_completed_poll_result():
    refresh_module = _load_module('supervision_refresh')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_running_detached_state(workspace)

        refreshed = refresh_module.refresh_detached_worker_supervision(
            workspace,
            process_poller=lambda session_id: {
                'status': 'completed',
                'observation': 'process exited cleanly',
                'exit_code': 0,
            },
        )
        stored = json.loads(state_path.read_text(encoding='utf-8'))
        session = stored['worker_orchestration']['worker_sessions']['worker-live']

        assert refreshed.state is not None
        assert refreshed.state['worker_orchestration']['mode'] == 'awaiting-worker-result'
        assert session['supervision']['status'] == 'completed'
        assert session['supervision']['last_exit_code'] == 0
        assert session['supervision']['last_observation'] == 'process exited cleanly'


def test_refresh_detached_worker_supervision_is_noop_without_running_detached_session():
    refresh_module = _load_module('supervision_refresh')
    atlas_state = _load_module('atlas_state')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_running_detached_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration']['worker_sessions']['worker-live']['supervision']['status'] = 'completed'
        raw_state['worker_orchestration']['worker_sessions']['worker-live']['mode'] = 'awaiting-worker-result'
        raw_state['worker_orchestration']['mode'] = 'awaiting-worker-result'
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')

        original_snapshot = atlas_state.read_atlas_state(workspace=workspace)
        refreshed = refresh_module.refresh_detached_worker_supervision(
            workspace,
            process_poller=lambda session_id: {'status': 'failed', 'observation': 'should not run'},
        )

        assert refreshed.state == original_snapshot.state



def test_refresh_detached_worker_supervision_polls_via_runtime_handle_when_supervision_session_id_is_missing():
    refresh_module = _load_module('supervision_refresh')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_running_detached_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration']['worker_sessions']['worker-live']['runtime_handle'] = 'codex-proc-9'
        raw_state['worker_orchestration']['worker_sessions']['worker-live']['supervision']['session_id'] = None
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')

        poll_calls: list[str] = []

        refreshed = refresh_module.refresh_detached_worker_supervision(
            workspace,
            process_poller=lambda session_id: poll_calls.append(session_id) or {
                'status': 'completed',
                'observation': 'process exited cleanly',
                'exit_code': 0,
            },
        )
        stored = json.loads(state_path.read_text(encoding='utf-8'))
        session = stored['worker_orchestration']['worker_sessions']['worker-live']

        assert poll_calls == ['codex-proc-9']
        assert refreshed.state is not None
        assert refreshed.state['worker_orchestration']['mode'] == 'awaiting-worker-result'
        assert session['supervision']['status'] == 'completed'
