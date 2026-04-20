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
_NONTERMINAL_WORKER_SESSION_STATUSES = {
    'dispatching',
    'active',
    'running',
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


def _worker_session_sort_key(session: Dict[str, Any]) -> tuple[str, str]:
    updated_at = _normalize_text(session.get('updated_at')) or ''
    secondary = _normalize_text(session.get('dispatched_at')) or _normalize_text(session.get('started_at')) or ''
    primary = max(updated_at, secondary)
    return (primary, secondary)


def _select_live_worker_session(worker_sessions: Dict[str, Dict[str, Any]]) -> Dict[str, Any] | None:
    candidates = [
        session
        for session in worker_sessions.values()
        if str(session.get('status') or '').strip().lower() in _NONTERMINAL_WORKER_SESSION_STATUSES
    ]
    if not candidates:
        return None
    return max(candidates, key=_worker_session_sort_key)


def _reattach_active_worker(normalized: Dict[str, Any]) -> None:
    worker_sessions = normalized.get('worker_sessions') or {}
    active_worker_id = normalized.get('active_worker_id')
    active_session = worker_sessions.get(active_worker_id) if active_worker_id in worker_sessions else None
    had_terminal_active_session = False
    if active_session is not None:
        active_status = str(active_session.get('status') or '').strip().lower()
        if active_status not in _NONTERMINAL_WORKER_SESSION_STATUSES:
            active_session = None
            had_terminal_active_session = True
    if active_session is None:
        active_session = _select_live_worker_session(worker_sessions)

    if active_session is None:
        if had_terminal_active_session:
            normalized['active_worker_id'] = None
            normalized['current_task_slug'] = None
            normalized['mode'] = 'idle'
        return

    normalized['active_worker_id'] = active_session.get('worker_id')
    normalized['current_task_slug'] = _normalize_text(active_session.get('task_slug'))
    normalized['mode'] = _normalize_text(active_session.get('mode'), default=active_session.get('status')) or 'idle'


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
    _reattach_active_worker(normalized)
    return normalized


def build_worker_reattachment_summary(payload: Dict[str, Any] | None) -> Dict[str, Any] | None:
    orchestration = normalize_worker_orchestration(payload)
    active_worker_id = _normalize_text(orchestration.get('active_worker_id'))
    if not active_worker_id:
        return None
    worker_sessions = orchestration.get('worker_sessions') or {}
    session = worker_sessions.get(active_worker_id)
    if not isinstance(session, dict):
        return None
    status = _normalize_text(session.get('status')) or _normalize_text(orchestration.get('mode')) or 'unknown'
    if status not in _NONTERMINAL_WORKER_SESSION_STATUSES:
        return None
    current_task_slug = _normalize_text(orchestration.get('current_task_slug')) or _normalize_text(session.get('task_slug'))
    return {
        'active_worker_id': active_worker_id,
        'current_task_slug': current_task_slug,
        'status': status,
    }


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
