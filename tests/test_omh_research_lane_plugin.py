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

    full = f'{sub_pkg}.{module_name}'
    path = plugin_dir / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = sub_pkg
    sys.modules[full] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_specialist_messages_is_deterministic_and_lane_specific():
    module = _load_module('research_lane')

    messages = module.build_specialist_messages(' investigate plugin loading path ')

    assert messages == [
        'omh-ulw explore investigate plugin loading path',
        'omh-ulw librarian investigate plugin loading path',
        'omh-ulw oracle investigate plugin loading path',
    ]


def test_build_research_lane_payload_includes_workspace_request_and_specialist_lanes():
    module = _load_module('research_lane')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        payload = module.build_research_lane_payload('investigate plugin loading path', workspace=workspace)

        assert payload['workspace'] == str(workspace.resolve())
        assert payload['request'] == 'investigate plugin loading path'
        assert payload['lane_names'] == ['explore', 'librarian', 'oracle']
        assert payload['specialist_lanes'] == [
            {'lane': 'explore', 'message': 'omh-ulw explore investigate plugin loading path'},
            {'lane': 'librarian', 'message': 'omh-ulw librarian investigate plugin loading path'},
            {'lane': 'oracle', 'message': 'omh-ulw oracle investigate plugin loading path'},
        ]


def test_render_research_lane_text_surfaces_specialist_lanes_and_messages():
    module = _load_module('research_lane')

    payload = module.build_research_lane_payload('investigate plugin loading path')
    text = module.render_research_lane_text(payload)

    assert 'OMH Research Lane' in text
    assert 'Request: investigate plugin loading path' in text
    assert 'Specialist Lanes: explore, librarian, oracle' in text
    assert 'omh-ulw explore investigate plugin loading path' in text
    assert 'omh-ulw librarian investigate plugin loading path' in text
    assert 'omh-ulw oracle investigate plugin loading path' in text
