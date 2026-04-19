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

    full = f'{sub_pkg}.{module_name}'
    path = plugin_dir / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = sub_pkg
    sys.modules[full] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_handle_omh_plan_command_returns_usage_on_empty_args():
    module = _load_module('omh_plan')
    result = module.handle_omh_plan_command('')
    assert result == 'Usage: `/omh-plan <intent...> [--json]`'


def test_handle_omh_plan_command_creates_canonical_plan_file():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_plan_payload('add auth middleware', workspace=workspace)

        plan_path = Path(payload['plan']['path'])
        assert plan_path.exists()
        assert plan_path.parent == (workspace / '.omh/plans').resolve()
        assert payload['created'] is True
        assert payload['plan']['name'] == 'add-auth-middleware'
        content = plan_path.read_text(encoding='utf-8')
        assert '# Add Auth Middleware' in content
        assert '## TODOs' in content
        assert '- [ ] 1. Confirm scope and acceptance criteria for: add auth middleware' in content


def test_handle_omh_plan_command_json_mode_returns_payload():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_plan_payload('build metrics dashboard', workspace=workspace)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        parsed = json.loads(rendered)
        assert parsed['plan']['name'] == 'build-metrics-dashboard'
        assert parsed['planning_backend'] == 'hermes-native'
