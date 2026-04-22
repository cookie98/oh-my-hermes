from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

VALID_TASK_SESSION_STATUSES = {
    'pending',
    'in_progress',
    'completed',
    'blocked',
    'cancelled',
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _normalize_status(value: Any) -> str:
    status = str(value).strip().lower() if value is not None else 'pending'
    if not status:
        return 'pending'
    if status == 'done':
        return 'completed'
    if status not in VALID_TASK_SESSION_STATUSES:
        return 'pending'
    return status


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple) or isinstance(value, set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_task_sessions(task_sessions: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, payload in (task_sessions or {}).items():
        entry = dict(payload) if isinstance(payload, dict) else {}
        slug = str(entry.get('task_slug') or key).strip() or str(key).strip() or 'task'
        label = str(entry.get('label') or slug.replace('-', ' ')).strip() or slug
        entry['task_slug'] = slug
        entry['label'] = label
        entry['status'] = _normalize_status(entry.get('status'))
        entry['acceptance'] = _normalize_list(entry.get('acceptance'))
        entry['files'] = _normalize_list(entry.get('files'))
        entry['tests'] = _normalize_list(entry.get('tests'))
        normalized[slug] = entry
    return normalized


def seed_task_sessions(task_sessions: Dict[str, Any], *, now: str | None = None, current_wave: int | None = 1) -> Dict[str, Dict[str, Any]]:
    stamp = now or _now_iso()
    seeded = normalize_task_sessions(task_sessions)
    if not seeded:
        return seeded

    has_active = any(entry.get('status') in {'in_progress', 'blocked'} for entry in seeded.values())
    if has_active:
        return seeded

    for entry in seeded.values():
        if entry.get('status') != 'pending':
            continue
        entry['status'] = 'in_progress'
        entry['wave'] = current_wave or 1
        entry['started_at'] = entry.get('started_at') or stamp
        entry['updated_at'] = stamp
        break

    return seeded


def summarize_task_sessions(task_sessions: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_task_sessions(task_sessions)
    by_status: Dict[str, int] = {}
    current_task_slug: str | None = None

    for slug, entry in normalized.items():
        status = entry.get('status') or 'pending'
        by_status[status] = by_status.get(status, 0) + 1
        if current_task_slug is None and status in {'in_progress', 'blocked'}:
            current_task_slug = slug

    if current_task_slug is None:
        for slug, entry in normalized.items():
            if entry.get('status') == 'pending':
                current_task_slug = slug
                break

    return {
        'count': len(normalized),
        'by_status': by_status,
        'current_task_slug': current_task_slug,
    }


def transition_task_session(
    state: Dict[str, Any],
    *,
    task_slug: str,
    next_status: str,
    now: str | None = None,
) -> Dict[str, Any]:
    stamp = now or _now_iso()
    normalized_status = _normalize_status(next_status)
    if normalized_status not in VALID_TASK_SESSION_STATUSES:
        raise ValueError(f'invalid task session status: {next_status}')

    next_state = dict(state)
    task_sessions = normalize_task_sessions(next_state.get('task_sessions') or {})
    if task_slug not in task_sessions:
        raise KeyError(f'unknown task session: {task_slug}')

    entry = dict(task_sessions[task_slug])
    current_wave = next_state.get('current_wave') or entry.get('wave') or 1

    if normalized_status == 'in_progress':
        for other_slug, other_entry in list(task_sessions.items()):
            if other_slug == task_slug:
                continue
            if other_entry.get('status') == 'in_progress':
                demoted = dict(other_entry)
                demoted['status'] = 'pending'
                demoted['updated_at'] = stamp
                task_sessions[other_slug] = demoted
        entry['started_at'] = entry.get('started_at') or stamp
        entry['wave'] = entry.get('wave') or current_wave
        entry.pop('completed_at', None)
        entry.pop('blocked_at', None)
        next_state['status'] = 'active'
        next_state['current_stage'] = 'exec'
        next_state['current_wave'] = entry['wave']

    elif normalized_status == 'blocked':
        entry['started_at'] = entry.get('started_at') or stamp
        entry['wave'] = entry.get('wave') or current_wave
        entry['blocked_at'] = stamp
        entry.pop('completed_at', None)
        next_state['status'] = 'blocked'
        next_state['current_stage'] = 'exec'
        next_state['current_wave'] = entry['wave']

    elif normalized_status == 'completed':
        entry['started_at'] = entry.get('started_at') or stamp
        entry['wave'] = entry.get('wave') or current_wave
        entry['completed_at'] = stamp
        entry.pop('blocked_at', None)

    elif normalized_status == 'pending':
        entry.pop('completed_at', None)
        entry.pop('blocked_at', None)

    elif normalized_status == 'cancelled':
        entry.pop('blocked_at', None)
        entry.pop('completed_at', None)

    entry['status'] = normalized_status
    entry['updated_at'] = stamp
    task_sessions[task_slug] = entry

    if normalized_status == 'completed':
        blocked_slug = next((slug for slug, item in task_sessions.items() if item.get('status') == 'blocked'), None)
        if blocked_slug is not None:
            next_state['status'] = 'blocked'
            next_state['current_stage'] = 'exec'
        else:
            next_pending_slug = next((slug for slug, item in task_sessions.items() if item.get('status') == 'pending'), None)
            if next_pending_slug is not None:
                promoted = dict(task_sessions[next_pending_slug])
                next_wave = int(next_state.get('current_wave') or 0) + 1
                promoted['status'] = 'in_progress'
                promoted['wave'] = promoted.get('wave') or next_wave
                promoted['started_at'] = promoted.get('started_at') or stamp
                promoted['updated_at'] = stamp
                task_sessions[next_pending_slug] = promoted
                next_state['status'] = 'active'
                next_state['current_stage'] = 'exec'
                next_state['current_wave'] = promoted['wave']
            else:
                next_state['status'] = 'active'
                next_state['current_stage'] = 'verify'
                next_state['current_wave'] = entry.get('wave') or current_wave

    next_state['task_sessions'] = task_sessions
    next_state['updated_at'] = stamp
    return next_state
