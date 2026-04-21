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

    for dep in ['task_sessions', 'worker_orchestration', 'atlas_state', 'omh_plan', 'omh_start_work', 'omh_status']:
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


def test_build_status_payload_includes_worker_orchestration_summary():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state['worker_orchestration'] = {
            **state['worker_orchestration'],
            'mode': 'dispatching',
            'active_worker_id': 'worker-confirm-scope-and-acceptance-criteria-for-add-auth-middleware-wave-1',
            'current_task_slug': 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware',
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)

        assert payload['worker_orchestration'] == {
            'mode': 'dispatching',
            'active_worker_id': 'worker-confirm-scope-and-acceptance-criteria-for-add-auth-middleware-wave-1',
            'current_task_slug': 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware',
        }


def test_render_status_text_surfaces_worker_orchestration_and_waiting_result():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state['worker_orchestration'] = {
            **state['worker_orchestration'],
            'mode': 'dispatching',
            'active_worker_id': 'worker-confirm-scope-and-acceptance-criteria-for-add-auth-middleware-wave-1',
            'current_task_slug': 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware',
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert 'Worker Orchestration: mode=dispatching, active_worker_id=worker-confirm-scope-and-acceptance-criteria-for-add-auth-middleware-wave-1, current_task_slug=confirm-scope-and-acceptance-criteria-for-add-auth-middleware' in text
        assert 'Awaiting worker result.' in text
        assert 'Execution is in progress.' not in text


def test_build_status_payload_includes_worker_reattachment_summary_when_worker_is_recovered():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state['worker_orchestration'] = {
            **state['worker_orchestration'],
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'implement-auth',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:05:00Z',
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)

        assert payload['worker_orchestration'] == {
            'mode': 'dispatching',
            'active_worker_id': 'worker-live',
            'current_task_slug': 'implement-auth',
        }
        assert payload['worker_reattachment'] == {
            'active_worker_id': 'worker-live',
            'current_task_slug': 'implement-auth',
            'status': 'dispatching',
        }


def test_render_status_text_mentions_recovered_worker_context():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state['worker_orchestration'] = {
            **state['worker_orchestration'],
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'implement-auth',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:05:00Z',
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert 'Worker Reattachment: worker-live (dispatching)' in text
        assert 'Awaiting worker result.' in text



def test_build_status_payload_includes_worker_supervision_summary_for_detached_session():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
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
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)

        assert payload['worker_supervision'] == {
            'session_id': 'proc-123',
            'status': 'running',
            'detached': True,
            'last_exit_code': None,
            'last_observation': None,
        }



def test_render_status_text_mentions_running_detached_worker_session():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
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
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert 'Worker Supervision: detached session proc-123 (running)' in text
        assert 'Detached worker session is still running.' in text
        assert 'Awaiting worker result.' not in text


def test_build_status_payload_auto_polls_running_detached_worker_when_process_poller_is_available():
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
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
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(
            workspace=workspace,
            process_poller=lambda session_id: {'status': 'completed', 'observation': 'process exited cleanly', 'exit_code': 0},
        )

        assert payload['worker_supervision']['status'] == 'completed'
        assert payload['worker_orchestration']['mode'] == 'awaiting-worker-result'


def test_render_status_text_mentions_exact_next_action_for_verify_gate():
    plan_module = _load_module('omh_plan')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'active',
            'current_stage': 'verify',
            'current_wave': 3,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'completed'}},
            'worker_orchestration': {},
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert 'Continuation Enforcement: strict' in text
        assert 'Next Action: Run `omh-verify <pass|fail> [summary...]`' in text



def test_render_status_text_surfaces_worker_result_bridge_summary():
    plan_module = _load_module('omh_plan')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = _load_module('omh_start_work').build_start_work_payload('', workspace=workspace)['state']
        state['worker_orchestration'] = {
            **state['worker_orchestration'],
            'active_worker_id': 'worker-live',
            'current_task_slug': 'implement-auth',
            'mode': 'awaiting-worker-result',
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'implement-auth',
                    'status': 'running',
                    'mode': 'awaiting-worker-result',
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'completed',
                        'last_exit_code': 0,
                        'last_observation': 'process exited cleanly',
                    },
                }
            },
        }
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert 'Worker Result Bridge: ready (recommended=complete)' in text
        assert 'Suggested Command: omh-exec accept' in text



def test_render_status_text_mentions_idle_escalation_when_active():
    plan_module = _load_module('omh_plan')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-04-20T00:00:00Z',
            'updated_at': '2026-04-20T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'worker_orchestration': {},
            'continuation_enforcement': {
                'idle': {
                    'last_nudged_at': '2026-04-20T03:00:00Z',
                    'nudge_count': 2,
                }
            },
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace, now='2026-04-20T04:00:00Z')
        text = status_module.render_status_text(payload)

        assert 'Idle Escalation: active' in text



def test_render_status_text_mentions_idle_continuation_when_due():
    plan_module = _load_module('omh_plan')
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-04-20T00:00:00Z',
            'updated_at': '2026-04-20T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'worker_orchestration': {},
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        payload = status_module.build_status_payload(workspace=workspace, now='2026-04-20T02:00:00Z')
        text = status_module.render_status_text(payload)

        assert 'Idle Continuation: due' in text
        assert 'Idle Age: 120m' in text
