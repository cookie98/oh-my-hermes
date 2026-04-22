from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

try:
    from .task_sessions import normalize_task_sessions
    from .worker_orchestration import normalize_worker_orchestration
except ImportError:  # pragma: no cover - support direct module imports in tests
    from task_sessions import normalize_task_sessions
    from worker_orchestration import normalize_worker_orchestration

STATE_RELATIVE_PATH = Path('.omh/state/atlas-state.json')
PLAN_DIR_RELATIVE_PATH = Path('.omh/plans')

VALID_LIFECYCLES = {'active', 'blocked', 'complete', 'failed', 'cancelled'}
_INACTIVE_TASK_SESSION_STATUSES = {'completed', 'cancelled', 'done'}
_TERMINAL_TASK_SESSION_STATUSES = {'completed', 'cancelled', 'done'}


@dataclass(frozen=True)
class PlanProgress:
    total: int
    completed: int
    is_complete: bool


@dataclass(frozen=True)
class AtlasStateSnapshot:
    workspace: Path
    state_path: Path
    has_state: bool
    lifecycle: str | None
    posture: str
    resumable: bool
    state: Dict[str, Any] | None
    progress: PlanProgress | None
    active_task_slugs: List[str]
    warnings: List[str]
    errors: List[str]
    consistency_warnings: List[str]


def get_workspace_root() -> Path:
    raw = os.environ.get('TERMINAL_CWD') or os.getcwd()
    return Path(raw).expanduser().resolve()


def get_state_path(workspace: Path | None = None) -> Path:
    root = workspace or get_workspace_root()
    return root / STATE_RELATIVE_PATH


def get_plan_dir(workspace: Path | None = None) -> Path:
    root = workspace or get_workspace_root()
    return root / PLAN_DIR_RELATIVE_PATH


def discover_canonical_plans(workspace: Path | None = None) -> List[Path]:
    plan_dir = get_plan_dir(workspace)
    if not plan_dir.exists() or not plan_dir.is_dir():
        return []
    return sorted(
        [p for p in plan_dir.glob('*.md') if p.is_file()],
        key=lambda p: p.name.lower(),
    )


def _normalize_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(raw)
    if not isinstance(state.get('session_ids'), list):
        state['session_ids'] = []
    if not isinstance(state.get('session_origins'), dict):
        state['session_origins'] = {}
    if not isinstance(state.get('task_sessions'), dict):
        state['task_sessions'] = {}
    state['task_sessions'] = normalize_task_sessions(state.get('task_sessions') or {})
    state['worker_orchestration'] = normalize_worker_orchestration(state.get('worker_orchestration') or {})
    return state


def _count_checkboxes(plan_path: Path) -> PlanProgress:
    try:
        text = plan_path.read_text(encoding='utf-8')
    except OSError:
        return PlanProgress(total=0, completed=0, is_complete=False)

    checked = 0
    unchecked = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('- [x]') or stripped.startswith('- [X]'):
            checked += 1
        elif stripped.startswith('- [ ]'):
            unchecked += 1
    total = checked + unchecked
    return PlanProgress(total=total, completed=checked, is_complete=(total > 0 and checked == total))


def _derive_active_task_slugs(task_sessions: Dict[str, Any], limit: int = 3) -> List[str]:
    slugs: List[str] = []
    seen: set[str] = set()

    for key, payload in task_sessions.items():
        status = None
        slug = str(key).strip()
        if isinstance(payload, dict):
            raw_status = payload.get('status')
            status = str(raw_status).strip().lower() if raw_status is not None else None
            slug = str(payload.get('task_slug') or payload.get('slug') or payload.get('task') or key).strip()

        if not slug or slug in seen:
            continue
        if status in _INACTIVE_TASK_SESSION_STATUSES:
            continue

        seen.add(slug)
        slugs.append(slug)
        if len(slugs) >= limit:
            break

    return slugs


def _task_sessions_terminal(task_sessions: Dict[str, Any]) -> bool:
    if not task_sessions:
        return False

    for payload in task_sessions.values():
        status = None
        if isinstance(payload, dict):
            raw_status = payload.get('status')
            status = str(raw_status).strip().lower() if raw_status is not None else None
        if status not in _TERMINAL_TASK_SESSION_STATUSES:
            return False

    return True


