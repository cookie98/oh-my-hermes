from __future__ import annotations

import importlib.util
import json
import subprocess
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
        'worker_orchestration',
        'atlas_state',
        'verify_fix',
        'omh_fix',
        'omh_verify',
        'omh_status',
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



def test_collect_task_artifacts_writes_output_diff_and_test_results():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        worktree = workspace / 'worktree'
        worktree.mkdir()
        subprocess.run(['git', 'init'], cwd=worktree, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=worktree, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=worktree, check=True, capture_output=True)
        tracked = worktree / 'sample.txt'
        tracked.write_text('before\n', encoding='utf-8')
        subprocess.run(['git', 'add', 'sample.txt'], cwd=worktree, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=worktree, check=True, capture_output=True)
        tracked.write_text('after\n', encoding='utf-8')
        junit = worktree / 'test-results.xml'
        junit.write_text('<testsuite tests="1"></testsuite>\n', encoding='utf-8')

        result = module._collect_task_artifacts(
            {
                'task_slug': 'artifact-task',
                'workspace': str(workspace),
                'worktree_path': str(worktree),
            },
            {
                'stdout': 'bridge stdout',
                'stderr': 'bridge stderr',
            },
        )

        artifacts_dir = Path(result['artifacts_dir'])
        assert (artifacts_dir / 'output.log').exists()
        assert 'bridge stdout' in (artifacts_dir / 'output.log').read_text(encoding='utf-8')
        assert 'bridge stderr' in (artifacts_dir / 'output.log').read_text(encoding='utf-8')
        assert (artifacts_dir / 'diff.patch').exists()
        assert 'sample.txt' in (artifacts_dir / 'diff.patch').read_text(encoding='utf-8')
        assert (artifacts_dir / 'test-results.xml').exists()
        assert result['artifact_paths']['diff_patch'].endswith('diff.patch')



def test_build_status_payload_includes_task_artifacts_and_dependency_tree():
    status_module = _load_module('omh_status')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        artifact_dir = workspace / '.omh' / 'artifacts' / 'task-a'
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / 'output.log').write_text('ok\n', encoding='utf-8')
        state = {
            'version': 1,
            'active_plan': str(workspace / '.omh' / 'plans' / 'sample.md'),
            'plan_name': 'sample',
            'started_at': '2026-04-22T07:00:00Z',
            'updated_at': '2026-04-22T07:05:00Z',
            'status': 'active',
            'current_stage': 'exec',
            'current_wave': 2,
            'task_sessions': {
                'task-a': {
                    'task_slug': 'task-a',
                    'label': 'Task A',
                    'status': 'completed',
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
                    'status': 'in_progress',
                    'blocks': [],
                    'blockedBy': ['task-a'],
                },
            },
            'lineage': {
                'waves': [['task-a'], ['task-b']],
                'total_waves': 2,
            },
            'worker_orchestration': {},
        }
        _write_state(workspace, state)

        payload = status_module.build_status_payload(workspace=workspace)

        assert payload['task_artifacts']['task-a']['artifact_paths']['output_log'].endswith('output.log')
        assert any('task-a -> task-b' in line for line in payload['dependency_tree'])



def test_render_status_text_mentions_artifact_paths_and_dependency_tree():
    status_module = _load_module('omh_status')

    payload = {
        'workspace': '/tmp/demo',
        'posture': 'active',
        'lifecycle': 'active',
        'resumable': True,
        'plan': {'name': 'sample'},
        'progress': {'total': 2, 'completed': 1, 'is_complete': False},
        'stage': 'exec',
        'wave': 2,
        'sessions': {'count': 0},
        'task_sessions': {'count': 2},
        'active_task_slugs': ['task-b'],
        'worker_orchestration': {'mode': 'idle', 'active_worker_id': None, 'current_task_slug': None},
        'worker_reattachment': None,
        'worker_supervision': None,
        'worker_result_bridge': None,
        'continuation_enforcement': {'active': False},
        'idle_continuation_lines': [],
        'worktree': {'path': '/tmp/demo', 'exists': True},
        'last_handoff': {'path': None, 'exists': None},
        'updated_at': '2026-04-22T07:05:00Z',
        'consistency_warnings': [],
        'task_artifacts': {
            'task-a': {
                'artifact_paths': {
                    'output_log': '/tmp/demo/.omh/artifacts/task-a/output.log',
                }
            }
        },
        'dependency_tree': ['task-a -> task-b'],
    }

    text = status_module.render_status_text(payload)
    assert 'Task Artifacts:' in text
    assert 'task-a: output_log=/tmp/demo/.omh/artifacts/task-a/output.log' in text
    assert 'Dependency Tree:' in text
    assert 'task-a -> task-b' in text



def test_archive_expired_artifacts_moves_old_directories_after_seven_days():
    module = _load_module('omh_exec')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        artifacts_root = workspace / '.omh' / 'artifacts'
        old_dir = artifacts_root / 'old-task'
        new_dir = artifacts_root / 'new-task'
        old_dir.mkdir(parents=True, exist_ok=True)
        new_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / 'output.log').write_text('old\n', encoding='utf-8')
        (new_dir / 'output.log').write_text('new\n', encoding='utf-8')

        result = module._archive_expired_artifacts(
            workspace,
            now='2026-04-22T08:00:00Z',
            retention_days=7,
            created_at_overrides={
                str(old_dir): '2026-04-01T00:00:00Z',
                str(new_dir): '2026-04-20T00:00:00Z',
            },
        )

        assert any(item.endswith('old-task') for item in result['archived'])
        assert old_dir.exists() is False
        assert new_dir.exists() is True
        archive_root = workspace / '.omh' / 'archives'
        assert any(path.is_dir() for path in archive_root.iterdir())
