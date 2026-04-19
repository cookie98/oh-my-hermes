from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .atlas_state import discover_canonical_plans, get_workspace_root, read_atlas_state
from .task_sessions import seed_task_sessions

_HEADING_RE = re.compile(r'^##\s+')
_UNCHECKED_TASK_RE = re.compile(r'^- \[ \]\s*(.+?)\s*$')
_TASK_LABEL_PREFIX_RE = re.compile(r'^(?:F?\d+\.)\s*')
_SLUG_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _slugify(text: str) -> str:
    lowered = text.lower().strip()
    slug = _SLUG_NON_ALNUM_RE.sub('-', lowered).strip('-')
    return slug or 'task'


def _parse_args(raw_args: str) -> Tuple[str | None, str | None, bool]:
    tokens = (raw_args or '').strip().split()
    plan_name: str | None = None
    worktree: str | None = None
    json_mode = False

    idx = 0
    free: List[str] = []
    while idx < len(tokens):
        token = tokens[idx]
        if token == '--json':
            json_mode = True
            idx += 1
            continue
        if token == '--worktree':
            if idx + 1 < len(tokens):
                worktree = tokens[idx + 1]
            idx += 2
            continue
        free.append(token)
        idx += 1

    if free:
        plan_name = ' '.join(free).strip()
    return plan_name, worktree, json_mode


def _match_plans(plan_name: str, plans: List[Path]) -> List[Path]:
    wanted = (plan_name or '').strip().lower()
    if not wanted:
        return []
    exact = [p for p in plans if p.stem.lower() == wanted]
    if exact:
        return exact
    return [p for p in plans if wanted in p.stem.lower()]


def _state_file(workspace: Path) -> Path:
    return workspace / '.omh' / 'state' / 'atlas-state.json'


def _notepad_dir(workspace: Path, plan_name: str) -> Path:
    return workspace / '.omh' / 'notepads' / plan_name


def _extract_execution_tasks(plan_path: Path) -> Dict[str, Any]:
    text = plan_path.read_text(encoding='utf-8')
    in_todos = False
    task_sessions: Dict[str, Any] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() == '## todos':
            in_todos = True
            continue
        if in_todos and _HEADING_RE.match(stripped):
            break
        if not in_todos:
            continue
        match = _UNCHECKED_TASK_RE.match(stripped)
        if not match:
            continue
        label = match.group(1).strip()
        label = _TASK_LABEL_PREFIX_RE.sub('', label).strip()
        if not label:
            continue
        slug = _slugify(label)
        task_sessions[slug] = {
            'task_slug': slug,
            'label': label,
            'status': 'pending',
        }

    return task_sessions


