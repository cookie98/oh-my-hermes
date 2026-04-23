from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Tuple

try:
    from .atlas_state import get_state_path, get_workspace_root, read_atlas_state
    from .omh_fix import build_fix_payload, render_fix_text
    from .omh_verify import build_verify_payload, render_verify_text
    from .task_sessions import summarize_task_sessions, transition_task_session
    from .worker_orchestration import (
        attach_worker_supervision,
        build_worker_result_bridge,
        dispatch_exec_worker,
        record_worker_result,
        record_worker_supervision_poll,
    )
except ImportError:  # pragma: no cover - support direct module imports in tests
    from atlas_state import get_state_path, get_workspace_root, read_atlas_state
    from omh_fix import build_fix_payload, render_fix_text
    from omh_verify import build_verify_payload, render_verify_text
    from task_sessions import summarize_task_sessions, transition_task_session
    from worker_orchestration import (
        attach_worker_supervision,
        build_worker_result_bridge,
        dispatch_exec_worker,
        record_worker_result,
        record_worker_supervision_poll,
    )

_EXEC_COMPLETE_HINTS = (
    'complete',
    'completed',
    'done',
    'finished',
    'confirmed',
    'move on',
    'moving on',
    'next task',
    'next step',
    'ready for the next',
    'wrapped up',
    'good to go',
    '완료',
    '끝',
    '다음 작업',
    '다음 단계',
)

_EXEC_BLOCK_HINTS = (
    'block',
    'blocked',
    'stuck',
    'waiting for',
    'waiting on',
    'need clarification',
    'needs clarification',
    'cannot continue',
    "can't continue",
    'dependency',
    'blocked by',
    'hold on',
    '막힘',
    '대기',
    '확인 필요',
)

_VERIFY_PASS_HINTS = (
    'pass',
    'passed',
    'green',
    'all checks passed',
    'verification passed',
    'tests passed',
    'verified',
    'no remaining issues',
    '통과',
    '성공',
)

_VERIFY_FAIL_HINTS = (
    'fail',
    'failed',
    'failing',
    'broken',
    'regression',
    'error',
    'errors',
    'test failure',
    'verification failed',
    '실패',
    '문제',
    '오류',
)

_TASK_RESEARCH_HINTS = frozenset({
    'research', 'investigate', 'evaluate', 'compare', 'survey',
    'look up', 'find out', 'check upstream',
})
_TASK_VERIFY_HINTS = frozenset({
    'verify', 'verification', 'validate', 'check', 'test', 'regression',
    'ensure', 'confirm', 'audit',
})
_TASK_IMPLEMENT_HINTS = frozenset({
    'implement', 'add', 'create', 'write', 'build', 'introduce',
    'refactor', 'fix', 'patch', 'update',
})

_AGENT_BRIDGE_PRIMARY = {
    'research': 'claude',
    'planning': 'claude',
    'verify': 'claude',
    'implement': 'codex',
}
_AGENT_BRIDGE_FALLBACK = 'opencode'
_AGENT_BRIDGE_ENV = {
    'claude': 'OMH_BRIDGE_CLAUDE_CMD',
    'codex': 'OMH_BRIDGE_CODEX_CMD',
    'opencode': 'OMH_BRIDGE_OPENCODE_CMD',
}


