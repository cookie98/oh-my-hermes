from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from .atlas_state import get_state_path, get_workspace_root, read_atlas_state
    from .verify_fix import record_verification_result
except ImportError:  # pragma: no cover - support direct module imports in tests
    from atlas_state import get_state_path, get_workspace_root, read_atlas_state
    from verify_fix import record_verification_result


_ACCEPTANCE_PREFIX_RE = re.compile(r'^[-*\s\[\]xX0-9.()]+')
_ACCEPTANCE_TOKEN_RE = re.compile(r'[a-z0-9]+')
_VERIFICATION_ESCALATION_THRESHOLD = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


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



def _normalize_acceptance_item(value: Any) -> str:
    text = str(value or '').strip()
    text = _ACCEPTANCE_PREFIX_RE.sub('', text).strip()
    return text



def _extract_acceptance_items(task_session: Dict[str, Any]) -> list[str]:
    items: list[str] = []
    raw_acceptance = task_session.get('acceptance') or []
    if isinstance(raw_acceptance, (list, tuple, set)):
        candidates = list(raw_acceptance)
    else:
        candidates = str(raw_acceptance).splitlines()
    for candidate in candidates:
        normalized = _normalize_acceptance_item(candidate)
        if normalized:
            items.append(normalized)
    return items



def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        parts = []
        for key in ('summary', 'stdout', 'stderr', 'text', 'output'):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        if parts:
            return '\n'.join(parts)
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    return str(result or '')



def _criterion_matches(criterion: str, result_text: str) -> bool:
    normalized_criterion = criterion.strip().lower()
    normalized_result = result_text.strip().lower()
    if not normalized_criterion:
        return True
    if normalized_criterion in normalized_result:
        return True
    criterion_tokens = [token for token in _ACCEPTANCE_TOKEN_RE.findall(normalized_criterion) if len(token) >= 3 or token.isdigit()]
    if not criterion_tokens:
        return normalized_criterion in normalized_result
    result_tokens = set(_ACCEPTANCE_TOKEN_RE.findall(normalized_result))
    return all(token in result_tokens for token in criterion_tokens)



def _verify_acceptance_criteria(task_session: Dict[str, Any], result: Any) -> Dict[str, Any]:
    acceptance_items = _extract_acceptance_items(task_session)
    verification_text = _result_text(result)
    matched: list[str] = []
    missing: list[str] = []

    for item in acceptance_items:
        if _criterion_matches(item, verification_text):
            matched.append(item)
        else:
            missing.append(item)

    if not acceptance_items:
        status = 'VERIFIED'
    elif missing and matched:
        status = 'PARTIAL'
    elif missing:
        status = 'FAILED'
    else:
        status = 'VERIFIED'

    evidence = [
        f'matched: {item}' for item in matched
    ] + [
        f'missing: {item}' for item in missing
    ]
    if verification_text.strip():
        evidence.append(f'source: {verification_text.strip()}')

    return {
        'status': status,
        'matched': matched,
        'missing': missing,
        'evidence': evidence,
    }



def _resolve_verification_target_task_slug(state: Dict[str, Any]) -> str | None:
    task_sessions = state.get('task_sessions') or {}
    if not isinstance(task_sessions, dict) or not task_sessions:
        return None

    completed: list[tuple[str, str]] = []
    for slug, session in task_sessions.items():
        if not isinstance(session, dict):
            continue
        if str(session.get('status') or '').strip().lower() == 'completed':
            completed_at = str(session.get('completed_at') or '')
            completed.append((completed_at, slug))
    if completed:
        completed.sort()
        return completed[-1][1]

    for slug, session in task_sessions.items():
        if isinstance(session, dict) and str(session.get('status') or '').strip().lower() in {'in_progress', 'blocked'}:
            return slug
    return next(iter(task_sessions.keys()), None)



def record_task_acceptance_verification(
    state: Dict[str, Any],
    *,
    task_slug: str,
    result: Any,
    now: str | None = None,
) -> Dict[str, Any]:
    stamp = now or _now_iso()
    next_state = dict(state)
    task_sessions = dict(next_state.get('task_sessions') or {})
    if task_slug not in task_sessions:
        raise KeyError(f'unknown task session: {task_slug}')

    session = dict(task_sessions[task_slug] or {})
    verdict = _verify_acceptance_criteria(session, result)
    prior_retry_count = int(session.get('verification_retry_count') or 0)
    if verdict['status'] == 'VERIFIED':
        retry_count = 0
        escalation_required = False
    else:
        retry_count = prior_retry_count + 1
        escalation_required = verdict['status'] == 'FAILED' and retry_count >= _VERIFICATION_ESCALATION_THRESHOLD

    session['verification_status'] = verdict['status']
    session['verification_evidence'] = verdict['evidence']
    session['verification_matched'] = verdict['matched']
    session['verification_missing'] = verdict['missing']
    session['verification_retry_count'] = retry_count
    session['verification_escalation_required'] = escalation_required
    session['verification_updated_at'] = stamp
    task_sessions[task_slug] = session
    next_state['task_sessions'] = task_sessions
    next_state['updated_at'] = stamp
    return next_state



def _write_state(workspace: Path, state: Dict[str, Any]) -> Path:
    state_path = get_state_path(workspace)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state_path



def build_verify_payload(raw_args: str = '', *, workspace: Path | None = None, task_label: str | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    if task_label is not None:
        normalized_label = ' '.join(str(task_label or '').split()).strip() or 'unknown'
        return {
            'mode': 'usage',
            'workspace': str(root),
            'task_label': normalized_label,
            'usage': f'OMH verification requested for task: {normalized_label}. Use `omh-verify <pass|fail> [summary...]` when ready.',
        }

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

    next_state = snapshot.state
    target_task_slug = _resolve_verification_target_task_slug(next_state)
    if target_task_slug is not None:
        next_state = record_task_acceptance_verification(
            next_state,
            task_slug=target_task_slug,
            result={'summary': summary or '', 'outcome': outcome},
        )

    next_state = record_verification_result(
        next_state,
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
