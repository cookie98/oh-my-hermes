from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import time
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
        'omh_complete',
        'omh_start_work',
        'omh_exec',
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



def _write_plan(workspace: Path) -> Path:
    plan_dir = workspace / '.omh' / 'plans'
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / 'e2e-lineage.md'
    plan_path.write_text(
        '\n'.join([
            '# E2E Lineage Plan',
            '',
            '- [ ] Root alpha task',
            '  - AC: root alpha done',
            '  **blockedBy:** `[]`',
            '  **blocks:** `[T3]`',
            '  **parentID:** `null`',
            '',
            '- [ ] Root beta task',
            '  - AC: root beta done',
            '  **blockedBy:** `[]`',
            '  **blocks:** `[T3]`',
            '  **parentID:** `null`',
            '',
            '- [ ] Integrate alpha and beta',
            '  - AC: integration complete',
            '  **blockedBy:** `[T1, T2]`',
            '  **blocks:** `[T4]`',
            '  **parentID:** `null`',
            '',
            '- [ ] Final completion bundle',
            '  - AC: final bundle written',
            '  **blockedBy:** `[T3]`',
            '  **blocks:** `[]`',
            '  **parentID:** `null`',
            '',
        ]) + '\n',
        encoding='utf-8',
    )
    return plan_path



def test_e2e_lineage_full_lifecycle_with_mock_agent_bridge_runs_under_five_seconds(monkeypatch):
    start_module = _load_module('omh_start_work')
    exec_module = _load_module('omh_exec')
    verify_module = _load_module('omh_verify')
    complete_module = _load_module('omh_complete')
    atlas_state = _load_module('atlas_state')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        _write_plan(workspace)
        start_time = time.monotonic()

        start_payload = start_module.build_start_work_payload('', workspace=workspace)
        state_path = Path(start_payload['state_path'])
        state = json.loads(state_path.read_text(encoding='utf-8'))

        assert start_payload['mode'] == 'fresh-start'
        assert len(state['lineage']['waves']) == 3
        assert [len(wave) for wave in state['lineage']['waves']] == [2, 1, 1]

        def fake_spawn(task: dict, worker_type: str):
            artifacts_dir = workspace / '.omh' / 'artifacts' / task['task_slug']
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            output_log = artifacts_dir / 'output.log'
            output_log.write_text((task.get('acceptance') or ['done'])[0] + '\n', encoding='utf-8')
            return {
                'worker_type': worker_type,
                'backend': 'mock-agent',
                'command': ['mock-agent'],
                'cwd': str(workspace),
                'artifacts_dir': str(artifacts_dir),
                'artifact_paths': {
                    'output_log': str(output_log),
                },
                'exit_code': 0,
                'stdout': (task.get('acceptance') or ['done'])[0],
                'stderr': '',
                'manual_required': False,
            }

        monkeypatch.setattr(exec_module, '_spawn_agent_bridge', fake_spawn)

        executed_waves: list[list[str]] = []
        stamp_counter = 0
        while state['current_stage'] == 'exec':
            ready_wave = exec_module._resolve_ready_wave(state['task_sessions'])
            assert ready_wave
            executed_waves.append(list(ready_wave))

            async def runner(task_slug: str):
                task = dict(state['task_sessions'][task_slug])
                task['workspace'] = str(workspace)
                task['worktree_path'] = str(workspace)
                bridge_result = exec_module._spawn_agent_bridge(task, exec_module._classify_task_session(task))
                return {
                    'task_slug': task_slug,
                    'status': 'completed' if bridge_result['exit_code'] == 0 else 'failed',
                    **bridge_result,
                }

            wave_result = asyncio.run(exec_module._run_wave(ready_wave, runner, fail_fast=True))
            stamp_counter += 1
            state = exec_module._apply_wave_results(
                state,
                wave_result['results'],
                now=f'2026-04-22T08:00:0{stamp_counter}Z',
                fail_fast=True,
            )
            atlas_state.write_json_atomically(state_path, state)

        assert executed_waves == state['lineage']['waves']
        assert state['current_stage'] == 'verify'

        verify_payload = verify_module.build_verify_payload('pass final bundle written', workspace=workspace)
        assert verify_payload['mode'] == 'recorded'
        verified_state = json.loads(state_path.read_text(encoding='utf-8'))
        assert verified_state['status'] == 'complete'

        final_task_slug = executed_waves[-1][0]
        assert verified_state['task_sessions'][final_task_slug]['verification_status'] == 'VERIFIED'
        assert verified_state['task_sessions'][final_task_slug]['verification_evidence']
        assert verified_state['task_sessions']['root-alpha-task']['artifacts']['artifact_paths']['output_log'].endswith('output.log')

        completion_text = complete_module.handle_omh_complete_command('', workspace=workspace)
        completed_state = json.loads(state_path.read_text(encoding='utf-8'))
        bundle_dir = Path(completed_state['completion']['bundle_dir'])
        summary_path = Path(completed_state['completion']['summary_path'])

        assert 'Recorded OMH completion bundle' in completion_text
        assert bundle_dir.exists()
        assert summary_path.exists()
        summary_text = summary_path.read_text(encoding='utf-8')
        assert 'Tasks Done: 4' in summary_text
        assert 'Waves Executed: 3' in summary_text
        assert 'Lineage Tree:' in summary_text
        assert 'root-alpha-task -> integrate-alpha-and-beta' in summary_text
        assert (bundle_dir / 'artifacts' / 'root-alpha-task' / 'output.log').exists()
        assert time.monotonic() - start_time < 5
