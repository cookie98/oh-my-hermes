from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .atlas_state import AtlasStateSnapshot, get_workspace_root, read_atlas_state
from .task_sessions import summarize_task_sessions


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


def build_status_payload(workspace: Path | None = None) -> Dict[str, Any]:
    snapshot: AtlasStateSnapshot = read_atlas_state(workspace)
    root = snapshot.workspace
    state = snapshot.state or {}

    active_plan_path = _resolve_path(state.get('active_plan'), root)
    worktree_path = _resolve_path(state.get('worktree_path'), root)
    handoff_path = _resolve_path(state.get('last_handoff'), root)

    session_ids = state.get('session_ids') if isinstance(state.get('session_ids'), list) else []
    session_origins = state.get('session_origins') if isinstance(state.get('session_origins'), dict) else {}
    task_sessions = state.get('task_sessions') if isinstance(state.get('task_sessions'), dict) else {}
    task_session_summary = summarize_task_sessions(task_sessions)

    plan_name = state.get('plan_name') or (active_plan_path.stem if active_plan_path else None)

    payload: Dict[str, Any] = {
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


def render_status_text(payload: Dict[str, Any]) -> str:
    workspace = get_workspace_root()
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

    if posture == 'idle':
        return (
            'No active OMH execution state found.\n\n'
            f'Workspace: {workspace}\n'
            'Next Step: run `omh-plan` to create a canonical plan, or `omh-ulw <intent>` to let OMH route the next step.'
        )

    if posture == 'active':
        return (
            'OMH Execution Status\n\n'
            f'Plan: {plan_name}\n'
            f'Lifecycle: {lifecycle}\n'
            f'Posture: {posture}\n'
            f'Resumable: {"yes" if payload.get("resumable") else "no"}\n'
            f'Progress: {progress}\n'
            f'Stage: {stage}\n'
            f'Wave: {wave}\n'
            f'Sessions: {(payload.get("sessions") or {}).get("count", 0)}\n'
            f'Task Sessions: {(payload.get("task_sessions") or {}).get("count", 0)}\n'
            f'Active Tasks: {active_tasks}\n'
            f'Worktree: {worktree}\n'
            f'Last Handoff: {handoff}\n'
            f'Updated: {updated_at}\n\n'
            'Execution is in progress.'
        )

    if posture == 'blocked':
        return (
            'OMH Execution Status\n\n'
            f'Plan: {plan_name}\n'
            f'Lifecycle: {lifecycle}\n'
            f'Posture: {posture}\n'
            f'Resumable: {"yes" if payload.get("resumable") else "no"}\n'
            f'Progress: {progress}\n'
            f'Stage: {stage}\n'
            f'Wave: {wave}\n'
            f'Active Tasks: {active_tasks}\n'
            f'Worktree: {worktree}\n'
            f'Last Handoff: {handoff}\n'
            f'Updated: {updated_at}\n\n'
            'Execution is blocked and needs intervention before resume.'
        )

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


def handle_omh_status_command(raw_args: str) -> str:
    args = (raw_args or '').strip()
    if args and args != '--json':
        return 'Usage: `/omh-status [--json]`'

    payload = build_status_payload()
    if args == '--json':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_status_text(payload)
