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

    for dep in ['task_sessions', 'atlas_state', 'omh_plan', 'omh_start_work', 'omh_status', 'verify_fix']:
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


def _write_state(workspace: Path, state: dict) -> None:
    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


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


def test_record_verification_pass_marks_execution_complete_and_writes_handoff():
    verify_module = _load_module('verify_fix')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        next_state = verify_module.record_verification_result(
            state,
            workspace=workspace,
            passed=True,
            summary='focused verification passed',
            now='2026-04-19T16:10:00Z',
        )

        assert next_state['status'] == 'complete'
        assert next_state['current_stage'] == 'verify'
        assert next_state['verified_at'] == '2026-04-19T16:10:00Z'
        assert next_state['last_handoff'].endswith('.omh/handoffs/verify.md')
        assert Path(next_state['last_handoff']).exists()


def test_record_verification_failure_routes_execution_into_fix_stage():
    verify_module = _load_module('verify_fix')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        next_state = verify_module.record_verification_result(
            state,
            workspace=workspace,
            passed=False,
            summary='regression suite failed',
            now='2026-04-19T16:10:00Z',
        )

        assert next_state['status'] == 'active'
        assert next_state['current_stage'] == 'fix'
        assert next_state['current_wave'] == 8
        assert next_state['last_handoff'].endswith('.omh/handoffs/verify.md')
        assert Path(next_state['last_handoff']).exists()


def test_record_fix_result_reenters_verify_stage_and_writes_fix_handoff():
    verify_module = _load_module('verify_fix')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        state['current_stage'] = 'fix'
        state['current_wave'] = 8
        next_state = verify_module.record_fix_result(
            state,
            workspace=workspace,
            summary='applied remediation patch',
            now='2026-04-19T16:20:00Z',
        )

        assert next_state['status'] == 'active'
        assert next_state['current_stage'] == 'verify'
        assert next_state['current_wave'] == 8
        assert next_state['fixed_at'] == '2026-04-19T16:20:00Z'
        assert next_state['last_handoff'].endswith('.omh/handoffs/fix.md')
        assert Path(next_state['last_handoff']).exists()


def test_status_payload_reports_complete_posture_after_verification_pass():
    status_module = _load_module('omh_status')
    verify_module = _load_module('verify_fix')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state = _completed_verify_state(workspace)
        final_state = verify_module.record_verification_result(
            state,
            workspace=workspace,
            passed=True,
            summary='focused verification passed',
            now='2026-04-19T16:10:00Z',
        )
        _write_state(workspace, final_state)

        payload = status_module.build_status_payload(workspace=workspace)
        assert payload['lifecycle'] == 'complete'
        assert payload['posture'] == 'complete'
        assert payload['stage'] == 'verify'
        assert payload['last_handoff']['exists'] is True
