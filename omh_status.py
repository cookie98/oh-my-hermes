from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .atlas_state import AtlasStateSnapshot, get_workspace_root, read_atlas_state
from .continuation_enforcement import ContinuationEnforcement, build_continuation_enforcement
from .supervision_refresh import ProcessPoller, refresh_detached_worker_supervision
from .task_sessions import summarize_task_sessions
from .worker_orchestration import (
    build_worker_reattachment_summary,
    build_worker_supervision_summary,
    normalize_worker_orchestration,
)


def _resolve_path(raw: str | None, workspace: Path) -> Path | None:
    if not raw or not str(raw).strip():
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    return path


def _origin_counts(session_origins: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in session_origins.values():
        label = str(value).strip() if value is not None else 'unknown'
        if not label:
            label = 'unknown'
        counts[label] = counts.get(label, 0) + 1
    return counts


def build_status_payload(workspace: Path | None = None, *, process_poller: ProcessPoller | None = None) -> Dict[str, Any]:
    snapshot: AtlasStateSnapshot = refresh_detached_worker_supervision(workspace or get_workspace_root(), process_poller=process_poller)
    root = snapshot.workspace
    state = snapshot.state or {}

    active_plan_path = _resolve_path(state.get('active_plan'), root)
    worktree_path = _resolve_path(state.get('worktree_path'), root)
    handoff_path = _resolve_path(state.get('last_handoff'), root)

    session_ids = state.get('session_ids') if isinstance(state.get('session_ids'), list) else []
    session_origins = state.get('session_origins') if isinstance(state.get('session_origins'), dict) else {}
    task_sessions = state.get('task_sessions') if isinstance(state.get('task_sessions'), dict) else {}
    task_session_summary = summarize_task_sessions(task_sessions)
    worker_orchestration = normalize_worker_orchestration(state.get('worker_orchestration') or {})
    worker_reattachment = build_worker_reattachment_summary(state.get('worker_orchestration') or {})
    worker_supervision = build_worker_supervision_summary(state.get('worker_orchestration') or {})
    continuation_enforcement: ContinuationEnforcement = build_continuation_enforcement(snapshot)

    plan_name = state.get('plan_name') or (active_plan_path.stem if active_plan_path else None)

    payload: Dict[str, Any] = {
        'workspace': str(root),
        'state_path': str(snapshot.state_path),
        'has_state': snapshot.has_state,
        'lifecycle': snapshot.lifecycle,
        'posture': snapshot.posture,
        'resumable': snapshot.resumable,
        'plan': {
            'name': plan_name,
            'path': str(active_plan_path) if active_plan_path else None,
        },
        'progress': None,
        'stage': state.get('current_stage'),
        'wave': state.get('current_wave'),
        'sessions': {
            'count': len(session_ids),
            'origins': _origin_counts(session_origins),
        },
        'task_sessions': task_session_summary,
        'worker_orchestration': {
            'mode': worker_orchestration.get('mode'),
            'active_worker_id': worker_orchestration.get('active_worker_id'),
            'current_task_slug': worker_orchestration.get('current_task_slug'),
        },
        'worker_reattachment': worker_reattachment,
        'worker_supervision': worker_supervision,
        'continuation_enforcement': {
            'active': continuation_enforcement.active,
            'strict': continuation_enforcement.strict,
            'route': continuation_enforcement.route,
            'reason': continuation_enforcement.reason,
            'next_action': continuation_enforcement.next_action,
        },
        'active_task_slugs': list(snapshot.active_task_slugs),
        'worktree': {
            'path': str(worktree_path) if worktree_path else None,
            'exists': worktree_path.exists() if worktree_path else None,
        },
        'last_handoff': {
            'path': str(handoff_path) if handoff_path else None,
            'exists': handoff_path.exists() if handoff_path else None,
        },
        'updated_at': state.get('updated_at') or state.get('started_at'),
        'warnings': list(snapshot.warnings),
        'errors': list(snapshot.errors),
    }

    if snapshot.progress is not None:
        payload['progress'] = {
            'total': snapshot.progress.total,
            'completed': snapshot.progress.completed,
            'is_complete': snapshot.progress.is_complete,
        }

    return payload


def _format_progress(payload: Dict[str, Any]) -> str:
    progress = payload.get('progress') or {}
    total = progress.get('total')
    completed = progress.get('completed')
    if total is None or completed is None:
        return 'unknown'
    return f'{completed}/{total}'


def _format_active_tasks(payload: Dict[str, Any]) -> str:
    slugs = payload.get('active_task_slugs') or []
    return ', '.join(slugs[:3]) if slugs else 'none'


def _display_worktree(payload: Dict[str, Any], workspace: Path) -> str:
    worktree = payload.get('worktree') or {}
    return worktree.get('path') or str(workspace)


def _display_handoff(payload: Dict[str, Any]) -> str:
    handoff = payload.get('last_handoff') or {}
    return handoff.get('path') or 'none'


def _format_worker_orchestration(payload: Dict[str, Any]) -> str:
    worker_orchestration = payload.get('worker_orchestration') or {}
    mode = worker_orchestration.get('mode') or 'idle'
    active_worker_id = worker_orchestration.get('active_worker_id') or 'none'
    current_task_slug = worker_orchestration.get('current_task_slug') or 'none'
    return (
        f'Worker Orchestration: mode={mode}, '
        f'active_worker_id={active_worker_id}, '
        f'current_task_slug={current_task_slug}'
    )


def _format_worker_reattachment(payload: Dict[str, Any]) -> str | None:
    worker_reattachment = payload.get('worker_reattachment') or {}
    active_worker_id = worker_reattachment.get('active_worker_id')
    status = worker_reattachment.get('status')
    if not active_worker_id or not status:
        return None
    return f'Worker Reattachment: {active_worker_id} ({status})'


def _format_worker_supervision(payload: Dict[str, Any]) -> str | None:
    worker_supervision = payload.get('worker_supervision') or {}
    session_id = worker_supervision.get('session_id')
    status = worker_supervision.get('status')
    detached = worker_supervision.get('detached')
    if not session_id or not status or not detached:
        return None
    return f'Worker Supervision: detached session {session_id} ({status})'


def _format_continuation_enforcement(payload: Dict[str, Any]) -> tuple[str | None, str | None]:
    enforcement = payload.get('continuation_enforcement') or {}
    if not enforcement.get('active'):
        return None, None
    level = 'strict' if enforcement.get('strict') else 'soft'
    next_action = enforcement.get('next_action')
    return f'Continuation Enforcement: {level}', f'Next Action: {next_action}' if next_action else None


def _worker_activity_message(payload: Dict[str, Any]) -> str:
    worker_supervision = payload.get('worker_supervision') or {}
    if worker_supervision.get('detached') and worker_supervision.get('status') == 'running':
        return 'Detached worker session is still running.'
    worker_orchestration = payload.get('worker_orchestration') or {}
    if worker_orchestration.get('active_worker_id'):
        return 'Awaiting worker result.'
    return 'Execution is in progress.'


def render_status_text(payload: Dict[str, Any]) -> str:
    workspace = Path(str(payload.get('workspace') or get_workspace_root()))
    posture = payload.get('posture')
    lifecycle = payload.get('lifecycle') or 'none'
    plan = payload.get('plan') or {}
    plan_name = plan.get('name') or 'unknown'
    progress = _format_progress(payload)
    active_tasks = _format_active_tasks(payload)
    updated_at = payload.get('updated_at') or 'unknown'
    worktree = _display_worktree(payload, workspace)
    handoff = _display_handoff(payload)
    stage = payload.get('stage') or 'unknown'
    wave = payload.get('wave') if payload.get('wave') is not None else 'unknown'
    worker_orchestration = payload.get('worker_orchestration') or {}
    worker_summary = _format_worker_orchestration(payload)
    worker_reattachment = _format_worker_reattachment(payload)
    worker_supervision = _format_worker_supervision(payload)
    enforcement_level, next_action = _format_continuation_enforcement(payload)
    active_worker_id = worker_orchestration.get('active_worker_id')

    if posture == 'idle':
        return (
            'No active OMH execution state found.\n\n'
            f'Workspace: {workspace}\n'
            'Next Step: run `omh-plan` to create a canonical plan, or `omh-ulw <intent>` to let OMH route the next step.'
        )

    if posture == 'active':
        show_worker = bool(
            active_worker_id
            or (worker_orchestration.get('mode') and worker_orchestration.get('mode') != 'idle')
            or worker_orchestration.get('current_task_slug')
        )
        lines = [
            'OMH Execution Status',
            '',
            f'Plan: {plan_name}',
            f'Lifecycle: {lifecycle}',
            f'Posture: {posture}',
            f'Resumable: {"yes" if payload.get("resumable") else "no"}',
            f'Progress: {progress}',
            f'Stage: {stage}',
            f'Wave: {wave}',
            f'Sessions: {(payload.get("sessions") or {}).get("count", 0)}',
            f'Task Sessions: {(payload.get("task_sessions") or {}).get("count", 0)}',
            f'Active Tasks: {active_tasks}',
        ]
        if show_worker:
            lines.append(worker_summary)
        if worker_reattachment:
            lines.append(worker_reattachment)
        if worker_supervision:
            lines.append(worker_supervision)
        if enforcement_level:
            lines.append(enforcement_level)
        if next_action:
            lines.append(next_action)
        lines.extend([
            f'Worktree: {worktree}',
            f'Last Handoff: {handoff}',
            f'Updated: {updated_at}',
            '',
            _worker_activity_message(payload),
        ])
        return '\n'.join(lines)

    if posture == 'blocked':
        show_worker = bool(
            active_worker_id
            or (worker_orchestration.get('mode') and worker_orchestration.get('mode') != 'idle')
            or worker_orchestration.get('current_task_slug')
        )
        lines = [
            'OMH Execution Status',
            '',
            f'Plan: {plan_name}',
            f'Lifecycle: {lifecycle}',
            f'Posture: {posture}',
            f'Resumable: {"yes" if payload.get("resumable") else "no"}',
            f'Progress: {progress}',
            f'Stage: {stage}',
            f'Wave: {wave}',
            f'Active Tasks: {active_tasks}',
        ]
        if show_worker:
            lines.append(worker_summary)
        if worker_reattachment:
            lines.append(worker_reattachment)
        if worker_supervision:
            lines.append(worker_supervision)
        if enforcement_level:
            lines.append(enforcement_level)
        if next_action:
            lines.append(next_action)
        lines.extend([
            f'Worktree: {worktree}',
            f'Last Handoff: {handoff}',
            f'Updated: {updated_at}',
            '',
            'Detached worker session is still running.' if ((payload.get('worker_supervision') or {}).get('detached') and (payload.get('worker_supervision') or {}).get('status') == 'running') else ('Awaiting worker result.' if active_worker_id else 'Execution is blocked and needs intervention before resume.'),
        ])
        return '\n'.join(lines)

    if posture == 'stale':
        issue = (payload.get('errors') or payload.get('warnings') or ['lifecycle-progress-mismatch'])[0]
        return (
            'OMH execution state is stale.\n\n'
            f'Plan: {plan_name}\n'
            f'Lifecycle: {lifecycle}\n'
            'Posture: stale\n'
            f'Progress: {progress}\n'
            f'Active Tasks: {active_tasks}\n'
            f'Issue: {issue}\n\n'
            'Suggested actions:\n'
            '- inspect why stored lifecycle disagrees with the canonical plan, then\n'
            '- repair the state intentionally or start a new execution session'
        )

    if posture == 'broken':
        issue = (payload.get('errors') or ['broken-state-reason'])[0]
        return (
            'OMH execution state is broken.\n\n'
            f'State File: {payload.get("state_path")}\n'
            f'Plan: {plan_name}\n'
            f'Issue: {issue}\n\n'
            'Suggested actions:\n'
            '- restore the missing artifact, or\n'
            '- start a new execution with `omh-start-work`'
        )

    if posture in {'complete', 'failed', 'cancelled'}:
        return (
            'OMH Execution Status\n\n'
            f'Plan: {plan_name}\n'
            f'Lifecycle: {lifecycle}\n'
            f'Posture: {posture}\n'
            f'Progress: {progress}\n'
            f'Active Tasks: {active_tasks}\n'
            f'Updated: {updated_at}'
        )

    return json.dumps(payload, ensure_ascii=False, indent=2)


def handle_omh_status_command(raw_args: str, *, workspace: Path | None = None, process_poller: ProcessPoller | None = None) -> str:
    args = (raw_args or '').strip()
    if args and args != '--json':
        return 'Usage: `/omh-status [--json]`'

    payload = build_status_payload(workspace=workspace, process_poller=process_poller)
    if args == '--json':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_status_text(payload)
