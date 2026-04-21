from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path


class _FakeCtx:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def inject_message(self, content: str, role: str = 'user') -> bool:
        self.messages.append(content)
        return True


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

    for dep in ['atlas_state', 'intent_gate', 'route_resolver', 'research_lane', 'omh_plan', 'omh_start_work', 'omh_resume', 'omh_status']:
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


def test_handle_omh_ulw_command_routes_status_intent_to_omh_status():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_ulw_command('status', ctx=None, workspace=workspace)

        assert 'No active OMH execution state found.' in result


def test_handle_omh_ulw_command_routes_no_plan_implementation_through_plan_then_start_work():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_ulw_command('add auth middleware', ctx=None, workspace=workspace)

        assert 'OMH Canonical Plan' in result
        assert 'Starting OMH work session' in result
        state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding='utf-8'))
        assert state['plan_name'] == 'add-auth-middleware'


def test_handle_omh_ulw_command_routes_resumable_implementation_to_omh_exec_guidance():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
        state_path.write_text(json.dumps({
            'version': 1,
            'active_plan': plan_payload['plan']['path'],
            'plan_name': 'add-auth-middleware',
            'started_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'session_ids': ['sess-a'],
            'session_origins': {'sess-a': 'direct'},
            'worktree_path': None,
            'task_sessions': {'auth-middleware': {'task_slug': 'auth-middleware', 'status': 'in_progress'}},
            'last_handoff': None,
            'notepad_dir': '.omh/notepads/add-auth-middleware/'
        }), encoding='utf-8')

        result = module.handle_omh_ulw_command('add auth middleware', ctx=None, workspace=workspace)
        assert 'OMH execution is waiting at exec stage.' in result
        assert 'Current Task: auth-middleware' in result
        assert 'omh-exec complete' in result


def test_build_ulw_context_mentions_continuation_enforcement_when_active():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
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

        context = module.build_ulw_context(user_message='add auth middleware', config={'max_instruction_chars': 4000}, workspace=workspace)

        assert 'Continuation Enforcement: strict' in context
        assert 'Next Action: Run `omh-verify <pass|fail> [summary...]`' in context


def test_handle_omh_ulw_command_routes_investigation_to_research_lane_queue_when_ctx_available():
    module = _load_module('omh_ulw')
    ctx = _FakeCtx()

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_ulw_command('investigate plugin loading path', ctx=ctx, workspace=workspace)

        assert result == 'Queued OMH ultrawork research lanes: explore, librarian, oracle.'
        assert ctx.messages == [
            'omh-ulw explore investigate plugin loading path',
            'omh-ulw librarian investigate plugin loading path',
            'omh-ulw oracle investigate plugin loading path',
        ]


def test_handle_omh_ulw_command_routes_investigation_to_research_lane_summary_without_ctx():
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        result = module.handle_omh_ulw_command('investigate plugin loading path', ctx=None, workspace=workspace)

        assert 'OMH Research Lane' in result
        assert 'Request: investigate plugin loading path' in result
        assert 'Specialist Lanes: explore, librarian, oracle' in result
        assert 'omh-ulw explore investigate plugin loading path' in result


def test_handle_omh_ulw_command_refuses_to_start_new_work_when_strict_verify_gate_is_active():
    plan_module = _load_module('omh_plan')
    module = _load_module('omh_ulw')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_payload = plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state_dir = workspace / '.omh' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / 'atlas-state.json'
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

        result = module.handle_omh_ulw_command('investigate plugin loading path', ctx=None, workspace=workspace)

        assert 'OMH execution is waiting at verify stage.' in result
        assert 'omh-verify <pass|fail>' in result
