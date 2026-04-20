from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .task_sessions import summarize_task_sessions

DEFAULT_WORKER_ORCHESTRATION: Dict[str, Any] = {
    'active_worker_id': None,
    'current_task_slug': None,
    'mode': 'idle',
    'backend': 'hermes-native',
    'worker_sessions': {},
}

_VALID_WORKER_SESSION_STATUSES = {
    'dispatch_ready',
    'dispatching',
    'active',
    'running',
    'blocked',
    'completed',
    'failed',
    'cancelled',
}

_WORKER_OUTCOME_ALIASES = {
    'complete': 'completed',
    'completed': 'completed',
    'done': 'completed',
    'block': 'blocked',
    'blocked': 'blocked',
    'fail': 'failed',
    'failed': 'failed',
    'cancel': 'cancelled',
    'cancelled': 'cancelled',
    'canceled': 'cancelled',
}

_WORKER_ID_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _normalize_text(value: Any, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_worker_session_status(value: Any) -> str:
    status = str(value).strip().lower() if value is not None else ''
    if not status or status not in _VALID_WORKER_SESSION_STATUSES:
        return 'dispatch_ready'
    return status


def _slugify_worker_id(value: str | None) -> str:
    text = (value or '').strip().lower()
    text = _WORKER_ID_NON_ALNUM_RE.sub('-', text).strip('-')
    return text or 'worker'


def _handoff_dir(workspace: Path) -> Path:
    return workspace / '.omh' / 'handoffs'


def _write_handoff(
    *,
    workspace: Path,
    worker_id: str,
    task_slug: str,
    generated_at: str,
    outcome: str,
    summary: str | None,
    wave: Any,
) -> Path:
    handoff_dir = _handoff_dir(workspace)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / f'{worker_id}.md'
    body = [
        '# OMH Exec Worker Handoff',
        '',
        f'- Generated At: {generated_at}',
        f'- Worker ID: {worker_id}',
        f'- Task: {task_slug}',
        f'- Outcome: {outcome}',
        f'- Wave: {wave if wave is not None else "unknown"}',
    ]
    if summary:
        body.extend(['', '## Summary', '', summary])
    handoff_path.write_text('\n'.join(body).rstrip() + '\n', encoding='utf-8')
    return handoff_path.resolve()


def normalize_worker_orchestration(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    normalized: Dict[str, Any] = dict(DEFAULT_WORKER_ORCHESTRATION)

    normalized['active_worker_id'] = _normalize_text(raw.get('active_worker_id'))
    normalized['current_task_slug'] = _normalize_text(raw.get('current_task_slug'))
    normalized['mode'] = _normalize_text(raw.get('mode'), default='idle') or 'idle'
    normalized['backend'] = _normalize_text(raw.get('backend'), default='hermes-native') or 'hermes-native'

    worker_sessions: Dict[str, Dict[str, Any]] = {}
    raw_sessions = raw.get('worker_sessions')
    if isinstance(raw_sessions, dict):
        for key, session in raw_sessions.items():
            session_payload = dict(session) if isinstance(session, dict) else {}
            base_worker_id = _normalize_text(session_payload.get('worker_id') or key) or str(key).strip() or 'worker'
            worker_id = base_worker_id
            suffix = 2
            while worker_id in worker_sessions:
                worker_id = f'{base_worker_id}-{suffix}'
                suffix += 1
            session_payload['worker_id'] = worker_id
            session_payload['status'] = _normalize_worker_session_status(session_payload.get('status'))
            worker_sessions[worker_id] = session_payload

    normalized['worker_sessions'] = worker_sessions
    return normalized


def build_worker_id(state: Dict[str, Any]) -> str:
    raw_state = state if isinstance(state, dict) else {}
    orchestration = normalize_worker_orchestration(raw_state.get('worker_orchestration') or {})
    task_slug = _normalize_text(orchestration.get('current_task_slug'))
    if not task_slug:
        task_summary = summarize_task_sessions(raw_state.get('task_sessions') or {})
        task_slug = _normalize_text(task_summary.get('current_task_slug'))
    task_slug = _slugify_worker_id(task_slug)
    wave = raw_state.get('current_wave')
    wave_suffix = f'wave-{wave}' if wave is not None else 'wave-unknown'
    base_worker_id = f'worker-{task_slug}-{wave_suffix}'
    worker_id = base_worker_id
    suffix = 2
    while worker_id in orchestration.get('worker_sessions', {}):
        worker_id = f'{base_worker_id}-{suffix}'
        suffix += 1
    return worker_id


def dispatch_exec_worker(
    state: Dict[str, Any],
    workspace: Path,
    task_slug: str,
    summary: str | None = None,
) -> Dict[str, Any]:
    stamp = _now_iso()
    next_state = dict(state)
    orchestration = normalize_worker_orchestration(next_state.get('worker_orchestration') or {})
    orchestration['current_task_slug'] = task_slug
    worker_id = build_worker_id({**next_state, 'worker_orchestration': orchestration})
    handoff_path = _write_handoff(
        workspace=workspace,
        worker_id=worker_id,
        task_slug=task_slug,
        generated_at=stamp,
        outcome='dispatched',
        summary=summary,
        wave=next_state.get('current_wave'),
    )

    worker_sessions = dict(orchestration.get('worker_sessions') or {})
    worker_sessions[worker_id] = {
        'worker_id': worker_id,
        'task_slug': task_slug,
        'status': 'dispatching',
        'mode': 'dispatching',
        'summary': summary,
        'dispatched_at': stamp,
        'updated_at': stamp,
        'handoff_path': str(handoff_path),
    }
    orchestration['active_worker_id'] = worker_id
    orchestration['current_task_slug'] = task_slug
    orchestration['mode'] = 'dispatching'
    orchestration['worker_sessions'] = worker_sessions

    next_state['worker_orchestration'] = orchestration
    next_state['last_handoff'] = str(handoff_path)
    next_state['updated_at'] = stamp
    return next_state


def _normalize_worker_outcome(outcome: Any) -> str | None:
    text = str(outcome).strip().lower() if outcome is not None else ''
    if not text:
        return None
    return _WORKER_OUTCOME_ALIASES.get(text)


def record_worker_result(
    state: Dict[str, Any],
    outcome: Any,
    summary: str | None = None,
) -> Dict[str, Any]:
    stamp = _now_iso()
    next_state = dict(state)
    orchestration = normalize_worker_orchestration(next_state.get('worker_orchestration') or {})
    worker_id = orchestration.get('active_worker_id')
    if not worker_id:
        return next_state

    worker_sessions = dict(orchestration.get('worker_sessions') or {})
    session = dict(worker_sessions.get(worker_id) or {'worker_id': worker_id})
    normalized_outcome = _normalize_worker_outcome(outcome)
    if normalized_outcome is None:
        raise ValueError(f'Unknown worker outcome: {outcome!r}')
    session['status'] = normalized_outcome
    session['outcome'] = normalized_outcome
    if summary is not None:
        session['summary'] = summary
    session['updated_at'] = stamp
    if normalized_outcome == 'completed':
        session['completed_at'] = stamp
    elif normalized_outcome == 'blocked':
        session['blocked_at'] = stamp
    elif normalized_outcome == 'failed':
        session['failed_at'] = stamp
    elif normalized_outcome == 'cancelled':
        session['cancelled_at'] = stamp
    worker_sessions[worker_id] = session

    orchestration['worker_sessions'] = worker_sessions
    orchestration['active_worker_id'] = None
    orchestration['current_task_slug'] = None
    orchestration['mode'] = 'idle'
    next_state['worker_orchestration'] = orchestration
    next_state['updated_at'] = stamp
    return next_state