def _check_state_consistency(state: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    task_sessions = state.get('task_sessions') if isinstance(state.get('task_sessions'), dict) else {}
    worker_orchestration = state.get('worker_orchestration') if isinstance(state.get('worker_orchestration'), dict) else {}
    worker_sessions = worker_orchestration.get('worker_sessions') if isinstance(worker_orchestration.get('worker_sessions'), dict) else {}

    for slug, payload in task_sessions.items():
        if not isinstance(payload, dict):
            continue

        task_status = str(payload.get('status') or '').strip().lower()
        session_id = str(payload.get('session_id') or '').strip()
        if not session_id:
            continue

        worker = worker_sessions.get(session_id)
        worker_status = str(worker.get('status') or '').strip().lower() if isinstance(worker, dict) else None

        if worker is None and task_status in {'running', 'dispatched'}:
            warnings.append(f"Task '{slug}' is {task_status} but has no worker session")
        elif task_status in {'completed', 'cancelled'} and worker_status in {'running', 'dispatched'}:
            warnings.append(f"Task '{slug}' is {task_status} but worker '{session_id}' is still {worker_status}")
        elif task_status in {'running', 'dispatched'} and worker_status in {'completed', 'failed', 'lost'}:
            warnings.append(f"Task '{slug}' is {task_status} but worker '{session_id}' is already {worker_status}")

    return warnings


def read_atlas_state(workspace: Path | None = None) -> AtlasStateSnapshot:
    root = workspace or get_workspace_root()
    state_path = get_state_path(root)
    warnings: List[str] = []
    errors: List[str] = []
    consistency_warnings: List[str] = []

    if not state_path.exists():
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=False,
            lifecycle=None,
            posture='idle',
            resumable=False,
            state=None,
            progress=None,
            active_task_slugs=[],
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    try:
        raw = json.loads(state_path.read_text(encoding='utf-8'))
    except Exception as exc:
        errors.append(f'malformed state: {exc}')
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=True,
            lifecycle=None,
            posture='broken',
            resumable=False,
            state=None,
            progress=None,
            active_task_slugs=[],
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    if not isinstance(raw, dict):
        errors.append('state is not a JSON object')
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=True,
            lifecycle=None,
            posture='broken',
            resumable=False,
            state=None,
            progress=None,
            active_task_slugs=[],
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    state = _normalize_state(raw)
    consistency_warnings = _check_state_consistency(state)
    task_sessions = state.get('task_sessions') or {}
    active_task_slugs = _derive_active_task_slugs(task_sessions)
    task_sessions_terminal = _task_sessions_terminal(task_sessions)
    lifecycle = state.get('status') if isinstance(state.get('status'), str) else None
    if lifecycle is not None and lifecycle not in VALID_LIFECYCLES:
        errors.append(f'invalid lifecycle: {lifecycle}')
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=True,
            lifecycle=lifecycle,
            posture='broken',
            resumable=False,
            state=state,
            progress=None,
            active_task_slugs=active_task_slugs,
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    active_plan_raw = state.get('active_plan')
    if not isinstance(active_plan_raw, str) or not active_plan_raw.strip():
        errors.append('missing active_plan')
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=True,
            lifecycle=lifecycle,
            posture='broken',
            resumable=False,
            state=state,
            progress=None,
            active_task_slugs=active_task_slugs,
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    active_plan = Path(active_plan_raw).expanduser()
    if not active_plan.is_absolute():
        active_plan = (root / active_plan).resolve()
    if not active_plan.exists():
        errors.append(f'missing plan file: {active_plan}')
        return AtlasStateSnapshot(
            workspace=root,
            state_path=state_path,
            has_state=True,
            lifecycle=lifecycle,
            posture='broken',
            resumable=False,
            state=state,
            progress=None,
            active_task_slugs=active_task_slugs,
            warnings=warnings,
            errors=errors,
            consistency_warnings=consistency_warnings,
        )

    progress = _count_checkboxes(active_plan)
    worktree_path = state.get('worktree_path')
    if isinstance(worktree_path, str) and worktree_path.strip():
        resolved_worktree_path = Path(worktree_path).expanduser()
        if not resolved_worktree_path.is_absolute():
            resolved_worktree_path = (root / resolved_worktree_path).resolve()
        if not resolved_worktree_path.exists():
            errors.append(f'missing worktree_path: {worktree_path}')
            return AtlasStateSnapshot(
                workspace=root,
                state_path=state_path,
                has_state=True,
                lifecycle=lifecycle,
                posture='broken',
                resumable=False,
                state=state,
                progress=progress,
                active_task_slugs=active_task_slugs,
                warnings=warnings,
                errors=errors,
                consistency_warnings=consistency_warnings,
            )

    last_handoff = state.get('last_handoff')
    if isinstance(last_handoff, str) and last_handoff.strip():
        handoff_path = Path(last_handoff).expanduser()
        if not handoff_path.is_absolute():
            handoff_path = (root / handoff_path).resolve()
        if not handoff_path.exists():
            warnings.append(f'missing last_handoff: {last_handoff}')

    posture = lifecycle or 'broken'
    if lifecycle in {'active', 'blocked'} and progress.is_complete:
        posture = 'stale'
    elif lifecycle == 'complete' and not (progress.is_complete or task_sessions_terminal):
        posture = 'stale'
    elif lifecycle in {'failed', 'cancelled'}:
        posture = lifecycle
    elif lifecycle in {'active', 'blocked', 'complete'}:
        posture = lifecycle
    elif lifecycle is None:
        posture = 'broken'

    resumable = posture in {'active', 'blocked'} and not progress.is_complete

    return AtlasStateSnapshot(
        workspace=root,
        state_path=state_path,
        has_state=True,
        lifecycle=lifecycle,
        posture=posture,
        resumable=resumable,
        state=state,
        progress=progress,
        active_task_slugs=active_task_slugs,
        warnings=warnings,
        errors=errors,
        consistency_warnings=consistency_warnings,
    )
