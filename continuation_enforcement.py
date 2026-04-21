from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .atlas_state import AtlasStateSnapshot
from .worker_orchestration import build_worker_result_bridge, build_worker_supervision_summary

DEFAULT_SOFT_IDLE_THRESHOLD_MINUTES = 60
DEFAULT_STRICT_IDLE_THRESHOLD_MINUTES = 15
DEFAULT_IDLE_COOLDOWN_MINUTES = 30
DEFAULT_IDLE_ESCALATION_NUDGE_THRESHOLD = 2


@dataclass(frozen=True)
class ContinuationEnforcement:
    active: bool
    strict: bool
    route: str | None
    reason: str
    next_action: str


@dataclass(frozen=True)
class IdleContinuationPressure:
    active: bool
    due: bool
    level: str
    idle_minutes: int
    threshold_minutes: int
    cooldown_active: bool
    cooldown_remaining_minutes: int
    nudge_count: int
    escalation_threshold: int
    escalation_active: bool
    reason: str


_SOFT_FALLBACK = ContinuationEnforcement(
    active=False,
    strict=False,
    route=None,
    reason='no active continuation enforcement required',
    next_action='Continue normally.',
)


_INACTIVE_IDLE_PRESSURE = IdleContinuationPressure(
    active=False,
    due=False,
    level='soft',
    idle_minutes=0,
    threshold_minutes=DEFAULT_SOFT_IDLE_THRESHOLD_MINUTES,
    cooldown_active=False,
    cooldown_remaining_minutes=0,
    nudge_count=0,
    escalation_threshold=DEFAULT_IDLE_ESCALATION_NUDGE_THRESHOLD,
    escalation_active=False,
    reason='idle continuation pressure is not active',
)


def _build_base_continuation_enforcement(snapshot: AtlasStateSnapshot) -> ContinuationEnforcement:
    if not snapshot.has_state or not snapshot.state or not snapshot.resumable:
        return _SOFT_FALLBACK

    state = snapshot.state or {}
    stage = str(state.get('current_stage') or '').strip().lower()
    worker_supervision = build_worker_supervision_summary(state.get('worker_orchestration') or {}) or {}

    if worker_supervision.get('detached') and worker_supervision.get('status') == 'running':
        session_id = worker_supervision.get('session_id') or 'unknown'
        return ContinuationEnforcement(
            active=True,
            strict=True,
            route='omh-status',
            reason='detached worker session is still running',
            next_action=f'Detached worker session is still running (session: {session_id}). Check `omh-status` before starting unrelated work.',
        )

    if stage == 'verify':
        return ContinuationEnforcement(
            active=True,
            strict=True,
            route='omh-exec',
            reason='verify stage must be resolved before unrelated work',
            next_action='Run `omh-verify <pass|fail> [summary...]` to resolve the current verify stage before starting unrelated work.',
        )

    if stage == 'fix':
        return ContinuationEnforcement(
            active=True,
            strict=True,
            route='omh-exec',
            reason='fix stage must be resolved before unrelated work',
            next_action='Run `omh-fix [summary...]` to resolve the current fix stage before starting unrelated work.',
        )

    worker_mode = str(((state.get('worker_orchestration') or {}).get('mode')) or '').strip().lower()
    if worker_mode == 'awaiting-worker-result':
        worker_result_bridge = build_worker_result_bridge(state.get('worker_orchestration') or {})
        if worker_result_bridge:
            recommended_action = worker_result_bridge.get('recommended_action') or 'accept'
            summary = worker_result_bridge.get('summary') or 'detached worker result is ready'
            return ContinuationEnforcement(
                active=True,
                strict=True,
                route='omh-exec',
                reason='worker result bridge is ready and must be resolved before unrelated work',
                next_action=f'Run `omh-exec accept` to adopt the detached worker result before starting unrelated work (recommended: {recommended_action}; summary: {summary}).',
            )
        return ContinuationEnforcement(
            active=True,
            strict=True,
            route='omh-exec',
            reason='worker result must be resolved before unrelated work',
            next_action='Run `omh-exec complete [summary...]` or `omh-exec block [summary...]` to resolve the current worker result before starting unrelated work.',
        )

    return ContinuationEnforcement(
        active=True,
        strict=False,
        route='omh-exec',
        reason='resumable execution exists',
        next_action='Run `omh-exec` to continue the current OMH execution before starting unrelated work.',
    )



def build_continuation_enforcement(snapshot: AtlasStateSnapshot) -> ContinuationEnforcement:
    base = _build_base_continuation_enforcement(snapshot)
    if not base.active or base.strict:
        return base

    idle_pressure = _build_idle_continuation_pressure(snapshot, enforcement=base, config=None)
    if idle_pressure.escalation_active:
        return ContinuationEnforcement(
            active=True,
            strict=True,
            route='omh-exec',
            reason='ignored idle continuation nudges escalated resumable execution into strict continuation enforcement',
            next_action='Run `omh-exec` to continue the current OMH execution before starting unrelated work.',
        )
    return base



