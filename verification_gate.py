from __future__ import annotations

from typing import Any, Dict

_UNRESOLVED_VERIFICATION_STATUSES = {'FAILED', 'PARTIAL'}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def collect_unresolved_task_verification_issues(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Return task-level acceptance verification issues that must block completion.

    OMO only proceeds when verification gates are definitively satisfied. A task
    with FAILED/PARTIAL acceptance verification or an explicit escalation flag is
    unresolved and must route the workflow back to review/fix instead of allowing
    a top-level pass or completion bundle.
    """
    issues: list[Dict[str, Any]] = []
    task_sessions = state.get('task_sessions') or {}
    if not isinstance(task_sessions, dict):
        return issues

    for key, raw_session in task_sessions.items():
        if not isinstance(raw_session, dict):
            continue

        verification_status = str(raw_session.get('verification_status') or '').strip().upper()
        escalation_required = bool(raw_session.get('verification_escalation_required'))
        if verification_status not in _UNRESOLVED_VERIFICATION_STATUSES and not escalation_required:
            continue

        task_slug = str(raw_session.get('task_slug') or raw_session.get('slug') or key).strip() or str(key)
        reasons: list[str] = []
        if verification_status in _UNRESOLVED_VERIFICATION_STATUSES:
            reasons.append(verification_status)
        if escalation_required:
            reasons.append('escalation required')

        issues.append({
            'task_slug': task_slug,
            'label': raw_session.get('label') or raw_session.get('title') or task_slug,
            'task_status': raw_session.get('status'),
            'verification_status': verification_status or None,
            'verification_escalation_required': escalation_required,
            'verification_missing': _string_list(raw_session.get('verification_missing')),
            'verification_evidence': _string_list(raw_session.get('verification_evidence')),
            'reason': ', '.join(reasons),
        })

    return issues


def format_verification_gate_reason(issues: list[Dict[str, Any]], *, action: str) -> str:
    if not issues:
        return ''

    fragments: list[str] = []
    for issue in issues:
        detail_parts: list[str] = []
        reason = str(issue.get('reason') or '').strip()
        if reason:
            detail_parts.append(reason)
        missing = issue.get('verification_missing') or []
        if missing:
            detail_parts.append('missing: ' + '; '.join(str(item) for item in missing))
        slug = str(issue.get('task_slug') or 'unknown')
        details = '; '.join(detail_parts) if detail_parts else 'unresolved verification'
        fragments.append(f'{slug} ({details})')

    return (
        f'OMH {action} is blocked by unresolved task acceptance verification: '
        + '; '.join(fragments)
        + '. Route back to review/fix and rerun verification after the task evidence satisfies acceptance criteria.'
    )


def build_verification_gate(state: Dict[str, Any], *, action: str) -> Dict[str, Any]:
    issues = collect_unresolved_task_verification_issues(state)
    return {
        'blocked': bool(issues),
        'issues': issues,
        'reason': format_verification_gate_reason(issues, action=action) if issues else None,
    }
