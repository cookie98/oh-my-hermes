from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from .atlas_state import get_state_path, get_workspace_root, read_atlas_state
from .verify_fix import record_verification_result


def _parse_args(raw_args: str) -> Tuple[str | None, str | None, bool]:
    tokens = (raw_args or '').strip().split()
    json_mode = False
    kept: list[str] = []
    for token in tokens:
        if token == '--json':
            json_mode = True
        else:
            kept.append(token)
    if not kept:
        return None, None, json_mode
    outcome = kept[0].strip().lower()
    summary = ' '.join(kept[1:]).strip() or None
    return outcome, summary, json_mode


def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = get_state_path(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path


def build_verify_payload(raw_args: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    outcome, summary, _json_mode = _parse_args(raw_args)
    if outcome not in {'pass', 'fail'}:
        return {
            'mode': 'usage',
            'workspace': str(root),
            'usage': 'Usage: `/omh-verify <pass|fail> [summary...]`',
        }

    snapshot = read_atlas_state(root)
    if not snapshot.has_state or not snapshot.state:
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'No OMH execution state was found to verify. Run `omh-start-work` first.',
        }

    current_stage = str(snapshot.state.get('current_stage') or '').strip().lower()
    if current_stage != 'verify':
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': f'OMH verification can run only from `verify` stage (current: {current_stage or "unknown"}).',
        }

    next_state = record_verification_result(
        snapshot.state,
        workspace=root,
        passed=(outcome == 'pass'),
        summary=summary,
    )
    state_path = _write_state(root, next_state)
    return {
        'mode': 'recorded',
        'workspace': str(root),
        'state_path': str(state_path),
        'outcome': outcome,
        'summary': summary,
        'state': next_state,
    }


def render_verify_text(payload: Dict[str, Any]) -> str:
    mode = payload.get('mode')
    if mode == 'usage':
        return str(payload.get('usage'))
    if mode == 'error':
        return str(payload.get('reason'))

    state = payload.get('state') or {}
    outcome = str(payload.get('outcome') or '').strip().lower()
    rendered_outcome = 'passed' if outcome == 'pass' else 'failed' if outcome == 'fail' else (outcome or 'unknown')
    return (
        'Recorded OMH verification result\n\n'
        f'Outcome: {rendered_outcome}\n'
        f'Plan: {state.get("plan_name") or "unknown"}\n'
        f'Lifecycle: {state.get("status") or "unknown"}\n'
        f'Stage: {state.get("current_stage") or "unknown"}\n'
        f'Wave: {state.get("current_wave") if state.get("current_wave") is not None else "unknown"}\n'
        f'Handoff: {state.get("last_handoff") or "none"}'
    )


def handle_omh_verify_command(raw_args: str, *, workspace: Path | None = None) -> str:
    payload = build_verify_payload(raw_args, workspace=workspace)
    outcome, _summary, json_mode = _parse_args(raw_args)
    if json_mode and payload.get('mode') != 'usage':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if json_mode and payload.get('mode') == 'usage' and outcome is None:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_verify_text(payload)
