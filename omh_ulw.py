from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .intent_gate import IntentDecision, classify_intent, extract_intent_payload
from .omh_exec import handle_omh_exec_command
from .omh_plan import build_plan_payload, render_plan_text
from .omh_resume import build_resume_payload, render_resume_text
from .omh_start_work import build_start_work_payload, render_start_work_text
from .omh_status import build_status_payload, render_status_text
from .research_lane import build_research_lane_payload, render_research_lane_text
from .route_resolver import RouteDecision, resolve_route

MODE_MARKER = '<oh-my-hermes-mode>'
ULW_MARKER = '<omh-ulw>'


def should_activate(user_message: str, config: Dict[str, Any]) -> bool:
    lowered = (user_message or '').lower()
    for keyword in config.get('trigger_keywords') or []:
        if str(keyword).lower() in lowered:
            return True
    return lowered.strip().startswith('omh-ulw') or lowered.strip().startswith('/omh-ulw')


def build_ulw_context(*, user_message: str, config: Dict[str, Any], workspace: Path | None = None) -> str:
    intent: IntentDecision = classify_intent(user_message)
    route: RouteDecision = resolve_route(intent, workspace=workspace)
    snapshot = route.state_snapshot

    progress_line = 'unknown'
    if snapshot.progress is not None:
        progress_line = f'{snapshot.progress.completed}/{snapshot.progress.total}'

    lines = [
        MODE_MARKER,
        ULW_MARKER,
        'OMH ultrawork mode is active.',
        'This is a Hermes-first orchestration path. Claude Code planning is optional, not mandatory.',
        '',
        f'Intent Gate: {intent.intent}',
        f'Reason: {intent.reason}',
        f'Normalized Request: {intent.normalized_request or extract_intent_payload(user_message) or user_message.strip()}',
        f'Route: {route.route}',
        f'Route Summary: {route.summary}',
        '',
        'Routing contract:',
        '- status -> inspect posture only',
        '- research/investigation/evaluation -> parallel research lane, no blind implementation',
        '- implementation/fix + resumable state -> resume current execution',
        '- implementation/fix + canonical plan -> start work from existing plan',
        '- implementation/fix + no plan -> create plan, then start work',
        '',
        'Current OMH workspace signals:',
        f'- workspace: {snapshot.workspace}',
        f'- has_state: {snapshot.has_state}',
        f'- lifecycle: {snapshot.lifecycle or "none"}',
        f'- posture: {snapshot.posture}',
        f'- resumable: {"yes" if snapshot.resumable else "no"}',
        f'- progress: {progress_line}',
    ]

    if route.canonical_plans:
        lines.append('- canonical_plans: ' + ', '.join(p.stem for p in route.canonical_plans[:5]))

    if snapshot.active_task_slugs:
        lines.append('- active_task_slugs: ' + ', '.join(snapshot.active_task_slugs))

    if route.next_commands:
        lines.append('- preferred_internal_commands: ' + ' -> '.join(route.next_commands))

    if snapshot.warnings:
        lines.append('Warnings:')
        lines.extend(f'- {item}' for item in snapshot.warnings)
    if snapshot.errors:
        lines.append('Errors:')
        lines.extend(f'- {item}' for item in snapshot.errors)

    lines.extend([
        '',
        'Operating rules:',
        '- Classify intent before acting.',
        '- Do not force implementation for research/evaluation requests.',
        '- Prefer Hermes-native planning and routing first.',
        '- Preserve planning/execution separation internally.',
        '- Verify with evidence before claiming completion.',
    ])

    max_chars = int(config.get('max_instruction_chars', 2400) or 2400)
    return '\n'.join(lines)[:max_chars].rstrip()


def handle_omh_ulw_command(raw_args: str, *, ctx: Any | None = None, workspace: Path | None = None) -> str:
    args = (raw_args or '').strip()
    if not args:
        return 'Usage: `/omh-ulw <intent...>`'

    intent = classify_intent(args)
    route = resolve_route(intent, workspace=workspace)

    if route.route == 'omh-status':
        payload = build_status_payload(workspace=workspace)
        return render_status_text(payload)

    if route.route == 'omh-exec':
        exec_args = args if intent.intent == 'open-ended' else ''
        return handle_omh_exec_command(exec_args, workspace=workspace)

    if route.route == 'omh-resume':
        payload = build_resume_payload('', workspace=workspace)
        return render_resume_text(payload)

    if route.route == 'omh-start-work':
        payload = build_start_work_payload('', workspace=workspace)
        return render_start_work_text(payload)

    if route.route == 'omh-plan -> omh-start-work':
        plan_payload = build_plan_payload(args, workspace=workspace)
        plan_text = render_plan_text(plan_payload)
        start_payload = build_start_work_payload(plan_payload['plan']['name'], workspace=workspace)
        start_text = render_start_work_text(start_payload)
        return f'{plan_text}\n\n---\n\n{start_text}'

    if route.route == 'research-lane':
        payload = build_research_lane_payload(args, workspace=workspace)
        if ctx is not None and hasattr(ctx, 'inject_message'):
            for item in payload['specialist_lanes']:
                ctx.inject_message(item['message'])
            return 'Queued OMH ultrawork research lanes: explore, librarian, oracle.'
        return render_research_lane_text(payload)

    return f'Unhandled OMH ultrawork route: {route.route}'