def _build_initial_state(*, workspace: Path, plan_path: Path, plan_name: str, worktree_path: str | None) -> Dict[str, Any]:
    now = _now_iso()
    task_sessions = seed_task_sessions(
        _extract_execution_tasks(plan_path),
        now=now,
        current_wave=1,
    )
    return {
        'version': 1,
        'active_plan': str(plan_path),
        'plan_name': plan_name,
        'started_at': now,
        'updated_at': now,
        'status': 'active',
        'current_stage': 'exec',
        'current_wave': 1 if task_sessions else None,
        'session_ids': [],
        'session_origins': {},
        'worktree_path': worktree_path,
        'task_sessions': task_sessions,
        'last_handoff': None,
        'notepad_dir': str(_notepad_dir(workspace, plan_name)),
    }


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = _state_file(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def _payload_for_failure(*, workspace: Path, reason: str) -> Dict[str, Any]:
    return {
        'mode': 'error',
        'workspace': str(workspace),
        'reason': reason,
    }


def build_start_work_payload(raw_args: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    requested_plan, requested_worktree, _json_mode = _parse_args(raw_args)
    snapshot = read_atlas_state(root)
    plans = discover_canonical_plans(root)

    selected_plan: Path | None = None
    mode = 'fresh-start'
    state: Dict[str, Any] | None = None

    if requested_plan:
        matches = _match_plans(requested_plan, plans)
        if not matches:
            return _payload_for_failure(workspace=root, reason='No canonical OMH plan found for this request. Run `omh-plan` first, then retry `omh-start-work`.')
        if len(matches) > 1:
            return {
                'mode': 'needs-selection',
                'workspace': str(root),
                'requested_plan': requested_plan,
                'matches': [p.stem for p in matches],
                'reason': 'Multiple canonical OMH plans matched. Choose one explicitly.',
            }
        selected_plan = matches[0]

    if selected_plan is None and snapshot.resumable and snapshot.state:
        active_plan_raw = snapshot.state.get('active_plan')
        if isinstance(active_plan_raw, str) and active_plan_raw.strip():
            active_plan = Path(active_plan_raw).expanduser()
            if not active_plan.is_absolute():
                active_plan = (root / active_plan).resolve()
            if active_plan.exists():
                selected_plan = active_plan
                mode = 'resume'
                state = dict(snapshot.state)

    if selected_plan is None:
        if len(plans) == 1:
            selected_plan = plans[0]
        elif len(plans) > 1:
            return {
                'mode': 'needs-selection',
                'workspace': str(root),
                'matches': [p.stem for p in plans],
                'reason': 'Multiple canonical OMH plans exist. Choose one explicitly.',
            }
        else:
            return _payload_for_failure(workspace=root, reason='No canonical OMH plan found for this request. Run `omh-plan` first, then retry `omh-start-work`.')

    plan_name = selected_plan.stem

    if mode == 'resume' and state is not None:
        state['updated_at'] = _now_iso()
        if requested_worktree is not None:
            state['worktree_path'] = requested_worktree
        state_path = _write_state(root, state)
        return {
            'mode': 'resume',
            'workspace': str(root),
            'state_path': str(state_path),
            'plan': {
                'name': plan_name,
                'path': str(selected_plan),
            },
            'state': state,
            'progress': {
                'total': snapshot.progress.total if snapshot.progress else None,
                'completed': snapshot.progress.completed if snapshot.progress else None,
                'is_complete': snapshot.progress.is_complete if snapshot.progress else None,
            },
        }

    initial_state = _build_initial_state(
        workspace=root,
        plan_path=selected_plan,
        plan_name=plan_name,
        worktree_path=requested_worktree,
    )
    state_path = _write_state(root, initial_state)
    return {
        'mode': 'fresh-start',
        'workspace': str(root),
        'state_path': str(state_path),
        'plan': {
            'name': plan_name,
            'path': str(selected_plan),
        },
        'state': initial_state,
    }


def render_start_work_text(payload: Dict[str, Any]) -> str:
    mode = payload.get('mode')
    if mode == 'error':
        return str(payload.get('reason'))
    if mode == 'needs-selection':
        matches = payload.get('matches') or []
        rendered = '\n'.join(f'- {name}' for name in matches)
        return (
            'Multiple canonical OMH plans matched.\n\n'
            f'{rendered}\n\n'
            'Choose one plan explicitly and retry `omh-start-work <plan-name>`.'
        )

    plan = payload.get('plan') or {}
    state = payload.get('state') or {}
    worktree = state.get('worktree_path') or str(payload.get('workspace'))

    if mode == 'resume':
        progress = payload.get('progress') or {}
        total = progress.get('total')
        completed = progress.get('completed')
        progress_text = f'{completed}/{total}' if total is not None and completed is not None else 'unknown'
        return (
            'Resuming OMH work session\n\n'
            f'Active Plan: {plan.get("name")}\n'
            f'Progress: {progress_text}\n'
            f'Stage: {state.get("current_stage") or "unknown"}\n'
            f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}\n'
            f'Sessions: {len(state.get("session_ids") or [])}\n'
            f'Worktree: {worktree}\n\n'
            'Continuing from the last incomplete execution state...'
        )

    return (
        'Starting OMH work session\n\n'
        f'Plan: {plan.get("name")}\n'
        f'Stage: {state.get("current_stage") or "exec"}\n'
        f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}\n'
        f'Task Sessions: {len(state.get("task_sessions") or {})}\n'
        f'Worktree: {worktree}\n\n'
        'Reading canonical plan and preparing execution...'
    )


def handle_omh_start_work_command(raw_args: str, *, workspace: Path | None = None) -> str:
    _plan_name, _worktree, json_mode = _parse_args(raw_args)
    payload = build_start_work_payload(raw_args, workspace=workspace)
    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_start_work_text(payload)