def _normalize_blocked_by(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []



def _compute_waves(lineage_dag: Dict[str, Any]) -> list[list[str]]:
    tasks = dict(lineage_dag or {})
    if not tasks:
        return []

    has_lineage = any(_normalize_blocked_by((payload or {}).get('blockedBy')) for payload in tasks.values() if isinstance(payload, dict))
    if not has_lineage:
        return [sorted(tasks.keys())]

    dependencies: dict[str, set[str]] = {}
    for slug, payload in tasks.items():
        blocked_by = _normalize_blocked_by((payload or {}).get('blockedBy') if isinstance(payload, dict) else None)
        dependencies[slug] = {item for item in blocked_by if item in tasks}

    waves: list[list[str]] = []
    completed: set[str] = set()
    remaining = set(tasks.keys())
    while remaining:
        ready = sorted(slug for slug in remaining if dependencies[slug] <= completed)
        if not ready:
            waves.append(sorted(remaining))
            break
        waves.append(ready)
        completed.update(ready)
        remaining -= set(ready)
    return waves



def _max_parallel_tasks() -> int:
    raw = str(os.environ.get('OMH_MAX_PARALLEL_TASKS', '3')).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 3
    return max(1, value)



def _wave_status(result: Dict[str, Any]) -> str:
    return str((result or {}).get('status') or '').strip().lower() or 'completed'



async def _run_wave(
    wave_tasks: list[str],
    runner: Callable[[str], Awaitable[Dict[str, Any]]],
    *,
    fail_fast: bool = True,
) -> Dict[str, Any]:
    max_parallel = _max_parallel_tasks()
    semaphore = asyncio.Semaphore(max_parallel)
    stop_scheduling = False
    results: list[Dict[str, Any]] = []
    failed_tasks: list[str] = []
    task_iter = iter(wave_tasks)

    async def worker() -> None:
        nonlocal stop_scheduling
        while True:
            if stop_scheduling:
                return
            try:
                task_slug = next(task_iter)
            except StopIteration:
                return
            async with semaphore:
                outcome = await runner(task_slug)
            results.append(outcome)
            if _wave_status(outcome) not in {'completed', 'success', 'verified'}:
                failed_tasks.append(task_slug)
                if fail_fast:
                    stop_scheduling = True
                    return

    workers = [asyncio.create_task(worker()) for _ in range(min(max_parallel, len(wave_tasks) or 1))]
    if workers:
        await asyncio.gather(*workers)

    indexed = {str(item.get('task_slug')): item for item in results if isinstance(item, dict) and item.get('task_slug') is not None}
    ordered_results = [indexed[slug] for slug in wave_tasks if slug in indexed]
    return {
        'results': ordered_results,
        'failed_tasks': failed_tasks,
        'stopped_early': bool(fail_fast and failed_tasks),
    }



def _resolve_ready_wave(task_sessions: Dict[str, Any]) -> list[str]:
    tasks = {slug: dict(payload) for slug, payload in (task_sessions or {}).items() if isinstance(payload, dict)}
    if not tasks:
        return []
    waves = _compute_waves(tasks)
    if not waves:
        return []

    for wave in waves:
        ready: list[str] = []
        for slug in wave:
            task = tasks.get(slug) or {}
            status = str(task.get('status') or '').strip().lower()
            if status in {'completed', 'cancelled'}:
                continue
            blocked_by = _normalize_blocked_by(task.get('blockedBy'))
            if all(str((tasks.get(dep) or {}).get('status') or '').strip().lower() == 'completed' for dep in blocked_by if dep in tasks):
                ready.append(slug)
        if ready:
            return ready
    return []



def _apply_wave_results(
    state: Dict[str, Any],
    wave_results: list[Dict[str, Any]],
    *,
    now: str | None = None,
    fail_fast: bool = True,
) -> Dict[str, Any]:
    stamp = now or str(state.get('updated_at') or '') or None
    next_state = dict(state)
    task_sessions = {slug: dict(payload) for slug, payload in (next_state.get('task_sessions') or {}).items() if isinstance(payload, dict)}

    failed = False
    for result in wave_results:
        task_slug = str((result or {}).get('task_slug') or '').strip()
        if not task_slug or task_slug not in task_sessions:
            continue
        entry = dict(task_sessions[task_slug])
        status = _wave_status(result)
        if status in {'completed', 'success', 'verified'}:
            entry['status'] = 'completed'
            if stamp:
                entry['completed_at'] = stamp
        else:
            entry['status'] = 'blocked'
            failed = True
            if stamp:
                entry['blocked_at'] = stamp

        artifact_paths = result.get('artifact_paths') if isinstance(result, dict) else None
        artifacts_dir = result.get('artifacts_dir') if isinstance(result, dict) else None
        if artifacts_dir or artifact_paths:
            entry['artifacts'] = {
                'artifacts_dir': str(artifacts_dir) if artifacts_dir else None,
                'artifact_paths': dict(artifact_paths) if isinstance(artifact_paths, dict) else {},
            }
        if isinstance(result, dict):
            entry['execution_result'] = {
                'backend': result.get('backend'),
                'exit_code': result.get('exit_code'),
                'stdout': result.get('stdout'),
                'stderr': result.get('stderr'),
                'manual_required': result.get('manual_required'),
            }
        if stamp:
            entry['updated_at'] = stamp
        task_sessions[task_slug] = entry

    ready_wave = _resolve_ready_wave(task_sessions)
    ready_set = set(ready_wave)
    for slug in ready_wave:
        entry = dict(task_sessions[slug])
        if str(entry.get('status') or '').strip().lower() == 'pending':
            entry['status'] = 'in_progress'
            if stamp:
                entry['started_at'] = entry.get('started_at') or stamp
                entry['updated_at'] = stamp
        task_sessions[slug] = entry

    next_state['task_sessions'] = task_sessions
    if stamp:
        next_state['updated_at'] = stamp

    if failed and fail_fast:
        next_state['status'] = 'blocked'
        next_state['current_stage'] = 'exec'
        return next_state

    if ready_wave:
        next_state['status'] = 'active'
        next_state['current_stage'] = 'exec'
        next_state['current_wave'] = min(int((task_sessions[slug].get('wave') or 1)) for slug in ready_wave)
        return next_state

    if any(str(task.get('status') or '').strip().lower() == 'pending' for task in task_sessions.values()):
        next_state['status'] = 'active'
        next_state['current_stage'] = 'exec'
        return next_state

    next_state['status'] = 'active'
    next_state['current_stage'] = 'verify'
    return next_state



def _normalize_agent_worker_type(worker_type: str | None) -> str:
    text = str(worker_type or '').strip().lower()
    if text in {'research', 'planning', 'verify'}:
        return text
    if text in {'implement', 'implementation', 'exec'}:
        return 'implement'
    return 'implement'



def _resolve_agent_bridge_workspace(task: Dict[str, Any]) -> Path:
    worktree_raw = task.get('worktree_path')
    if isinstance(worktree_raw, str) and worktree_raw.strip():
        worktree_path = Path(worktree_raw).expanduser()
        if worktree_path.exists():
            return worktree_path.resolve()
    workspace_raw = task.get('workspace') or task.get('workspace_root')
    if isinstance(workspace_raw, str) and workspace_raw.strip():
        return Path(workspace_raw).expanduser().resolve()
    return Path.cwd().resolve()



def _resolve_agent_artifacts_dir(task: Dict[str, Any]) -> Path:
    workspace = _resolve_agent_bridge_workspace(task)
    task_slug = str(task.get('task_slug') or task.get('label') or 'task').strip() or 'task'
    artifacts_dir = workspace / '.omh' / 'artifacts' / task_slug
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir



def _parse_iso_datetime(value: str | None) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None



def _collect_task_artifacts(task: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    artifacts_dir = Path(str(result.get('artifacts_dir') or _resolve_agent_artifacts_dir(task))).expanduser().resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths: Dict[str, str] = {}

    stdout = str(result.get('stdout') or '')
    stderr = str(result.get('stderr') or '')
    output_body = stdout
    if stderr:
        output_body = f'{stdout}\n\n[stderr]\n{stderr}'.strip()
    output_log = artifacts_dir / 'output.log'
    output_log.write_text(output_body + ('\n' if output_body and not output_body.endswith('\n') else ''), encoding='utf-8')
    artifact_paths['output_log'] = str(output_log)

    worktree_raw = task.get('worktree_path')
    worktree = Path(str(worktree_raw)).expanduser().resolve() if worktree_raw else None
    if worktree and worktree.exists():
        diff = subprocess.run(['git', 'diff', '--binary'], cwd=str(worktree), capture_output=True, text=True, check=False)
        diff_text = diff.stdout or ''
        if diff_text.strip():
            diff_path = artifacts_dir / 'diff.patch'
            diff_path.write_text(diff_text, encoding='utf-8')
            artifact_paths['diff_patch'] = str(diff_path)

        result_xml = worktree / 'test-results.xml'
        if result_xml.exists():
            target_xml = artifacts_dir / 'test-results.xml'
            shutil.copy2(result_xml, target_xml)
            artifact_paths['test_results_xml'] = str(target_xml)

    return {
        'artifacts_dir': str(artifacts_dir),
        'artifact_paths': artifact_paths,
    }



def _archive_expired_artifacts(
    workspace: Path,
    *,
    now: str | None = None,
    retention_days: int = 7,
    created_at_overrides: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    root = workspace.expanduser().resolve()
    artifacts_root = root / '.omh' / 'artifacts'
    archives_root = root / '.omh' / 'archives'
    archives_root.mkdir(parents=True, exist_ok=True)
    raw_overrides = created_at_overrides or {}
    created_at_overrides: Dict[str, str] = {}
    for key, value in raw_overrides.items():
        key_text = str(key)
        created_at_overrides[key_text] = value
        try:
            normalized_path = Path(key_text).expanduser()
            created_at_overrides[str(normalized_path)] = value
            created_at_overrides[str(normalized_path.resolve())] = value
            created_at_overrides[normalized_path.name] = value
        except Exception:
            pass
    current_time = _parse_iso_datetime(now) or datetime.now(timezone.utc)
    archived: list[str] = []

    if not artifacts_root.exists():
        return {'archived': archived, 'archives_root': str(archives_root)}

    archive_batch = archives_root / current_time.strftime('%Y%m%dT%H%M%SZ')
    for child in artifacts_root.iterdir():
        if not child.is_dir():
            continue
        override_value = (
            created_at_overrides.get(str(child))
            or created_at_overrides.get(str(child.resolve()))
            or created_at_overrides.get(child.name)
        )
        created_at = _parse_iso_datetime(override_value)
        if created_at is None:
            created_at = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        age_days = (current_time - created_at).total_seconds() / 86400
        if age_days < retention_days:
            continue
        archive_batch.mkdir(parents=True, exist_ok=True)
        target = archive_batch / child.name
        shutil.move(str(child), str(target))
        archived.append(str(target))

    return {
        'archived': archived,
        'archives_root': str(archives_root),
    }



def _render_agent_bridge_prompt(task: Dict[str, Any], worker_type: str) -> str:
    label = str(task.get('label') or task.get('task_slug') or 'Unnamed OMH task').strip()
    acceptance = [str(item).strip() for item in (task.get('acceptance') or []) if str(item).strip()]
    files = [str(item).strip() for item in (task.get('files') or []) if str(item).strip()]
    tests = [str(item).strip() for item in (task.get('tests') or []) if str(item).strip()]
    summary = str(task.get('summary') or '').strip()

    body = [
        f'OMH worker type: {worker_type}',
        f'Task: {label}',
    ]
    if summary:
        body.extend(['', 'Summary:', summary])
    if acceptance:
        body.extend(['', 'Acceptance Criteria:'])
        body.extend([f'- {item}' for item in acceptance])
    if files:
        body.extend(['', 'Relevant Files:'])
        body.extend([f'- {item}' for item in files])
    if tests:
        body.extend(['', 'Relevant Tests:'])
        body.extend([f'- {item}' for item in tests])
    body.extend(['', 'Return a concise execution summary and note any blockers.'])
    return '\n'.join(body).strip()



def _resolve_agent_bridge_command(agent_name: str) -> list[str] | None:
    env_name = _AGENT_BRIDGE_ENV.get(agent_name)
    override = os.environ.get(env_name, '').strip() if env_name else ''
    if override:
        command = shlex.split(override)
        if command:
            executable = command[0]
            if Path(executable).expanduser().exists() or shutil.which(executable):
                return command
    if shutil.which(agent_name):
        return [agent_name]
    return None



def _build_agent_bridge_invocation(base_command: list[str], agent_name: str, prompt: str) -> list[str]:
    if agent_name == 'claude':
        return [*base_command, '--print', prompt]
    if agent_name == 'codex':
        return [*base_command, 'exec', prompt]
    return [*base_command, 'run', prompt]



def _spawn_agent_bridge(task: Dict[str, Any], worker_type: str) -> Dict[str, Any]:
    normalized_type = _normalize_agent_worker_type(worker_type)
    preferred_agent = _AGENT_BRIDGE_PRIMARY.get(normalized_type, 'codex')
    prompt = _render_agent_bridge_prompt(task, normalized_type)
    workspace = _resolve_agent_bridge_workspace(task)
    artifacts_dir = _resolve_agent_artifacts_dir(task)
    (artifacts_dir / 'prompt.txt').write_text(prompt + '\n', encoding='utf-8')

    candidate_agents = [preferred_agent]
    if preferred_agent != _AGENT_BRIDGE_FALLBACK:
        candidate_agents.append(_AGENT_BRIDGE_FALLBACK)

    selected_agent: str | None = None
    selected_command: list[str] | None = None
    for agent_name in candidate_agents:
        command = _resolve_agent_bridge_command(agent_name)
        if command:
            selected_agent = agent_name
            selected_command = command
            break

    if selected_agent is None or selected_command is None:
        stderr = f'manual execution required: no supported agent CLI found for worker type {normalized_type}'
        result = {
            'worker_type': normalized_type,
            'backend': 'manual',
            'command': None,
            'cwd': str(workspace),
            'artifacts_dir': str(artifacts_dir),
            'exit_code': None,
            'stdout': '',
            'stderr': stderr,
            'manual_required': True,
        }
        (artifacts_dir / 'stderr.log').write_text(stderr + '\n', encoding='utf-8')
        result.update(_collect_task_artifacts(task, result))
        return result

    invocation = _build_agent_bridge_invocation(selected_command, selected_agent, prompt)
    completed = subprocess.run(
        invocation,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout or ''
    stderr = completed.stderr or ''
    (artifacts_dir / 'stdout.log').write_text(stdout, encoding='utf-8')
    (artifacts_dir / 'stderr.log').write_text(stderr, encoding='utf-8')
    result = {
        'worker_type': normalized_type,
        'backend': selected_agent,
        'command': invocation,
        'cwd': str(workspace),
        'artifacts_dir': str(artifacts_dir),
        'exit_code': completed.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'manual_required': False,
    }
    result.update(_collect_task_artifacts(task, result))
    return result



def _classify_task_session(task: Dict[str, Any]) -> str:
    text = ' '.join([
        task.get('label', ''),
        ' '.join(task.get('acceptance', [])),
        ' '.join(task.get('files', [])),
    ]).lower()
    if any(h in text for h in _TASK_VERIFY_HINTS):
        return 'verify'
    if any(h in text for h in _TASK_RESEARCH_HINTS):
        return 'research'
    if any(h in text for h in _TASK_IMPLEMENT_HINTS):
        return 'implement'
    return 'implement'


def _resolve_active_task_session(state: Dict[str, Any] | None) -> Dict[str, Any] | None:
    task_sessions = (state or {}).get('task_sessions') or {}
    fallback: Dict[str, Any] | None = None

    for payload in task_sessions.values():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get('status') or '').strip().lower()
        if status in {'completed', 'cancelled', 'done'}:
            continue
        if status in {'in_progress', 'blocked'}:
            return payload
        if fallback is None:
            fallback = payload

    return fallback


def _strip_json_flag(raw_args: str) -> Tuple[str, bool]:
    tokens = (raw_args or '').strip().split()
    json_mode = False
    kept: list[str] = []
    for token in tokens:
        if token == '--json':
            json_mode = True
        else:
            kept.append(token)
    return ' '.join(kept).strip(), json_mode


def _split_fix_reverify(raw_args: str) -> Tuple[str, str | None]:
    text = (raw_args or '').strip()
    marker = ' --reverify '
    if marker in f' {text} ':
        idx = text.find('--reverify')
        fix_args = text[:idx].strip()
        verify_args = text[idx + len('--reverify'):].strip() or None
        return fix_args, verify_args
    return text, None


def _parse_exec_action(raw_args: str) -> Tuple[str | None, str | None]:
    tokens = (raw_args or '').strip().split()
    if not tokens:
        return None, None
    action = tokens[0].strip().lower() or None
    summary = ' '.join(tokens[1:]).strip() or None
    return action, summary


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = (text or '').strip().lower()
    return any(hint in lowered for hint in hints)


def _infer_exec_action(raw_args: str) -> Tuple[str | None, str | None]:
    action, summary = _parse_exec_action(raw_args)
    if action in {'run', 'complete', 'block', 'accept'}:
        return action, summary

    text = (raw_args or '').strip()
    if not text:
        return None, None

    if _contains_hint(text, _EXEC_BLOCK_HINTS):
        return 'block', text
    if _contains_hint(text, _EXEC_COMPLETE_HINTS):
        return 'complete', text
    return None, None


def _parse_supervision_attach(raw_args: str) -> Tuple[str | None, str | None]:
    tokens = (raw_args or '').strip().split()
    if len(tokens) < 2 or tokens[0].strip().lower() != 'supervise':
        return None, None
    session_id = tokens[1].strip() or None
    command = ' '.join(tokens[2:]).strip() or None
    return session_id, command


def _parse_supervision_poll(raw_args: str) -> Tuple[str | None, str | None, str | None, int | None]:
    tokens = (raw_args or '').strip().split()
    if len(tokens) < 3 or tokens[0].strip().lower() != 'poll':
        return None, None, None, None
    session_id = tokens[1].strip() or None
    status = tokens[2].strip().lower() or None
    remaining = list(tokens[3:])
    exit_code = None
    if '--exit-code' in remaining:
        idx = remaining.index('--exit-code')
        if idx + 1 < len(remaining):
            raw_exit_code = remaining[idx + 1].strip()
            if raw_exit_code.isdigit() or (raw_exit_code.startswith('-') and raw_exit_code[1:].isdigit()):
                exit_code = int(raw_exit_code)
            del remaining[idx:idx + 2]
    observation = ' '.join(remaining).strip() or None
    return session_id, status, observation, exit_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _split_run_mode(summary: str | None) -> Tuple[str | None, bool]:
    text = str(summary or '').strip()
    if not text:
        return None, False
    tokens = text.split()
    detached = False
    kept: list[str] = []
    for token in tokens:
        if token == '--detached':
            detached = True
            continue
        kept.append(token)
    next_summary = ' '.join(kept).strip() or None
    return next_summary, detached


async def _run_agent_bridge_task(task: Dict[str, Any], worker_type: str) -> Dict[str, Any]:
    try:
        bridge_result = await asyncio.to_thread(_spawn_agent_bridge, task, worker_type)
    except Exception as exc:  # pragma: no cover - defensive bridge fallback
        return {
            'task_slug': str(task.get('task_slug') or ''),
            'status': 'failed',
            'backend': 'bridge-error',
            'command': None,
            'cwd': str(task.get('workspace') or task.get('workspace_root') or ''),
            'artifacts_dir': None,
            'artifact_paths': {},
            'exit_code': 1,
            'stdout': '',
            'stderr': str(exc),
            'manual_required': True,
        }
    status = 'completed' if bridge_result.get('exit_code') == 0 and not bridge_result.get('manual_required') else 'failed'
    return {
        'task_slug': str(task.get('task_slug') or ''),
        'status': status,
        **bridge_result,
    }


def _execute_auto_run(
    state: Dict[str, Any],
    workspace: Path,
    *,
    summary: str | None = None,
    fail_fast: bool = True,
) -> Dict[str, Any]:
    next_state = dict(state)
    waves_executed: list[list[str]] = []
    tasks_executed = 0
    failed_tasks: list[str] = []

    while str(next_state.get('current_stage') or '').strip().lower() == 'exec':
        ready_wave = _resolve_ready_wave(next_state.get('task_sessions') or {})
        if not ready_wave:
            break
        task_sessions = next_state.get('task_sessions') or {}
        worktree_path = str(next_state.get('worktree_path') or workspace)

        async def runner(task_slug: str) -> Dict[str, Any]:
            task = dict(task_sessions.get(task_slug) or {})
            task['workspace'] = str(workspace)
            task['workspace_root'] = str(workspace)
            task['worktree_path'] = worktree_path
            if summary and not task.get('summary'):
                task['summary'] = summary
            worker_type = _classify_task_session(task)
            return await _run_agent_bridge_task(task, worker_type)

        wave_result = asyncio.run(_run_wave(ready_wave, runner, fail_fast=fail_fast))
        next_state = _apply_wave_results(next_state, wave_result.get('results') or [], now=_now_iso(), fail_fast=fail_fast)
        waves_executed.append(list(ready_wave))
        tasks_executed += len(wave_result.get('results') or [])
        failed_tasks.extend([str(item) for item in (wave_result.get('failed_tasks') or []) if str(item).strip()])
        if failed_tasks and fail_fast:
            break

    return {
        'state': next_state,
        'waves_executed': waves_executed,
        'tasks_executed': tasks_executed,
        'failed_tasks': failed_tasks,
    }


def _infer_verify_outcome(raw_args: str) -> str | None:
    tokens = (raw_args or '').strip().split()
    explicit = tokens[0].strip().lower() if tokens else None
    if explicit in {'pass', 'fail'}:
        return explicit

    text = (raw_args or '').strip()
    if not text:
        return None

    if _contains_hint(text, _VERIFY_FAIL_HINTS):
        return 'fail'
    if _contains_hint(text, _VERIFY_PASS_HINTS):
        return 'pass'
    return None


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = get_state_path(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def build_exec_payload(raw_args: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    raw, _json_mode = _strip_json_flag(raw_args)
    snapshot = read_atlas_state(root)
    if not snapshot.has_state or not snapshot.state:
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'No active OMH execution state was found. Run `omh-start-work` first.',
        }

    stage = str(snapshot.state.get('current_stage') or '').strip().lower() or 'unknown'

    if stage == 'exec':
        task_summary = summarize_task_sessions(snapshot.state.get('task_sessions') or {})
        current_task_slug = task_summary.get('current_task_slug')
        worker_result_bridge = build_worker_result_bridge(snapshot.state.get('worker_orchestration') or {})
        if not raw:
            usage = 'Use `omh-exec complete [summary...]` to advance the current task, `omh-exec block [summary...]` to mark it blocked, `omh-exec run [summary...]` to auto-execute ready waves via the bridge, `omh-exec run --detached [summary...]` to dispatch the current task into a worker lane, `omh-exec supervise <session-id> [command...]` to attach a detached worker session, or `omh-exec poll <session-id> <running|completed|failed|lost> [--exit-code N] [observation...]` to update detached lifecycle state.'
            if worker_result_bridge and worker_result_bridge.get('ready'):
                usage = 'Use `omh-exec accept` to adopt the detached worker result, `omh-exec complete [summary...]` to advance the current task, `omh-exec block [summary...]` to mark it blocked, `omh-exec run [summary...]` to auto-execute ready waves via the bridge, `omh-exec run --detached [summary...]` to dispatch the current task into a worker lane, `omh-exec supervise <session-id> [command...]` to attach a detached worker session, or `omh-exec poll <session-id> <running|completed|failed|lost> [--exit-code N] [observation...]` to update detached lifecycle state.'
            return {
                'mode': 'awaiting-exec-input',
                'workspace': str(root),
                'stage': stage,
                'wave': snapshot.state.get('current_wave'),
                'current_task_slug': current_task_slug,
                'usage': usage,
            }

        attach_session_id, attach_command = _parse_supervision_attach(raw)
        if attach_session_id:
            orchestration = snapshot.state.get('worker_orchestration') or {}
            if not orchestration.get('active_worker_id'):
                return {
                    'mode': 'error',
                    'workspace': str(root),
                    'reason': 'No active OMH worker is available to attach detached supervision.',
                }
            next_state = attach_worker_supervision(snapshot.state, session_id=attach_session_id, command=attach_command)
            state_path = _write_state(root, next_state)
            return {
                'mode': 'worker-supervision-attached',
                'workspace': str(root),
                'state_path': str(state_path),
                'session_id': attach_session_id,
                'command': attach_command,
                'state': next_state,
            }

        poll_session_id, poll_status, poll_observation, poll_exit_code = _parse_supervision_poll(raw)
        if poll_session_id and poll_status:
            try:
                next_state = record_worker_supervision_poll(
                    snapshot.state,
                    session_id=poll_session_id,
                    status=poll_status,
                    observation=poll_observation,
                    exit_code=poll_exit_code,
                )
            except ValueError as exc:
                return {
                    'mode': 'error',
                    'workspace': str(root),
                    'reason': str(exc),
                }
            state_path = _write_state(root, next_state)
            return {
                'mode': 'worker-supervision-polled',
                'workspace': str(root),
                'state_path': str(state_path),
                'session_id': poll_session_id,
                'supervision_status': poll_status,
                'observation': poll_observation,
                'state': next_state,
            }

        active_task = _resolve_active_task_session(snapshot.state)
        if active_task:
            task_label = str(active_task.get('label') or '').strip() or str(active_task.get('task_slug') or current_task_slug or '').strip()
            category = _classify_task_session(active_task)
            if category == 'research':
                try:
                    from .research_lane import run_research_lane
                except ImportError:  # pragma: no cover - support direct module imports in tests
                    from research_lane import run_research_lane
                return {
                    'mode': 'task-aware-research',
                    'workspace': str(root),
                    'task_label': task_label,
                    'text': run_research_lane(task_label),
                }
            if category == 'verify':
                verify_payload = build_verify_payload('', workspace=root, task_label=task_label)
                return {
                    'mode': 'task-aware-verify',
                    'workspace': str(root),
                    'task_label': task_label,
                    'verify': verify_payload,
                    'text': render_verify_text(verify_payload),
                }

        action, summary = _infer_exec_action(raw)
        if action not in {'run', 'complete', 'block', 'accept'}:
            return {
                'mode': 'usage',
                'workspace': str(root),
                'stage': stage,
                'usage': 'Usage: `/omh-exec [run|complete|block|accept <summary...>]`, `/omh-exec run --detached [summary...]`, `/omh-exec supervise <session-id> [command...]`, or `/omh-exec poll <session-id> <running|completed|failed|lost> [--exit-code N] [observation...]` while execution is in `exec` stage.',
            }
        if not current_task_slug:
            return {
                'mode': 'error',
                'workspace': str(root),
                'reason': 'No current OMH task session could be determined for exec stage.',
            }

        if action == 'run':
            next_summary, detached_mode = _split_run_mode(summary)
            orchestration = snapshot.state.get('worker_orchestration') or {}
            active_worker_id = orchestration.get('active_worker_id')
            if active_worker_id:
                return {
                    'mode': 'worker-dispatch-blocked',
                    'workspace': str(root),
                    'stage': stage,
                    'current_task_slug': current_task_slug,
                    'active_worker_id': active_worker_id,
                    'usage': 'Use `omh-exec complete ...` or `omh-exec block ...` to finish the active worker before running `omh-exec run` again.',
                }
            if detached_mode:
                next_state = dispatch_exec_worker(snapshot.state, root, task_slug=str(current_task_slug), summary=next_summary)
                state_path = _write_state(root, next_state)
                orchestration = next_state.get('worker_orchestration') or {}
                worker_id = orchestration.get('active_worker_id')
                return {
                    'mode': 'worker-dispatched',
                    'workspace': str(root),
                    'state_path': str(state_path),
                    'worker_id': worker_id,
                    'task_slug': current_task_slug,
                    'summary': next_summary,
                    'handoff_path': next_state.get('last_handoff'),
                    'state': next_state,
                }
            auto_run = _execute_auto_run(snapshot.state, root, summary=next_summary, fail_fast=True)
            next_state = auto_run.get('state') or snapshot.state
            state_path = _write_state(root, next_state)
            return {
                'mode': 'auto-run-executed',
                'workspace': str(root),
                'state_path': str(state_path),
                'summary': next_summary,
                'waves_executed': auto_run.get('waves_executed') or [],
                'tasks_executed': auto_run.get('tasks_executed') or 0,
                'failed_tasks': auto_run.get('failed_tasks') or [],
                'state': next_state,
            }

        if action == 'accept':
            if not worker_result_bridge or not worker_result_bridge.get('ready'):
                return {
                    'mode': 'usage',
                    'workspace': str(root),
                    'stage': stage,
                    'usage': 'Usage: `/omh-exec [run|complete|block|accept <summary...>]`, `/omh-exec run --detached [summary...]`, `/omh-exec supervise <session-id> [command...]`, or `/omh-exec poll <session-id> <running|completed|failed|lost> [--exit-code N] [observation...]` while execution is in `exec` stage.',
                }
            action = str(worker_result_bridge.get('recommended_action') or '').strip().lower() or 'block'
            summary = summary or worker_result_bridge.get('summary')

        next_status = 'completed' if action == 'complete' else 'blocked'
        next_state = snapshot.state
        if (next_state.get('worker_orchestration') or {}).get('active_worker_id'):
            next_state = record_worker_result(next_state, outcome=next_status, summary=summary)
        next_state = transition_task_session(
            next_state,
            task_slug=str(current_task_slug),
            next_status=next_status,
        )
        state_path = _write_state(root, next_state)
        next_task_summary = summarize_task_sessions(next_state.get('task_sessions') or {})
        return {
            'mode': 'exec-transition-recorded',
            'workspace': str(root),
            'state_path': str(state_path),
            'action': action,
            'outcome': next_status,
            'summary': summary,
            'current_task_slug': current_task_slug,
            'next_task_slug': next_task_summary.get('current_task_slug'),
            'state': next_state,
        }

    if stage == 'verify':
        if not raw:
            return {
                'mode': 'awaiting-verify-input',
                'workspace': str(root),
                'stage': stage,
                'usage': 'Use `omh-verify <pass|fail> [summary...]` or `omh-exec <pass|fail> [summary...]` to continue from verify stage.',
            }
        verify_outcome = _infer_verify_outcome(raw)
        if verify_outcome is None:
            return {
                'mode': 'awaiting-verify-input',
                'workspace': str(root),
                'stage': stage,
                'usage': 'Use `omh-verify <pass|fail> [summary...]` or `omh-exec <pass|fail> [summary...]` to continue from verify stage.',
            }
        verify_args = raw if raw.strip().lower().split()[0:1] in [['pass'], ['fail']] else f'{verify_outcome} {raw}'.strip()
        verify_payload = build_verify_payload(verify_args, workspace=root)
        return {
            'mode': 'verify-delegated',
            'workspace': str(root),
            'stage': stage,
            'verify': verify_payload,
        }

    if stage == 'fix':
        if not raw:
            return {
                'mode': 'awaiting-fix-input',
                'workspace': str(root),
                'stage': stage,
                'usage': 'Use `omh-fix [summary...]` or `omh-exec <summary...> [--reverify <pass|fail> ...]` to continue from fix stage.',
            }
        fix_args, reverify_args = _split_fix_reverify(raw)
        fix_payload = build_fix_payload(fix_args, workspace=root)
        verify_payload = None
        if fix_payload.get('mode') == 'recorded' and reverify_args:
            verify_payload = build_verify_payload(reverify_args, workspace=root)
        return {
            'mode': 'fix-delegated',
            'workspace': str(root),
            'stage': stage,
            'fix': fix_payload,
            'reverify': verify_payload,
        }

    return {
        'mode': 'error',
        'workspace': str(root),
        'reason': f'OMH exec driver does not know how to continue from stage: {stage}.',
    }


def render_exec_text(payload: Dict[str, Any]) -> str:
    mode = payload.get('mode')
    if mode == 'error':
        return str(payload.get('reason'))
    if mode == 'usage':
        return str(payload.get('usage'))

    if mode == 'awaiting-exec-input':
        return (
            'OMH execution is waiting at exec stage.\n\n'
            f'Current Task: {payload.get("current_task_slug") or "unknown"}\n'
            f'Wave: {payload.get("wave") if payload.get("wave") is not None else "unknown"}\n\n'
            f'{payload.get("usage")}'
        )

    if mode == 'task-aware-research':
        return str(payload.get('text') or '')

    if mode == 'task-aware-verify':
        return str(payload.get('text') or '')

    if mode == 'worker-dispatch-blocked':
        return (
            'OMH execution already has an active worker.\n\n'
            f'Current Task: {payload.get("current_task_slug") or "unknown"}\n'
            f'Active Worker: {payload.get("active_worker_id") or "unknown"}\n\n'
            f'{payload.get("usage")}'
        )

    if mode == 'worker-dispatched':
        return (
            'Recorded OMH worker-dispatched result\n\n'
            f'Worker: {payload.get("worker_id") or "unknown"}\n'
            f'Task: {payload.get("task_slug") or "unknown"}\n'
            f'Handoff: {payload.get("handoff_path") or "none"}\n'
            f'Summary: {payload.get("summary") or "none"}'
        )

    if mode == 'auto-run-executed':
        state = payload.get('state') or {}
        failed_tasks = payload.get('failed_tasks') or []
        failed_text = ', '.join(str(item) for item in failed_tasks if str(item).strip()) or 'none'
        return (
            'Executed OMH auto-run waves\n\n'
            f'Waves Executed: {len(payload.get("waves_executed") or [])}\n'
            f'Tasks Executed: {payload.get("tasks_executed") or 0}\n'
            f'Failed Tasks: {failed_text}\n'
            f'Lifecycle: {state.get("status") or "unknown"}\n'
            f'Stage: {state.get("current_stage") or "unknown"}\n'
            f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}'
        )

    if mode == 'worker-supervision-attached':
        return (
            'Attached OMH worker supervision\n\n'
            f'Detached Session: {payload.get("session_id") or "unknown"}\n'
            f'Command: {payload.get("command") or "none"}'
        )

    if mode == 'worker-supervision-polled':
        return (
            'Recorded OMH worker supervision poll\n\n'
            f'Detached Session: {payload.get("session_id") or "unknown"}\n'
            f'Status: {payload.get("supervision_status") or "unknown"}\n'
            f'Observation: {payload.get("observation") or "none"}'
        )

    if mode == 'exec-transition-recorded':
        state = payload.get('state') or {}
        next_task = payload.get('next_task_slug') or 'none'
        return (
            'Recorded OMH exec task transition\n\n'
            f'Task: {payload.get("current_task_slug") or "unknown"}\n'
            f'Outcome: {payload.get("outcome") or "unknown"}\n'
            f'Lifecycle: {state.get("status") or "unknown"}\n'
            f'Stage: {state.get("current_stage") or "unknown"}\n'
            f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}\n'
            f'Next Task: {next_task}'
        )

    if mode == 'awaiting-verify-input':
        return (
            'OMH execution is waiting at verify stage.\n\n'
            f'{payload.get("usage")}'
        )

    if mode == 'awaiting-fix-input':
        return (
            'OMH execution is waiting at fix stage.\n\n'
            f'{payload.get("usage")}'
        )

    if mode == 'verify-delegated':
        return render_verify_text(payload.get('verify') or {})

    if mode == 'fix-delegated':
        fix_text = render_fix_text(payload.get('fix') or {})
        reverify = payload.get('reverify')
        if reverify:
            verify_text = render_verify_text(reverify)
            return f'{fix_text}\n\n---\n\n{verify_text}'
        return fix_text

    return json.dumps(payload, ensure_ascii=False, indent=2)


def handle_omh_exec_command(raw_args: str, *, workspace: Path | None = None) -> str:
    text, json_mode = _strip_json_flag(raw_args)
    payload = build_exec_payload(text, workspace=workspace)
    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_exec_text(payload)
