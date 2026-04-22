from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

_RESEARCH_LANES = ('explore', 'librarian', 'oracle')


def _normalize_request(request: str) -> str:
    return ' '.join(str(request or '').split()).strip()


def build_specialist_messages(request: str) -> List[str]:
    normalized_request = _normalize_request(request)
    if not normalized_request:
        raise ValueError('request is required')

    return [f'omh-ulw {lane} {normalized_request}' for lane in _RESEARCH_LANES]


def build_research_lane_payload(request: str, workspace: Path | None = None) -> Dict[str, Any]:
    normalized_request = _normalize_request(request)
    if not normalized_request:
        raise ValueError('request is required')

    specialist_messages = build_specialist_messages(normalized_request)
    specialist_lanes = [
        {'lane': lane, 'message': message}
        for lane, message in zip(_RESEARCH_LANES, specialist_messages, strict=True)
    ]

    return {
        'workspace': str(Path(workspace).expanduser().resolve()) if workspace is not None else None,
        'request': normalized_request,
        'lane_names': list(_RESEARCH_LANES),
        'specialist_messages': specialist_messages,
        'specialist_lanes': specialist_lanes,
    }


def render_research_lane_text(payload: Dict[str, Any]) -> str:
    request = payload.get('request') or 'unknown'
    lane_names = payload.get('lane_names') or [item.get('lane') for item in payload.get('specialist_lanes') or []]
    specialist_lanes = payload.get('specialist_lanes') or []

    lines = [
        'OMH Research Lane',
        '',
        f'Request: {request}',
        f'Specialist Lanes: {", ".join(str(lane) for lane in lane_names if lane)}',
        '',
        'Specialist Messages:',
    ]

    for item in specialist_lanes:
        lane = item.get('lane') or 'unknown'
        message = item.get('message') or ''
        lines.append(f'- {lane}: {message}')

    return '\n'.join(lines)


def run_research_lane(request: str) -> str:
    payload = build_research_lane_payload(request)
    return render_research_lane_text(payload)
