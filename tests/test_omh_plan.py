from __future__ import annotations

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

    for dep in ['task_sessions', 'worker_orchestration', 'atlas_state', 'intent_gate', 'omh_plan']:
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


def test_implementation_plan_contains_task_structure():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_plan_payload('add auth middleware', workspace=workspace)
        plan_text = Path(payload['plan']['path']).read_text(encoding='utf-8')

        assert payload['intent_category'] == 'implementation'
        assert '## Goal' in plan_text
        assert '**blockedBy:**' in plan_text
        assert '**blocks:**' in plan_text
        assert '**parentID:**' in plan_text
        assert '## Task 1: Architecture & Tech Stack' in plan_text
        assert '## Task 2: Scope & Acceptance Criteria' in plan_text
        assert '## Task 3: Implementation with TDD' in plan_text
        assert '## Task 4: Verification' in plan_text
        assert '## Task 5: Final Verification Wave' in plan_text
        assert '- [ ] Write or update a failing test first' in plan_text
        assert 'path/to/primary_module.py' in plan_text


def test_research_plan_contains_research_questions():
    module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_plan_payload('research the plugin planning flow', workspace=workspace)
        plan_text = Path(payload['plan']['path']).read_text(encoding='utf-8')

        assert payload['intent_category'] == 'research'
        assert '## Task 0: Research Questions' in plan_text
        assert '**blockedBy:**' in plan_text
        assert '**blocks:**' in plan_text
        assert '**parentID:**' in plan_text
        assert 'R1.' in plan_text
        assert 'R2.' in plan_text
        assert 'R3.' in plan_text
        assert '## Task 1: Deliverables' in plan_text
        assert '## Task 2: Final Verification' in plan_text


def test_slugify_replaces_non_alnum_with_hyphen():
    module = _load_module('omh_plan')

    assert module._slugify('Add auth middleware!! v2') == 'add-auth-middleware-v2'
    assert module._slugify('  hello, world / plan  ') == 'hello-world-plan'
