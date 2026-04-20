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

    for dep in [
        'task_sessions',
        'atlas_state',
        'verify_fix',
        'omh_plan',
        'omh_start_work',
        'omh_resume',
        'omh_status',
        'omh_verify',
        'omh_fix',
        'omh_exec',
        'intent_gate',
        'route_resolver',
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


def _write_state(workspace: Path, state: dict) -> Path:
    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def _seed_exec_state(workspace: Path) -> dict:
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    plan_module.build_plan_payload('add auth middleware', workspace=workspace)
    return start_module.build_start_work_payload('', workspace=workspace)['state']


def _seed_verify_state(workspace: Path) -> dict:
    task_module = _load_module('task_sessions')
    state = _seed_exec_state(workspace)
    for slug in list(state['task_sessions'].keys()):
        state = task_module.transition_task_session(
            state,
            task_slug=slug,
            next_status='completed',
            now='2026-04-19T16:00:00Z',
        )
    return state


def test_resolve_route_prefers_omh_exec_for_resumable_implementation_state():
    route_module = _load_module('route_resolver')
    intent_module = _load_module('intent_gate')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _seed_exec_state(workspace)
        _write_state(workspace, state)
        decision = route_module.resolve_route(intent_module.classify_intent('add auth middleware'), workspace=workspace)

        assert decision.route == 'omh-exec'
        assert decision.next_commands == ['omh-exec']


def test_resolve_route_prefers_omh_exec_for_open_ended_followup_when_execution_is_resumable():
    route_module = _load_module('route_resolver')
    intent_module = _load_module('intent_gate')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _seed_exec_state(workspace)
        _write_state(workspace, state)
        decision = route_module.resolve_route(
            intent_module.classify_intent('scope confirmed and ready for the next task'),
            workspace=workspace,
        )

        assert decision.route == 'omh-exec'
        assert decision.next_commands == ['omh-exec']


def test_handle_omh_ulw_command_routes_resumable_exec_state_through_omh_exec():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _seed_exec_state(workspace)
        _write_state(workspace, state)

        result = module.handle_omh_ulw_command('add auth middleware', ctx=None, workspace=workspace)
        assert 'OMH execution is waiting at exec stage.' in result
        assert 'omh-exec complete' in result


def test_handle_omh_ulw_command_records_natural_language_exec_followup_through_omh_exec():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _seed_exec_state(workspace)
        state_path = _write_state(workspace, state)

        result = module.handle_omh_ulw_command('scope confirmed and ready for the next task', ctx=None, workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        first = updated['task_sessions']['confirm-scope-and-acceptance-criteria-for-add-auth-middleware']
        second = updated['task_sessions']['identify-the-primary-files-modules-or-surfaces-likely-to-change']

        assert 'Recorded OMH exec task transition' in result
        assert 'Outcome: completed' in result
        assert first['status'] == 'completed'
        assert second['status'] == 'in_progress'


def test_handle_omh_ulw_command_routes_verify_stage_to_non_mutating_exec_guidance():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _seed_verify_state(workspace)
        state_path = _write_state(workspace, state)

        result = module.handle_omh_ulw_command('add auth middleware', ctx=None, workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'OMH execution is waiting at verify stage.' in result
        assert 'omh-verify <pass|fail>' in result
        assert updated['current_stage'] == 'verify'
        assert updated['status'] == 'active'


def test_handle_omh_ulw_command_surfaces_active_worker_waiting_for_result_in_status_view():
    module = _load_module('omh_ulw')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

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
        _write_state(workspace, state)

        result = module.handle_omh_ulw_command('status', ctx=None, workspace=workspace)

        assert 'Worker Orchestration: mode=dispatching, active_worker_id=worker-confirm-scope-and-acceptance-criteria-for-add-auth-middleware-wave-1, current_task_slug=confirm-scope-and-acceptance-criteria-for-add-auth-middleware' in result
        assert 'Awaiting worker result.' in result
        assert 'Execution is in progress.' not in result
