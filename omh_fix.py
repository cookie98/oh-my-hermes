from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from .atlas_state import get_state_path, get_workspace_root, read_atlas_state
from .verify_fix import record_fix_result


def _parse_args(raw_args: str) -> Tuple[str | None, bool]:
    tokens = (raw_args or '').strip().split()
    json_mode = False
    kept: list[str] = []
    for token in tokens:
        if token == '--json':
            json_mode = True
        else:
            kept.append(token)
    summary = ' '.join(kept).strip() or None
    return summary, json_mode


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = get_state_path(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def build_fix_payload(raw_args: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    summary, _json_mode = _parse_args(raw_args)
    snapshot = read_atlas_state(root)
    if not snapshot.has_state or not snapshot.state:
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'No OMH execution state was found to remediate. Run `omh-start-work` first.',
        }

    current_stage = str(snapshot.state.get('current_stage') or '').strip().lower()
    if current_stage != 'fix':
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': f'OMH fix can run only from `fix` stage (current: {current_stage or "unknown"}).',
        }

    next_state = record_fix_result(snapshot.state, workspace=root, summary=summary)
    state_path = _write_state(root, next_state)
    return {
        'mode': 'recorded',
        'workspace': str(root),
        'state_path': str(state_path),
        'summary': summary,
        'state': next_state,
    }


def render_fix_text(payload: Dict[str, Any]) -> str:
    if payload.get('mode') == 'error':
        return str(payload.get('reason'))

    state = payload.get('state') or {}
    return (
        'Recorded OMH fix result\n\n'
        f'Plan: {state.get("plan_name") or "unknown"}\n'
        f'Lifecycle: {state.get("status") or "unknown"}\n'
        f'Next Stage: {state.get("current_stage") or "unknown"}\n'
        f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}\n'
        f'Handoff: {state.get("last_handoff") or "none"}'
    )


def handle_omh_fix_command(raw_args: str, *, workspace: Path | None = None) -> str:
    payload = build_fix_payload(raw_args, workspace=workspace)
    _summary, json_mode = _parse_args(raw_args)
    if json_mode and payload.get('mode') != 'error':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_fix_text(payload)
