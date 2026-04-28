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
    assert result == 'Usage: `/omh-plan <intent...> [--json]` or `/omh-plan finalize <plan-name> [--json]`'


def test_handle_omh_plan_command_creates_draft_plan_file_first():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_draft_plan_payload('add auth middleware', workspace=workspace)

        plan_path = Path(payload['draft']['path'])
        assert plan_path.exists()
        assert plan_path.parent == (workspace / '.omh/drafts').resolve()
        assert payload['created'] is True
        assert payload['draft']['name'] == 'add-auth-middleware'
        assert not (workspace / '.omh' / 'plans' / 'add-auth-middleware.md').exists()
        content = plan_path.read_text(encoding='utf-8')
        assert '# Add Auth Middleware' in content
        assert 'add auth middleware' in content.lower() or '# Add Auth Middleware' in content
        assert '- [ ]' in content
        assert '> Draft OMH plan' in content
        assert '## Task 1: Scope & Acceptance Criteria' in content
        assert '**blockedBy:** `[]`' in content


def test_handle_omh_plan_command_finalize_materializes_canonical_plan_and_deletes_draft():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        module.build_draft_plan_payload('add auth middleware', workspace=workspace)

        payload = module.finalize_draft_plan_payload('add-auth-middleware', workspace=workspace)

        canonical_path = Path(payload['plan']['path'])
        draft_path = workspace / '.omh' / 'drafts' / 'add-auth-middleware.md'
        assert canonical_path.exists()
        assert canonical_path.parent == (workspace / '.omh' / 'plans').resolve()
        assert payload['draft_deleted'] is True
        assert not draft_path.exists()
        content = canonical_path.read_text(encoding='utf-8')
        assert '> Canonical OMH plan' in content
        assert '## Task 1: Scope & Acceptance Criteria' in content


def test_handle_omh_plan_command_json_mode_returns_payload():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_draft_plan_payload('build metrics dashboard', workspace=workspace)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        parsed = json.loads(rendered)
        assert parsed['draft']['name'] == 'build-metrics-dashboard'
        assert parsed['planning_backend'] == 'hermes-native'