def _parse_iso_timestamp(raw: Any) -> datetime | None:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _resolve_now(now: str | datetime | None) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    parsed = _parse_iso_timestamp(now)
    if parsed is not None:
        return parsed
    return datetime.now(timezone.utc)



def _resolve_idle_settings(config: Mapping[str, Any] | None, *, strict: bool) -> tuple[int, int, int]:
    source: Mapping[str, Any] = config or {}
    nested = source.get('idle_continuation') if isinstance(source, Mapping) else None
    settings = nested if isinstance(nested, Mapping) else source

    soft_threshold = int(settings.get('soft_threshold_minutes', DEFAULT_SOFT_IDLE_THRESHOLD_MINUTES) or DEFAULT_SOFT_IDLE_THRESHOLD_MINUTES)
    strict_threshold = int(settings.get('strict_threshold_minutes', DEFAULT_STRICT_IDLE_THRESHOLD_MINUTES) or DEFAULT_STRICT_IDLE_THRESHOLD_MINUTES)
    cooldown = int(settings.get('cooldown_minutes', DEFAULT_IDLE_COOLDOWN_MINUTES) or DEFAULT_IDLE_COOLDOWN_MINUTES)
    escalation_threshold = int(settings.get('escalation_nudge_threshold', DEFAULT_IDLE_ESCALATION_NUDGE_THRESHOLD) or DEFAULT_IDLE_ESCALATION_NUDGE_THRESHOLD)
    threshold = strict_threshold if strict else soft_threshold
    return max(1, threshold), max(0, cooldown), max(1, escalation_threshold)



def _build_idle_continuation_pressure(
    snapshot: AtlasStateSnapshot,
    *,
    enforcement: ContinuationEnforcement,
    now: str | datetime | None = None,
    config: Mapping[str, Any] | None = None,
) -> IdleContinuationPressure:
    if not snapshot.has_state or not snapshot.state or not snapshot.resumable:
        return _INACTIVE_IDLE_PRESSURE

    threshold_minutes, cooldown_minutes, escalation_threshold = _resolve_idle_settings(config, strict=enforcement.strict)
    state = snapshot.state or {}
    current_time = _resolve_now(now)
    activity_time = _parse_iso_timestamp(state.get('updated_at')) or _parse_iso_timestamp(state.get('started_at'))
    continuation_meta = state.get('continuation_enforcement') if isinstance(state.get('continuation_enforcement'), dict) else {}
    idle_meta = continuation_meta.get('idle') if isinstance(continuation_meta.get('idle'), dict) else {}
    nudge_count = max(0, int(idle_meta.get('nudge_count') or 0))
    escalation_active = (not enforcement.strict) and nudge_count >= escalation_threshold
    if activity_time is None:
        return IdleContinuationPressure(
            active=True,
            due=False,
            level='strict' if enforcement.strict else 'soft',
            idle_minutes=0,
            threshold_minutes=threshold_minutes,
            cooldown_active=False,
            cooldown_remaining_minutes=0,
            nudge_count=nudge_count,
            escalation_threshold=escalation_threshold,
            escalation_active=escalation_active,
            reason='idle continuation pressure is waiting for a valid activity timestamp',
        )

    idle_minutes = max(0, int((current_time - activity_time).total_seconds() // 60))
    last_nudged_at = _parse_iso_timestamp(idle_meta.get('last_nudged_at'))
    cooldown_remaining_minutes = 0
    if last_nudged_at is not None and cooldown_minutes > 0:
        elapsed_since_nudge = max(0, int((current_time - last_nudged_at).total_seconds() // 60))
        cooldown_remaining_minutes = max(0, cooldown_minutes - elapsed_since_nudge)

    cooldown_active = cooldown_remaining_minutes > 0
    due = idle_minutes >= threshold_minutes and not cooldown_active
    level = 'strict' if enforcement.strict else 'soft'

    if escalation_active:
        reason = f'idle continuation escalation is active after {nudge_count} ignored nudges'
    elif due:
        reason = f'idle continuation pressure is due after {idle_minutes}m idle'
    elif cooldown_active:
        reason = f'idle continuation pressure is cooling down for {cooldown_remaining_minutes}m'
    else:
        reason = f'idle continuation pressure is waiting for the {threshold_minutes}m threshold'

    return IdleContinuationPressure(
        active=True,
        due=due,
        level=level,
        idle_minutes=idle_minutes,
        threshold_minutes=threshold_minutes,
        cooldown_active=cooldown_active,
        cooldown_remaining_minutes=cooldown_remaining_minutes,
        nudge_count=nudge_count,
        escalation_threshold=escalation_threshold,
        escalation_active=escalation_active,
        reason=reason,
    )



def build_idle_continuation_pressure(
    snapshot: AtlasStateSnapshot,
    *,
    now: str | datetime | None = None,
    config: Mapping[str, Any] | None = None,
) -> IdleContinuationPressure:
    base = _build_base_continuation_enforcement(snapshot)
    return _build_idle_continuation_pressure(snapshot, enforcement=base, now=now, config=config)
