from __future__ import annotations

from dataclasses import dataclass

from .atlas_state import AtlasStateSnapshot
from .worker_orchestration import build_worker_supervision_summary


@dataclass(frozen=True)
class ContinuationEnforcement:
    active: bool
    strict: bool
    route: str | None
    reason: str
    next_action: str


_SOFT_FALLBACK = ContinuationEnforcement(
    active=False,
    strict=False,
    route=None,
    reason='no active continuation enforcement required',
    next_action='Continue normally.',
)


def build_continuation_enforcement(snapshot: AtlasStateSnapshot) -> ContinuationEnforcement:
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
