from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from .atlas_state import AtlasStateSnapshot
from .continuation_enforcement import (
    IdleContinuationPressure,
    build_continuation_enforcement,
    build_idle_continuation_pressure,
)
from .worker_orchestration import (
    build_worker_reattachment_summary,
    build_worker_result_bridge,
    build_worker_supervision_summary,
)

_CONTINUATION_WORD_RE = re.compile(r'\b(?:continue|resume|keep going|next task|next step)\b', re.IGNORECASE)
_CONTINUATION_KOREAN_CUES = (
    '계속해',
    '계속하자',
    '이어가자',
    '다음 작업',
    '다음 구현 작업',
    '이어서 진행',
)
_EXACT_CONTINUATION_MESSAGES = {'계속', '이어서', 'resume', 'continue'}
_FIRST_TURN_GREETING_RE = re.compile(r'^(?:hi|hello|hey|yo|sup|안녕|하이|헬로)(?:\s+there)?[!.?]*$', re.IGNORECASE)


def is_continuation_prompt(user_message: str) -> bool:
    text = (user_message or '').strip()
    if not text:
        return False

    lowered = text.lower()
    if lowered in _EXACT_CONTINUATION_MESSAGES:
        return True

    if _CONTINUATION_WORD_RE.search(text):
        return True

    return any(cue in lowered for cue in _CONTINUATION_KOREAN_CUES)



def should_inject_continuation_context(*, user_message: str, is_first_turn: bool, resumable: bool) -> bool:
    if not resumable:
        return False
    if is_continuation_prompt(user_message):
        return True
    if not is_first_turn:
        return False
    text = (user_message or '').strip()
    if not text:
        return True
    return bool(_FIRST_TURN_GREETING_RE.match(text))



def should_inject_idle_continuation_context(*, user_message: str, is_first_turn: bool, idle_pressure: IdleContinuationPressure) -> bool:
    if not is_first_turn:
        return False
    if not idle_pressure.active or not idle_pressure.due:
        return False
    return not is_continuation_prompt(user_message)



def _resolve_plan_name(snapshot: AtlasStateSnapshot) -> str:
    state = snapshot.state or {}
    plan_name = state.get('plan_name')
    if isinstance(plan_name, str) and plan_name.strip():
        return plan_name.strip()

    active_plan_raw = state.get('active_plan')
    if isinstance(active_plan_raw, str) and active_plan_raw.strip():
        return Path(active_plan_raw).stem

    return 'unknown'



def _resolve_stage(snapshot: AtlasStateSnapshot) -> str:
    state = snapshot.state or {}
    stage = state.get('current_stage')
    if isinstance(stage, str) and stage.strip():
        return stage.strip()
    if snapshot.lifecycle:
        return snapshot.lifecycle
    return 'unknown'



def _resolve_wave(snapshot: AtlasStateSnapshot) -> str:
    state = snapshot.state or {}
    wave = state.get('current_wave')
    if wave is None:
        return 'unknown'
    return str(wave)



def _resolve_current_task_slug(snapshot: AtlasStateSnapshot) -> str:
    state = snapshot.state or {}
    orchestration = state.get('worker_orchestration') if isinstance(state.get('worker_orchestration'), dict) else {}
    if isinstance(orchestration, dict):
        current_task_slug = orchestration.get('current_task_slug')
        if isinstance(current_task_slug, str) and current_task_slug.strip():
            return current_task_slug.strip()

    current_task_slug = state.get('current_task_slug')
    if isinstance(current_task_slug, str) and current_task_slug.strip():
        return current_task_slug.strip()

    if snapshot.active_task_slugs:
        return snapshot.active_task_slugs[0]

    return 'none'



def _format_progress(snapshot: AtlasStateSnapshot) -> str | None:
    if snapshot.progress is None:
        return None
    return f'{snapshot.progress.completed}/{snapshot.progress.total}'



def describe_idle_continuation_lines(
    snapshot: AtlasStateSnapshot,
    *,
    now: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    pressure = build_idle_continuation_pressure(snapshot, now=now, config=config)
    if not pressure.active:
        return []

    status = 'due' if pressure.due else ('cooldown' if pressure.cooldown_active else 'waiting')
    lines = [
        f'Idle Continuation: {status}',
        f'Idle Age: {pressure.idle_minutes}m',
        f'Idle Threshold: {pressure.threshold_minutes}m',
    ]
    if pressure.escalation_active:
        lines.append('Idle Escalation: active')
    if pressure.cooldown_active:
        lines.append(f'Idle Cooldown Remaining: {pressure.cooldown_remaining_minutes}m')
    return lines



def build_continuation_context(
    snapshot: AtlasStateSnapshot,
    *,
    now: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> str:
    plan_name = _resolve_plan_name(snapshot)
    stage = _resolve_stage(snapshot)
    wave = _resolve_wave(snapshot)
    current_task = _resolve_current_task_slug(snapshot)
    progress = _format_progress(snapshot)
    worker_reattachment = build_worker_reattachment_summary((snapshot.state or {}).get('worker_orchestration') or {})
    worker_supervision = build_worker_supervision_summary((snapshot.state or {}).get('worker_orchestration') or {})
    worker_result_bridge = build_worker_result_bridge((snapshot.state or {}).get('worker_orchestration') or {})
    continuation_enforcement = build_continuation_enforcement(snapshot)
    idle_lines = describe_idle_continuation_lines(snapshot, now=now, config=config)

    lines = [
        'OMH continuation reminder.',
    ]
    if progress is not None:
        lines.append(f'Progress: {progress}')
    lines.extend([
        f'Plan: {plan_name}',
        f'Stage: {stage}',
        f'Wave: {wave}',
        f'Current Task: {current_task}',
    ])
    if worker_reattachment and worker_reattachment.get('active_worker_id'):
        lines.extend([
            f'Worker Reattachment: {worker_reattachment.get("active_worker_id")}',
            f'Worker Status: {worker_reattachment.get("status") or "unknown"}',
        ])
    if worker_supervision and worker_supervision.get('session_id'):
        lines.extend([
            f'Detached Worker Session: {worker_supervision.get("session_id")}',
            f'Detached Worker Status: {worker_supervision.get("status") or "unknown"}',
        ])
    if worker_result_bridge and worker_result_bridge.get('ready'):
        lines.extend([
            f'Worker Result Bridge: ready (recommended={worker_result_bridge.get("recommended_action") or "unknown"})',
            'Suggested Command: omh-exec accept',
        ])
    if continuation_enforcement.active:
        lines.extend([
            f'Continuation Enforcement: {"strict" if continuation_enforcement.strict else "soft"}',
            f'Next Action: {continuation_enforcement.next_action}',
        ])
    lines.extend(idle_lines)
    lines.append('Continue from the current OMH execution state instead of restarting the workflow.')
    return '\n'.join(lines)
