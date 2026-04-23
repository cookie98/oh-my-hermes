from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _handoff_dir(workspace: Path) -> Path:
    return workspace / '.omh' / 'handoffs'


def _write_handoff(
    *,
    workspace: Path,
    filename: str,
    title: str,
    generated_at: str,
    stage: str,
    outcome: str,
    summary: str | None,
    wave: Any,
) -> Path:
    handoff_dir = _handoff_dir(workspace)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / filename
    body = [
        f'# {title}',
        '',
        f'- Generated At: {generated_at}',
        f'- Stage: {stage}',
        f'- Outcome: {outcome}',
        f'- Wave: {wave if wave is not None else "unknown"}',
    ]
    if summary:
        body.extend(['', '## Summary', '', summary])
    handoff_path.write_text('\n'.join(body).rstrip() + '\n', encoding='utf-8')
    return handoff_path.resolve()


def record_verification_result(
    state: Dict[str, Any],
    *,
    workspace: Path,
    passed: bool,
    summary: str | None = None,
    now: str | None = None,
) -> Dict[str, Any]:
    stamp = now or _now_iso()
    next_state = dict(state)
    current_wave = next_state.get('current_wave') or 1

    lineage = next_state.get('lineage', {})
    total_waves = lineage.get('total_waves', 1)

    if passed:
        handoff_path = _write_handoff(
            workspace=workspace,
            filename='verify.md',
            title='OMH Verify Handoff',
            generated_at=stamp,
            stage='verify',
            outcome='passed',
            summary=summary,
            wave=current_wave,
        )
        next_state['status'] = 'complete'
        next_state['current_stage'] = 'verify'
        next_state['verified_at'] = stamp
    else:
        # Fix stage uses total_waves + 1 as a dedicated wave
        fix_wave = total_waves + 1
        handoff_path = _write_handoff(
            workspace=workspace,
            filename='verify.md',
            title='OMH Verify Handoff',
            generated_at=stamp,
            stage='verify',
            outcome='failed',
            summary=summary,
            wave=fix_wave,
        )
        next_state['status'] = 'active'
        next_state['current_stage'] = 'fix'
        next_state['current_wave'] = fix_wave
        next_state['verification_failed_at'] = stamp

    next_state['last_handoff'] = str(handoff_path)
    next_state['updated_at'] = stamp
    return next_state


def record_fix_result(
    state: Dict[str, Any],
    *,
    workspace: Path,
    summary: str | None = None,
    now: str | None = None,
) -> Dict[str, Any]:
    stamp = now or _now_iso()
    next_state = dict(state)
    lineage = next_state.get('lineage', {})
    total_waves = lineage.get('total_waves', 1)
    current_wave = next_state.get('current_wave') or 1
    handoff_path = _write_handoff(
        workspace=workspace,
        filename='fix.md',
        title='OMH Fix Handoff',
        generated_at=stamp,
        stage='fix',
        outcome='remediated',
        summary=summary,
        wave=current_wave,
    )
    next_state['status'] = 'active'
    next_state['current_stage'] = 'verify'
    # After fix, reset to total_waves (re-verify from last wave)
    next_state['current_wave'] = total_waves
    next_state['fixed_at'] = stamp
    next_state['last_handoff'] = str(handoff_path)
    next_state['updated_at'] = stamp
    return next_state
