from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict

from .atlas_state import AtlasStateSnapshot, get_state_path, read_atlas_state
from .worker_orchestration import build_worker_supervision_summary, record_worker_supervision_poll

ProcessPoller = Callable[[str], Dict[str, Any] | None]


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = get_state_path(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=state_path.parent, delete=False) as handle:
        handle.write(json.dumps(state, ensure_ascii=False, indent=2))
        handle.write('\n')
        temp_path = Path(handle.name)
    temp_path.replace(state_path)
    return state_path


def refresh_detached_worker_supervision(
    workspace: Path,
    *,
    process_poller: ProcessPoller | None = None,
) -> AtlasStateSnapshot:
    snapshot = read_atlas_state(workspace)
    if not snapshot.has_state or not snapshot.state or process_poller is None:
        return snapshot

    supervision = build_worker_supervision_summary((snapshot.state or {}).get('worker_orchestration') or {})
    if not supervision:
        return snapshot
    if not supervision.get('detached') or supervision.get('status') != 'running' or not supervision.get('session_id'):
        return snapshot

    try:
        poll_result = process_poller(str(supervision['session_id']))
    except Exception as exc:
        return replace(snapshot, warnings=[*snapshot.warnings, f'detached supervision refresh failed: {exc}'])
    if not isinstance(poll_result, dict):
        return snapshot

    status = poll_result.get('status')
    if status is None:
        return snapshot

    next_state = record_worker_supervision_poll(
        snapshot.state,
        session_id=str(supervision['session_id']),
        status=status,
        observation=poll_result.get('observation'),
        exit_code=poll_result.get('exit_code'),
    )
    _write_state(workspace, next_state)
    return read_atlas_state(workspace)
