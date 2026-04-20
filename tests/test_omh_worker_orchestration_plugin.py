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


def test_normalize_worker_orchestration_infers_active_worker_from_latest_nonterminal_session():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'mode': 'idle',
            'worker_sessions': {
                'worker-old': {
                    'worker_id': 'worker-old',
                    'task_slug': 'scope',
                    'status': 'completed',
                    'updated_at': '2026-04-20T00:00:00Z',
                },
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'implement',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:05:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-live'
    assert normalized['current_task_slug'] == 'implement'
    assert normalized['mode'] == 'dispatching'


def test_normalize_worker_orchestration_repairs_stale_active_worker_reference_from_live_session():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'active_worker_id': 'missing-worker',
            'current_task_slug': 'old-task',
            'mode': 'dispatching',
            'worker_sessions': {
                'worker-ready': {
                    'worker_id': 'worker-ready',
                    'task_slug': 'confirm-scope',
                    'status': 'running',
                    'updated_at': '2026-04-20T00:06:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-ready'
    assert normalized['current_task_slug'] == 'confirm-scope'
    assert normalized['mode'] == 'running'



def test_normalize_worker_orchestration_clears_terminal_active_worker_when_no_live_session_remains():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'active_worker_id': 'worker-done',
            'current_task_slug': 'old-task',
            'mode': 'running',
            'worker_sessions': {
                'worker-done': {
                    'worker_id': 'worker-done',
                    'task_slug': 'old-task',
                    'status': 'completed',
                    'updated_at': '2026-04-20T00:06:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] is None
    assert normalized['current_task_slug'] is None
    assert normalized['mode'] == 'idle'



def test_normalize_worker_orchestration_prefers_latest_live_session_with_dispatched_at_fallback():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'worker_sessions': {
                'worker-older': {
                    'worker_id': 'worker-older',
                    'task_slug': 'old-task',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:04:00Z',
                },
                'worker-newer': {
                    'worker_id': 'worker-newer',
                    'task_slug': 'new-task',
                    'status': 'running',
                    'dispatched_at': '2026-04-20T00:06:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-newer'
    assert normalized['current_task_slug'] == 'new-task'
    assert normalized['mode'] == 'running'



def test_dispatch_exec_worker_seeds_detached_supervision_metadata(tmp_path):
    orchestration_module = _load_module('worker_orchestration')

    state = {
        'current_wave': 1,
        'task_sessions': {
            'task-a': {
                'task_slug': 'task-a',
                'status': 'in_progress',
            }
        },
        'worker_orchestration': orchestration_module.normalize_worker_orchestration({}),
    }

    next_state = orchestration_module.dispatch_exec_worker(state, tmp_path, task_slug='task-a', summary='draft handoff')
    worker_id = next_state['worker_orchestration']['active_worker_id']
    session = next_state['worker_orchestration']['worker_sessions'][worker_id]

    assert session['supervision'] == {
        'detached': False,
        'session_id': None,
        'status': 'untracked',
        'command': None,
        'attached_at': None,
        'last_polled_at': None,
        'last_exit_code': None,
        'last_observation': None,
    }



def test_attach_worker_supervision_marks_active_worker_as_detached_running():
    orchestration_module = _load_module('worker_orchestration')

    state = {
        'worker_orchestration': orchestration_module.normalize_worker_orchestration(
            {
                'active_worker_id': 'worker-a',
                'current_task_slug': 'task-a',
                'mode': 'dispatching',
                'worker_sessions': {
                    'worker-a': {
                        'worker_id': 'worker-a',
                        'task_slug': 'task-a',
                        'status': 'dispatching',
                    }
                },
            }
        )
    }

    next_state = orchestration_module.attach_worker_supervision(state, session_id='proc-123', command='codex exec ...')
    session = next_state['worker_orchestration']['worker_sessions']['worker-a']

    assert session['supervision']['detached'] is True
    assert session['supervision']['session_id'] == 'proc-123'
    assert session['supervision']['status'] == 'running'
    assert session['supervision']['command'] == 'codex exec ...'
    assert next_state['worker_orchestration']['mode'] == 'running'



def test_record_worker_supervision_poll_tracks_terminal_background_state_without_consuming_task_result():
    orchestration_module = _load_module('worker_orchestration')

    state = {
        'worker_orchestration': orchestration_module.normalize_worker_orchestration(
            {
                'active_worker_id': 'worker-a',
                'current_task_slug': 'task-a',
                'mode': 'running',
                'worker_sessions': {
                    'worker-a': {
                        'worker_id': 'worker-a',
                        'task_slug': 'task-a',
                        'status': 'running',
                        'supervision': {
                            'detached': True,
                            'session_id': 'proc-123',
                            'status': 'running',
                            'command': 'codex exec ...',
                        },
                    }
                },
            }
        )
    }

    next_state = orchestration_module.record_worker_supervision_poll(
        state,
        session_id='proc-123',
        status='completed',
        observation='process exited cleanly',
        exit_code=0,
    )
    session = next_state['worker_orchestration']['worker_sessions']['worker-a']
    normalized = orchestration_module.normalize_worker_orchestration(next_state['worker_orchestration'])

    assert session['supervision']['status'] == 'completed'
    assert session['supervision']['last_exit_code'] == 0
    assert session['supervision']['last_observation'] == 'process exited cleanly'
    assert next_state['worker_orchestration']['active_worker_id'] == 'worker-a'
    assert next_state['worker_orchestration']['mode'] == 'awaiting-worker-result'
    assert normalized['active_worker_id'] == 'worker-a'
    assert normalized['mode'] == 'awaiting-worker-result'



def test_build_worker_result_bridge_recommends_complete_for_clean_completed_detached_worker():
    orchestration_module = _load_module('worker_orchestration')

    bridge = orchestration_module.build_worker_result_bridge(
        {
            'active_worker_id': 'worker-a',
            'current_task_slug': 'task-a',
            'mode': 'awaiting-worker-result',
            'worker_sessions': {
                'worker-a': {
                    'worker_id': 'worker-a',
                    'task_slug': 'task-a',
                    'status': 'running',
                    'mode': 'awaiting-worker-result',
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
    )

    assert bridge is not None
    assert bridge['ready'] is True
    assert bridge['recommended_action'] == 'complete'
    assert bridge['summary'] == 'process exited cleanly'
    assert bridge['session_id'] == 'proc-123'



def test_build_worker_result_bridge_recommends_block_for_failed_detached_worker():
    orchestration_module = _load_module('worker_orchestration')

    bridge = orchestration_module.build_worker_result_bridge(
        {
            'active_worker_id': 'worker-a',
            'current_task_slug': 'task-a',
            'mode': 'awaiting-worker-result',
            'worker_sessions': {
                'worker-a': {
                    'worker_id': 'worker-a',
                    'task_slug': 'task-a',
                    'status': 'running',
                    'mode': 'awaiting-worker-result',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'failed',
                        'last_exit_code': 2,
                    },
                }
            },
        }
    )

    assert bridge is not None
    assert bridge['ready'] is True
    assert bridge['recommended_action'] == 'block'
    assert 'exit code 2' in bridge['summary']



def test_record_worker_supervision_poll_rejects_stale_session_after_active_worker_clears():
    orchestration_module = _load_module('worker_orchestration')

    state = {
        'worker_orchestration': orchestration_module.normalize_worker_orchestration(
            {
                'worker_sessions': {
                    'worker-a': {
                        'worker_id': 'worker-a',
                        'task_slug': 'task-a',
                        'status': 'completed',
                        'supervision': {
                            'detached': True,
                            'session_id': 'proc-123',
                            'status': 'completed',
                        },
                    }
                },
            }
        )
    }

    with pytest.raises(ValueError, match='No active detached OMH worker matched session id'):
        orchestration_module.record_worker_supervision_poll(
            state,
            session_id='proc-123',
            status='running',
            observation='late poll should not mutate state',
        )
