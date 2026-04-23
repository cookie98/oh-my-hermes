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
        'worker_orchestration',
        'atlas_state',
        'verify_fix',
        'omh_fix',
        'omh_verify',
        'omh_status',
        'omh_plan',
        'omh_start_work',
        'omh_resume',
        'intent_gate',
        'route_resolver',
        'omh_ulw',
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


def _complete_ready_state(workspace: Path) -> dict:
    artifact_dir = workspace / '.omh' / 'artifacts' / 'task-a'
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / 'output.log').write_text('ok\n', encoding='utf-8')
    plan_path = workspace / '.omh' / 'plans' / 'sample-plan.md'
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text('- [x] task a\n- [x] task b\n', encoding='utf-8')
    return {
        'version': 1,
        'active_plan': str(plan_path),
        'plan_name': 'sample-plan',
        'started_at': '2026-04-22T07:00:00Z',
        'updated_at': '2026-04-22T07:10:00Z',
        'status': 'complete',
        'current_stage': 'verify',
        'current_wave': 2,
        'task_sessions': {
            'task-a': {
                'task_slug': 'task-a',
                'label': 'Task A',
                'status': 'completed',
                'wave': 1,
                'blocks': ['task-b'],
                'blockedBy': [],
                'artifacts': {
                    'artifacts_dir': str(artifact_dir),
                    'artifact_paths': {
                        'output_log': str(artifact_dir / 'output.log'),
                    },
                },
            },
            'task-b': {
                'task_slug': 'task-b',
                'label': 'Task B',
                'status': 'completed',
                'wave': 2,
                'blocks': [],
                'blockedBy': ['task-a'],
            },
        },
        'lineage': {
            'waves': [['task-a'], ['task-b']],
            'total_waves': 2,
        },
        'worker_orchestration': {},
        'session_ids': [],
        'session_origins': {},
        'last_handoff': None,
        'worktree_path': None,
        'notepad_dir': str(workspace / '.omh' / 'notepads' / 'sample-plan'),
    }


def test_build_status_payload_suggests_omh_complete_when_execution_is_complete():
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_state(workspace, _complete_ready_state(workspace))

        payload = status_module.build_status_payload(workspace=workspace)
        text = status_module.render_status_text(payload)

        assert payload['suggested_command'] == 'omh-complete'
        assert 'Next Action: Run `omh-complete`' in text


def test_handle_omh_complete_command_generates_summary_and_archives_state_and_artifacts():
    complete_module = _load_module('omh_complete')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        state_path = _write_state(workspace, _complete_ready_state(workspace))

        result = complete_module.handle_omh_complete_command('', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))

        assert 'Recorded OMH completion bundle' in result
        completed_dir = Path(updated['completion']['bundle_dir'])
        assert completed_dir.exists()
        summary_path = completed_dir / 'summary.md'
        assert summary_path.exists()
        summary_text = summary_path.read_text(encoding='utf-8')
        assert 'Tasks Done: 2' in summary_text
        assert 'Waves Executed: 2' in summary_text
        assert 'Artifacts:' in summary_text
        assert 'Lineage Tree:' in summary_text
        assert 'task-a -> task-b' in summary_text
        assert (completed_dir / 'atlas-state.json').exists()
        assert (completed_dir / 'artifacts' / 'task-a' / 'output.log').exists()
        assert updated['completion']['summary_path'].endswith('summary.md')
        assert updated['plan_locked'] is False


def test_register_includes_omh_complete_command():
    module = _load_module('__init__')
    ctx = _FakeCtx()

    module.register(ctx)

    assert 'omh-complete' in ctx.commands
