from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .atlas_state import get_workspace_root
from .continuation_enforcement import build_continuation_enforcement
from .supervision_refresh import ProcessPoller, refresh_detached_worker_supervision
from .worker_orchestration import build_worker_reattachment_summary, build_worker_supervision_summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _state_file(workspace: Path) -> Path:
    return workspace / '.omh' / 'state' / 'atlas-state.json'


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = _state_file(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def build_resume_payload(raw_args: str, *, workspace: Path | None = None, process_poller: ProcessPoller | None = None) -> Dict[str, Any]:
    if (raw_args or '').strip():
        raise ValueError('Usage: `/omh-resume`')

    root = (workspace or get_workspace_root()).expanduser().resolve()
    snapshot = refresh_detached_worker_supervision(root, process_poller=process_poller)

    if not snapshot.has_state:
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'No resumable OMH execution state was found.\nRun `omh-start-work` to begin work from a canonical OMH plan.',
        }

    if snapshot.lifecycle == 'complete':
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'The last OMH execution is not resumable (status: complete).\nUse `omh-start-work` to begin a new execution session.',
        }

    if not snapshot.resumable or not snapshot.state:
        status = snapshot.lifecycle or snapshot.posture
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': f'The last OMH execution is not resumable (status: {status}).\nUse `omh-start-work` to begin a new execution session.',
        }

    state = dict(snapshot.state)
    state['updated_at'] = _now_iso()
    state_path = _write_state(root, state)
    worker_reattachment = build_worker_reattachment_summary(state.get('worker_orchestration') or {})
    worker_supervision = build_worker_supervision_summary(state.get('worker_orchestration') or {})
    continuation_enforcement = build_continuation_enforcement(snapshot)

    plan_name = state.get('plan_name') or Path(str(state.get('active_plan'))).stem
    return {
        'mode': 'resume',
        'workspace': str(root),
        'state_path': str(state_path),
        'plan': {
            'name': plan_name,
            'path': state.get('active_plan'),
        },
        'state': state,
        'progress': {
            'total': snapshot.progress.total if snapshot.progress else None,
            'completed': snapshot.progress.completed if snapshot.progress else None,
            'is_complete': snapshot.progress.is_complete if snapshot.progress else None,
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
    }


def render_resume_text(payload: Dict[str, Any]) -> str:
    if payload.get('mode') == 'error':
        return str(payload.get('reason'))

    plan = payload.get('plan') or {}
    state = payload.get('state') or {}
    progress = payload.get('progress') or {}
    total = progress.get('total')
    completed = progress.get('completed')
    progress_text = f'{completed}/{total}' if total is not None and completed is not None else 'unknown'
    wave = state.get('current_wave') if state.get('current_wave') is not None else 'unknown'
    worktree = state.get('worktree_path') or str(payload.get('workspace'))
    worker_reattachment = payload.get('worker_reattachment') or {}
    worker_supervision = payload.get('worker_supervision') or {}
    worker_line = ''
    worker_status_line = ''
    supervision_session_line = ''
    supervision_status_line = ''
    if worker_reattachment.get('active_worker_id'):
        worker_line = f'Worker Reattachment: {worker_reattachment.get("active_worker_id")}\n'
        worker_status_line = f'Worker Status: {worker_reattachment.get("status") or "unknown"}\n'
    if worker_supervision.get('session_id'):
        supervision_session_line = f'Detached Worker Session: {worker_supervision.get("session_id")}\n'
        supervision_status_line = f'Detached Worker Status: {worker_supervision.get("status") or "unknown"}\n'
    enforcement = payload.get('continuation_enforcement') or {}
    enforcement_line = ''
    next_action_line = ''
    if enforcement.get('active'):
        enforcement_line = f'Continuation Enforcement: {"strict" if enforcement.get("strict") else "soft"}\n'
        next_action_line = f'Next Action: {enforcement.get("next_action") or "Continue the current OMH execution."}\n'
    return (
        'Resuming OMH work session\n\n'
        f'Active Plan: {plan.get("name")}\n'
        f'Progress: {progress_text}\n'
        f'Stage: {state.get("current_stage") or "unknown"}\n'
        f'Wave: {wave}\n'
        f'Sessions: {len(state.get("session_ids") or [])}\n'
        f'Worktree: {worktree}\n'
        f'{worker_line}'
        f'{worker_status_line}'
        f'{supervision_session_line}'
        f'{supervision_status_line}'
        f'{enforcement_line}'
        f'{next_action_line}\n'
        'Continuing from the last incomplete execution state...'
    )


def handle_omh_resume_command(raw_args: str, *, workspace: Path | None = None, process_poller: ProcessPoller | None = None) -> str:
    if (raw_args or '').strip():
        return 'Usage: `/omh-resume`'
    payload = build_resume_payload('', workspace=workspace, process_poller=process_poller)
    return render_resume_text(payload)
