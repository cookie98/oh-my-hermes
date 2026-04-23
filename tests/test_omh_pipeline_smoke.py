import importlib.util
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

    for dep in ['task_sessions', 'worker_orchestration', 'atlas_state', 'intent_gate']:
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


omh_plan = _load_module('omh_plan')
omh_start_work = _load_module('omh_start_work')
read_atlas_state = _load_module('atlas_state').read_atlas_state


def test_full_pipeline_from_intent_to_status():
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        # 1. Plan
        payload = omh_plan.build_plan_payload('implement JWT auth', workspace=workspace)
        assert payload['created'] is True
        assert payload['intent_category'] in {'implementation', 'fix'}
        plan_path = Path(payload['plan']['path'])
        assert plan_path.exists()

        # 2. Start work
        result = omh_start_work.handle_omh_start_work_command(
            f'--worktree {workspace} {payload["plan"]["name"]}',
            workspace=workspace,
        )
        assert 'started' in result.lower() or 'session' in result.lower()

        # 3. Status
        snapshot = read_atlas_state(workspace)
        assert snapshot.has_state is True
        assert len(snapshot.active_task_slugs) > 0
