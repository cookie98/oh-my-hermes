from __future__ import annotations

import importlib.util
import subprocess
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

    for dep in [
        'task_sessions',
        'worker_orchestration',
        'atlas_state',
        'verify_fix',
        'omh_fix',
        'omh_verify',
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



def test_spawn_agent_bridge_prefers_codex_for_implement_and_uses_worktree(monkeypatch, tmp_path):
    module = _load_module('omh_exec')
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    calls: list[dict[str, object]] = []

    def fake_which(name: str):
        return '/usr/bin/codex' if name == 'codex' else None

    def fake_run(command, cwd, capture_output, text, check):
        calls.append({
            'command': command,
            'cwd': cwd,
            'capture_output': capture_output,
            'text': text,
            'check': check,
        })
        if command and command[0] == 'git':
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
        return subprocess.CompletedProcess(command, 0, stdout='bridge ok\n', stderr='')

    monkeypatch.setattr(module.shutil, 'which', fake_which)
    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    result = module._spawn_agent_bridge(
        {
            'task_slug': 'external-agent-bridge',
            'label': 'External Agent Bridge',
            'acceptance': ['bridge returns structured result'],
            'files': ['omh_exec.py'],
            'tests': ['tests/test_omh_exec_agent_bridge.py'],
            'workspace': str(workspace),
            'worktree_path': str(worktree),
        },
        'implement',
    )

    assert result['backend'] == 'codex'
    assert result['exit_code'] == 0
    assert result['stdout'] == 'bridge ok\n'
    assert result['stderr'] == ''
    assert result['manual_required'] is False
    assert any(call['cwd'] == str(worktree) for call in calls)
    bridge_call = next(call for call in calls if call['command'][0] != 'git')
    assert bridge_call['command'][0] == 'codex'
    assert bridge_call['command'][1] == 'exec'
    artifacts_dir = Path(result['artifacts_dir'])
    assert artifacts_dir.exists()
    assert (artifacts_dir / 'prompt.txt').exists()
    assert (artifacts_dir / 'stdout.log').read_text(encoding='utf-8') == 'bridge ok\n'



def test_spawn_agent_bridge_prefers_claude_for_research(monkeypatch, tmp_path):
    module = _load_module('omh_exec')

    def fake_which(name: str):
        return '/usr/bin/claude' if name == 'claude' else None

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(command, 0, stdout='research summary', stderr='')

    monkeypatch.setattr(module.shutil, 'which', fake_which)
    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    result = module._spawn_agent_bridge(
        {
            'task_slug': 'research-task',
            'label': 'Investigate bridge behavior',
            'workspace': str(tmp_path),
        },
        'research',
    )

    assert result['backend'] == 'claude'
    assert result['command'][0] == 'claude'
    assert result['command'][1] == '--print'
    assert result['exit_code'] == 0



def test_spawn_agent_bridge_falls_back_to_opencode_when_primary_missing(monkeypatch, tmp_path):
    module = _load_module('omh_exec')

    def fake_which(name: str):
        if name == 'opencode':
            return '/usr/bin/opencode'
        return None

    def fake_run(command, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(command, 0, stdout='fallback ok', stderr='')

    monkeypatch.setattr(module.shutil, 'which', fake_which)
    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    result = module._spawn_agent_bridge(
        {
            'task_slug': 'fallback-task',
            'label': 'Implement fallback bridge',
            'workspace': str(tmp_path),
        },
        'implement',
    )

    assert result['backend'] == 'opencode'
    assert result['command'][0] == 'opencode'
    assert result['command'][1] == 'run'
    assert result['manual_required'] is False



def test_spawn_agent_bridge_returns_manual_resolution_when_no_cli_exists(monkeypatch, tmp_path):
    module = _load_module('omh_exec')

    def fake_which(name: str):
        return None

    def fail_run(*args, **kwargs):
        raise AssertionError('subprocess.run should not be called when no bridge CLI exists')

    monkeypatch.setattr(module.shutil, 'which', fake_which)
    monkeypatch.setattr(module.subprocess, 'run', fail_run)

    result = module._spawn_agent_bridge(
        {
            'task_slug': 'manual-task',
            'label': 'Manual bridge fallback',
            'workspace': str(tmp_path),
        },
        'implement',
    )

    assert result['backend'] == 'manual'
    assert result['exit_code'] is None
    assert result['stdout'] == ''
    assert 'manual execution required' in result['stderr']
    assert result['manual_required'] is True
    artifacts_dir = Path(result['artifacts_dir'])
    assert (artifacts_dir / 'stderr.log').exists()
