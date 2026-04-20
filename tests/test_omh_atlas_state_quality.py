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


def test_read_atlas_state_resolves_relative_worktree_path_against_workspace_root(tmp_path):
    atlas_state_module = _load_module('atlas_state')
    workspace = tmp_path / 'workspace'
    (workspace / '.omh/state').mkdir(parents=True)
    (workspace / 'plans').mkdir(parents=True)
    (workspace / 'worktrees/demo').mkdir(parents=True)
    (workspace / 'plans/demo.md').write_text('- [ ] task\n', encoding='utf-8')

    (workspace / '.omh/state/atlas-state.json').write_text(
        json.dumps(
            {
                'status': 'active',
                'active_plan': 'plans/demo.md',
                'worktree_path': 'worktrees/demo',
                'task_sessions': {},
                'worker_orchestration': {},
            }
        ),
        encoding='utf-8',
    )

    snapshot = atlas_state_module.read_atlas_state(workspace=workspace)

    assert snapshot.posture == 'active'
    assert snapshot.resumable is True
    assert snapshot.errors == []
    assert snapshot.warnings == []
    assert snapshot.state['worktree_path'] == 'worktrees/demo'
