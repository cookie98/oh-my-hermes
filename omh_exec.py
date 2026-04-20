from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from .atlas_state import get_state_path, get_workspace_root, read_atlas_state
from .omh_fix import build_fix_payload, render_fix_text
from .omh_verify import build_verify_payload, render_verify_text
from .task_sessions import summarize_task_sessions, transition_task_session
from .worker_orchestration import dispatch_exec_worker, record_worker_result

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
    if action in {'run', 'complete', 'block'}:
        return action, summary

    text = (raw_args or '').strip()
    if not text:
        return None, None

    if _contains_hint(text, _EXEC_BLOCK_HINTS):
        return 'block', text
    if _contains_hint(text, _EXEC_COMPLETE_HINTS):
        return 'complete', text
    return None, None


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
        if not raw:
            return {
                'mode': 'awaiting-exec-input',
                'workspace': str(root),
                'stage': stage,
                'wave': snapshot.state.get('current_wave'),
                'current_task_slug': current_task_slug,
                'usage': 'Use `omh-exec complete [summary...]` to advance the current task, `omh-exec block [summary...]` to mark it blocked, or `omh-exec run [summary...]` to dispatch it into a worker lane.',
            }

        action, summary = _infer_exec_action(raw)
        if action not in {'run', 'complete', 'block'}:
            return {
                'mode': 'usage',
                'workspace': str(root),
                'stage': stage,
                'usage': 'Usage: `/omh-exec [run|complete|block <summary...>]` while execution is in `exec` stage.',
            }
        if not current_task_slug:
            return {
                'mode': 'error',
                'workspace': str(root),
                'reason': 'No current OMH task session could be determined for exec stage.',
            }

        if action == 'run':
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
            next_state = dispatch_exec_worker(snapshot.state, root, task_slug=str(current_task_slug), summary=summary)
            state_path = _write_state(root, next_state)
            orchestration = next_state.get('worker_orchestration') or {}
            worker_id = orchestration.get('active_worker_id')
            return {
                'mode': 'worker-dispatched',
                'workspace': str(root),
                'state_path': str(state_path),
                'worker_id': worker_id,
                'task_slug': current_task_slug,
                'summary': summary,
                'handoff_path': next_state.get('last_handoff'),
                'state': next_state,
            }

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
