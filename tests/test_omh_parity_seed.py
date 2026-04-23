from __future__ import annotations

import importlib.util
import json
import sys
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



def test_write_json_atomically_writes_and_overwrites_without_temp_leak(tmp_path):
    atlas_state = _load_module('atlas_state')
    target = tmp_path / 'state.json'

    atlas_state.write_json_atomically(target, {'status': 'active'})
    atlas_state.write_json_atomically(target, {'status': 'complete'})

    assert target.exists() is True
    assert json.loads(target.read_text(encoding='utf-8')) == {'status': 'complete'}
    assert (tmp_path / 'state.json.tmp').exists() is False



def test_merge_lineage_references_additively_appends_without_duplicates():
    task_sessions = _load_module('task_sessions')

    merged = task_sessions.merge_lineage_references(
        {
            'task_slug': 'task-a',
            'blocks': ['T-existing-1'],
            'blockedBy': ['T-parent-1'],
        },
        add_blocks=['T-existing-1', 'T-new-1', 'T-new-2'],
        add_blocked_by=['T-parent-1', 'T-parent-2'],
    )

    assert merged['blocks'] == ['T-existing-1', 'T-new-1', 'T-new-2']
    assert merged['blockedBy'] == ['T-parent-1', 'T-parent-2']



def test_read_atlas_state_marks_complete_lifecycle_stale_when_task_sessions_are_not_terminal_even_if_plan_checkboxes_are_complete(tmp_path):
    atlas_state = _load_module('atlas_state')
    workspace = tmp_path / 'workspace'
    (workspace / '.omh/state').mkdir(parents=True)
    (workspace / '.omh/plans').mkdir(parents=True)
    plan_path = workspace / '.omh/plans/demo.md'
    plan_path.write_text('- [x] completed on paper\n', encoding='utf-8')

    (workspace / '.omh/state/atlas-state.json').write_text(
        json.dumps(
            {
                'status': 'complete',
                'active_plan': str(plan_path),
                'task_sessions': {
                    'task-a': {
                        'task_slug': 'task-a',
                        'status': 'in_progress',
                    }
                },
                'worker_orchestration': {},
            }
        ),
        encoding='utf-8',
    )

    snapshot = atlas_state.read_atlas_state(workspace=workspace)

    assert snapshot.lifecycle == 'complete'
    assert snapshot.posture == 'stale'
    assert snapshot.resumable is False
    assert snapshot.active_task_slugs == ['task-a']
