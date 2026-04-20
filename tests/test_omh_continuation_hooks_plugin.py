from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path


class _FakeCtx:
    def __init__(self) -> None:
        self.commands: dict[str, object] = {}
        self.hooks: dict[str, object] = {}
        self._poll_result: dict[str, object] | None = None
        self.poll_calls: list[str] = []

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler

    def register_command(self, name: str, handler: object, description: str = '') -> None:
        self.commands[name] = {'handler': handler, 'description': description}

    def poll_background_process(self, session_id: str):
        self.poll_calls.append(session_id)
        return self._poll_result


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

    full = f'{sub_pkg}.{module_name}'
    path = plugin_dir / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = sub_pkg
    sys.modules[full] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_resumable_state(workspace: Path) -> Path:
    plan_path = workspace / '.omh' / 'plans' / 'demo-plan.md'
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text('- [ ] keep going\n', encoding='utf-8')

    state_path = workspace / '.omh' / 'state' / 'atlas-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                'version': 1,
                'active_plan': str(plan_path),
                'plan_name': 'demo-plan',
                'started_at': '2026-04-20T00:00:00Z',
                'updated_at': '2026-04-20T00:00:00Z',
                'status': 'active',
                'current_stage': 'exec',
                'current_wave': 3,
                'session_ids': ['sess-1'],
                'session_origins': {'sess-1': 'direct'},
                'worktree_path': None,
                'task_sessions': {
                    'keep-going': {
                        'task_slug': 'keep-going',
                        'label': 'Keep going',
                        'status': 'in_progress',
                    }
                },
                'worker_orchestration': {},
                'last_handoff': None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )
    return state_path


def test_is_continuation_prompt_matches_english_and_korean_cues():
    module = _load_module('continuation_hooks')

    assert module.is_continuation_prompt('continue please') is True
    assert module.is_continuation_prompt('keep going with the next step') is True
    assert module.is_continuation_prompt('계속해줘') is True
    assert module.is_continuation_prompt('다음 작업 이어가자') is True
    assert module.is_continuation_prompt('what is the plan?') is False
    assert module.is_continuation_prompt('진행 상황 알려줘') is False
    assert module.is_continuation_prompt('이어폰 추천해줘') is False


def test_build_continuation_context_includes_active_resumable_state_details():
    atlas_state = _load_module('atlas_state')
    module = _load_module('continuation_hooks')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_resumable_state(workspace)

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        context = module.build_continuation_context(snapshot)

        assert 'OMH continuation reminder' in context
        assert 'Plan: demo-plan' in context
        assert 'Stage: exec' in context
        assert 'Wave: 3' in context
        assert 'Current Task: keep-going' in context


def test_pre_llm_call_injects_continuation_context_on_first_turn_with_resumable_state():
    module = _load_module('__init__')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_resumable_state(workspace)
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = module._pre_llm_call(user_message='hi there', platform='cli', is_first_turn=True)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is not None
        assert 'OMH continuation reminder' in result['context']
        assert 'Current Task: keep-going' in result['context']


def test_pre_llm_call_does_not_inject_on_unrelated_first_turn_even_with_resumable_state():
    module = _load_module('__init__')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_resumable_state(workspace)
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = module._pre_llm_call(user_message='what restaurants are nearby?', platform='cli', is_first_turn=True)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is None


def test_pre_llm_call_injects_continuation_context_for_continuation_cue_with_resumable_state():
    module = _load_module('__init__')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_resumable_state(workspace)
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = module._pre_llm_call(user_message='계속', platform='cli', is_first_turn=False)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is not None
        assert 'OMH continuation reminder' in result['context']
        assert 'Stage: exec' in result['context']


def test_pre_llm_call_does_not_inject_for_continuation_cues_without_resumable_state():
    module = _load_module('__init__')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = module._pre_llm_call(user_message='continue', platform='cli', is_first_turn=False)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is None


def test_build_continuation_context_mentions_recovered_worker_hint():
    atlas_state = _load_module('atlas_state')
    module = _load_module('continuation_hooks')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_resumable_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration'] = {
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'keep-going',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:05:00Z',
                }
            }
        }
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        context = module.build_continuation_context(snapshot)

        assert 'Worker Reattachment: worker-live' in context
        assert 'Worker Status: dispatching' in context



def test_build_continuation_context_mentions_detached_worker_supervision_hint():
    atlas_state = _load_module('atlas_state')
    module = _load_module('continuation_hooks')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_resumable_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration'] = {
            'active_worker_id': 'worker-live',
            'current_task_slug': 'keep-going',
            'mode': 'running',
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'keep-going',
                    'status': 'running',
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            }
        }
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')

        snapshot = atlas_state.read_atlas_state(workspace=workspace)
        context = module.build_continuation_context(snapshot)

        assert 'Detached Worker Session: proc-123' in context
        assert 'Detached Worker Status: running' in context


def test_pre_llm_call_auto_polls_running_detached_worker_before_continuation_context():
    module = _load_module('__init__')
    ctx = _FakeCtx()
    ctx._poll_result = {'status': 'completed', 'observation': 'process exited cleanly', 'exit_code': 0}
    module.register(ctx)
    hook = ctx.hooks['pre_llm_call']

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_resumable_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration'] = {
            'active_worker_id': 'worker-live',
            'current_task_slug': 'keep-going',
            'mode': 'running',
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'keep-going',
                    'status': 'running',
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            }
        }
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = hook(user_message='continue', platform='cli', is_first_turn=False)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is not None
        assert 'Detached Worker Status: completed' in result['context']
        assert ctx.poll_calls == ['proc-123']



def test_pre_llm_call_does_not_auto_poll_for_unrelated_turns_even_when_callback_exists():
    module = _load_module('__init__')
    ctx = _FakeCtx()
    ctx._poll_result = {'status': 'completed'}
    module.register(ctx)
    hook = ctx.hooks['pre_llm_call']

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_resumable_state(workspace)
        raw_state = json.loads(state_path.read_text(encoding='utf-8'))
        raw_state['worker_orchestration'] = {
            'active_worker_id': 'worker-live',
            'current_task_slug': 'keep-going',
            'mode': 'running',
            'worker_sessions': {
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'keep-going',
                    'status': 'running',
                    'updated_at': '2026-04-20T00:05:00Z',
                    'supervision': {
                        'detached': True,
                        'session_id': 'proc-123',
                        'status': 'running',
                    },
                }
            }
        }
        state_path.write_text(json.dumps(raw_state, ensure_ascii=False, indent=2), encoding='utf-8')
        previous_cwd = os.environ.get('TERMINAL_CWD')
        os.environ['TERMINAL_CWD'] = str(workspace)
        try:
            result = hook(user_message='what restaurants are nearby?', platform='cli', is_first_turn=True)
        finally:
            if previous_cwd is None:
                os.environ.pop('TERMINAL_CWD', None)
            else:
                os.environ['TERMINAL_CWD'] = previous_cwd

        assert result is None
        assert ctx.poll_calls == []
