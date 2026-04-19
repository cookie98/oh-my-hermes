from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path


class _FakeCtx:
    def __init__(self) -> None:
        self.commands: dict[str, object] = {}
        self.hooks: dict[str, object] = {}
        self.skills: dict[str, object] = {}

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler

    def register_command(self, name: str, handler: object, description: str = '') -> None:
        self.commands[name] = {'handler': handler, 'description': description}

    def register_skill(self, name: str, path: Path, description: str) -> None:
        self.skills[name] = {'path': str(path), 'description': description}


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
        'intent_gate',
        'route_resolver',
        'omh_ulw',
        'omh_exec',
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


def _completed_verify_state(workspace: Path) -> dict:
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')
    task_module = _load_module('task_sessions')

    plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
    state = start_module.build_start_work_payload('', workspace=workspace)['state']
    for slug in list(state['task_sessions'].keys()):
        state = task_module.transition_task_session(
            state,
            task_slug=slug,
            next_status='completed',
            now='2026-04-19T16:00:00Z',
        )
    assert state['current_stage'] == 'verify'
    state['active_plan'] = plan_payload['plan']['path']
    state['plan_name'] = plan_payload['plan']['name']
    return state


def test_handle_omh_exec_command_routes_verify_stage_through_omh_verify():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('pass focused verification passed', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'Recorded OMH verification result' in result
        assert updated['status'] == 'complete'
        assert updated['current_stage'] == 'verify'


def test_handle_omh_exec_command_returns_non_mutating_guidance_for_verify_stage_without_outcome():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'OMH execution is waiting at verify stage.' in result
        assert 'omh-verify <pass|fail>' in result
        assert updated['current_stage'] == 'verify'
        assert updated['status'] == 'active'


def test_handle_omh_exec_command_routes_fix_stage_through_fix_and_reverify():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state['current_stage'] = 'fix'
        state['current_wave'] = 8
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('applied remediation patch --reverify pass all checks passed', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'Recorded OMH fix result' in result
        assert 'Recorded OMH verification result' in result
        assert updated['status'] == 'complete'
        assert updated['current_stage'] == 'verify'


def test_handle_omh_exec_command_returns_non_mutating_guidance_for_fix_stage_without_summary():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state['current_stage'] = 'fix'
        state['current_wave'] = 8
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'OMH execution is waiting at fix stage.' in result
        assert 'omh-fix [summary' in result
        assert updated['current_stage'] == 'fix'
        assert updated['status'] == 'active'


def test_handle_omh_exec_command_returns_non_mutating_guidance_for_exec_stage_without_action():
    module = _load_module('omh_exec')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'OMH execution is waiting at exec stage.' in result
        assert 'omh-exec complete' in result
        assert updated['current_stage'] == 'exec'
        assert updated['status'] == 'active'


def test_handle_omh_exec_command_completes_current_task_and_promotes_next_pending_task():
    module = _load_module('omh_exec')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('complete scope confirmed', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        first = updated['task_sessions']['confirm-scope-and-acceptance-criteria-for-add-auth-middleware']
        second = updated['task_sessions']['identify-the-primary-files-modules-or-surfaces-likely-to-change']

        assert 'Recorded OMH exec task transition' in result
        assert 'Outcome: completed' in result
        assert first['status'] == 'completed'
        assert second['status'] == 'in_progress'
        assert updated['current_stage'] == 'exec'
        assert updated['current_wave'] == 2
        assert updated['status'] == 'active'


def test_handle_omh_exec_command_blocks_current_task_and_marks_execution_blocked():
    module = _load_module('omh_exec')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('block waiting for requirement clarification', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        first = updated['task_sessions']['confirm-scope-and-acceptance-criteria-for-add-auth-middleware']

        assert 'Recorded OMH exec task transition' in result
        assert 'Outcome: blocked' in result
        assert first['status'] == 'blocked'
        assert updated['current_stage'] == 'exec'
        assert updated['status'] == 'blocked'


def test_handle_omh_exec_command_infers_completion_from_natural_language_followup():
    module = _load_module('omh_exec')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('scope confirmed and ready for the next task', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        first = updated['task_sessions']['confirm-scope-and-acceptance-criteria-for-add-auth-middleware']
        second = updated['task_sessions']['identify-the-primary-files-modules-or-surfaces-likely-to-change']

        assert 'Recorded OMH exec task transition' in result
        assert 'Outcome: completed' in result
        assert first['status'] == 'completed'
        assert second['status'] == 'in_progress'


def test_handle_omh_exec_command_infers_verify_pass_from_natural_language_followup():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('focused verification passed with no remaining issues', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'Recorded OMH verification result' in result
        assert updated['status'] == 'complete'
        assert updated['current_stage'] == 'verify'


def test_register_includes_omh_exec_command():
    module = _load_module('__init__')
    ctx = _FakeCtx()

    module.register(ctx)

    assert 'omh-exec' in ctx.commands
