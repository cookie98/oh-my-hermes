from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from .atlas_state import AtlasStateSnapshot, discover_canonical_plans, read_atlas_state
from .intent_gate import IntentDecision


@dataclass(frozen=True)
class RouteDecision:
    route: str
    summary: str
    next_commands: List[str]
    state_snapshot: AtlasStateSnapshot
    canonical_plans: List[Path]


def resolve_route(intent: IntentDecision, *, workspace: Path | None = None) -> RouteDecision:
    snapshot = read_atlas_state(workspace)
    plans: List[Path] = []

    if intent.intent == 'status':
        return RouteDecision(
            route='omh-status',
            summary='Status intent detected; inspect OMH execution posture only.',
            next_commands=['omh-status'],
            state_snapshot=snapshot,
            canonical_plans=plans,
        )

    if intent.intent in {'research', 'investigation', 'evaluation'}:
        return RouteDecision(
            route='research-lane',
            summary='Non-implementation intent detected; use parallel research/review lane before any code changes.',
            next_commands=[],
            state_snapshot=snapshot,
            canonical_plans=plans,
        )

    if intent.intent == 'open-ended' and snapshot.resumable:
        return RouteDecision(
            route='omh-exec',
            summary='Open-ended follow-up arrived while OMH execution is resumable; continue through the stage-aware exec driver instead of dropping into research by default.',
            next_commands=['omh-exec'],
            state_snapshot=snapshot,
            canonical_plans=plans,
        )

    if intent.intent in {'implementation', 'fix'}:
        if snapshot.resumable:
            return RouteDecision(
                route='omh-exec',
                summary='Active resumable OMH state exists; continue through the stage-aware exec driver rather than bypassing the current stage.',
                next_commands=['omh-exec'],
                state_snapshot=snapshot,
                canonical_plans=plans,
            )

        plans = discover_canonical_plans(snapshot.workspace)
        if plans:
            return RouteDecision(
                route='omh-start-work',
                summary='Canonical plan exists and no resumable execution is active; bootstrap execution from the existing plan.',
                next_commands=['omh-start-work'],
                state_snapshot=snapshot,
                canonical_plans=plans,
            )

        return RouteDecision(
            route='omh-plan -> omh-start-work',
            summary='No canonical plan exists yet; create a plan first, then enter execution automatically.',
            next_commands=['omh-plan', 'omh-start-work'],
            state_snapshot=snapshot,
            canonical_plans=plans,
        )

    return RouteDecision(
        route='research-lane',
        summary='Fallback to research lane because intent could not be resolved safely.',
        next_commands=[],
        state_snapshot=snapshot,
        canonical_plans=plans,
    )
