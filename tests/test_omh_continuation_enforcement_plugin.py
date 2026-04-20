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


def _write_state(workspace: Path, state: dict) -> Path:
    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def _write_plan(workspace: Path) -> Path:
    plan_path = workspace / '.omh' / 'plans' / 'demo-plan.md'
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text('- [ ] task one\n', encoding='utf-8')
    return plan_path


def test_build_continuation_enforcement_returns_verify_gate_with_exact_next_action():
    atlas_state = _load_module('atlas_state')
    enforcement_module = _load_module('continuation_enforcement')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_path = _write_plan(workspace)
        _write_state(
            workspace,
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'verify',
                'current_wave': 3,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'task_sessions': {
                    'task-one': {'task_slug': 'task-one', 'status': 'completed'}
                },
                'worker_orchestration': {},
                'last_handoff': None,
            },
        )

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        decision = enforcement_module.build_continuation_enforcement(snapshot)

        assert decision.strict is True
        assert decision.route == 'omh-exec'
        assert decision.next_action == 'Run `omh-verify <pass|fail> [summary...]` to resolve the current verify stage before starting unrelated work.'


def test_build_continuation_enforcement_returns_status_gate_for_running_detached_worker():
    atlas_state = _load_module('atlas_state')
    enforcement_module = _load_module('continuation_enforcement')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_path = _write_plan(workspace)
        _write_state(
            workspace,
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'exec',
                'current_wave': 2,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'task_sessions': {
                    'task-one': {'task_slug': 'task-one', 'status': 'in_progress'}
                },
                'worker_orchestration': {
                    'active_worker_id': 'worker-live',
                    'current_task_slug': 'task-one',
                    'mode': 'running',
                    'worker_sessions': {
                        'worker-live': {
                            'worker_id': 'worker-live',
                            'task_slug': 'task-one',
                            'status': 'running',
                            'mode': 'running',
                            'updated_at': '2026-04-20T00:05:00Z',
                            'supervision': {
                                'detached': True,
                                'session_id': 'proc-123',
                                'status': 'running',
                            },
                        }
                    },
                },
                'last_handoff': None,
            },
        )

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        decision = enforcement_module.build_continuation_enforcement(snapshot)

        assert decision.strict is True
        assert decision.route == 'omh-status'
        assert 'Detached worker session is still running' in decision.next_action


def test_build_idle_continuation_pressure_marks_soft_resumable_state_due_after_threshold():
    atlas_state = _load_module('atlas_state')
    enforcement_module = _load_module('continuation_enforcement')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_path = _write_plan(workspace)
        _write_state(
            workspace,
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'exec',
                'current_wave': 2,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'task_sessions': {
                    'task-one': {'task_slug': 'task-one', 'status': 'in_progress'}
                },
                'worker_orchestration': {},
                'last_handoff': None,
            },
        )

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T02:00:00Z')

        assert decision.active is True
        assert decision.due is True
        assert decision.level == 'soft'
        assert decision.idle_minutes == 120
        assert decision.threshold_minutes == 60
        assert decision.cooldown_active is False


def test_build_idle_continuation_pressure_uses_shorter_threshold_for_strict_state():
    atlas_state = _load_module('atlas_state')
    enforcement_module = _load_module('continuation_enforcement')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_path = _write_plan(workspace)
        _write_state(
            workspace,
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'verify',
                'current_wave': 2,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'task_sessions': {
                    'task-one': {'task_slug': 'task-one', 'status': 'completed'}
                },
                'worker_orchestration': {},
                'last_handoff': None,
            },
        )

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T00:20:00Z')

        assert decision.active is True
        assert decision.due is True
        assert decision.level == 'strict'
        assert decision.threshold_minutes == 15



def test_build_idle_continuation_pressure_respects_recent_nudge_cooldown():
    atlas_state = _load_module('atlas_state')
    enforcement_module = _load_module('continuation_enforcement')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_path = _write_plan(workspace)
        _write_state(
            workspace,
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'exec',
                'current_wave': 2,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'task_sessions': {
                    'task-one': {'task_slug': 'task-one', 'status': 'in_progress'}
                },
                'worker_orchestration': {},
                'continuation_enforcement': {
                    'idle': {
                        'last_nudged_at': '2026-04-20T01:50:00Z',
                        'nudge_count': 1,
                    }
                },
                'last_handoff': None,
            },
        )

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T02:00:00Z')

        assert decision.active is True
        assert decision.due is False
        assert decision.cooldown_active is True
        assert decision.cooldown_remaining_minutes == 20
