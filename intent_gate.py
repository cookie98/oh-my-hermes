from __future__ import annotations

import re
from dataclasses import dataclass

ULW_PREFIX_RE = re.compile(r'^\s*(?:/)?omh-ulw\b', re.IGNORECASE)
TRIGGER_RE = re.compile(r'\b(?:ultrawork|ulw)\b', re.IGNORECASE)
_INTENT_REASONS = {
    'status': 'request asks for execution posture or progress',
    'investigation': 'request asks for investigation before action',
    'research': 'request asks for understanding or external/internal research',
    'evaluation': 'request asks for evaluation or recommendation',
    'fix': 'request mentions a bug or failure to repair',
    'implementation': 'request asks for a concrete change or feature',
    'open-ended': 'request is ambiguous enough to require exploratory routing first',
}


@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    raw_text: str

    @property
    def reason(self) -> str:
        return _INTENT_REASONS.get(self.intent, _INTENT_REASONS['open-ended'])

    @property
    def normalized_request(self) -> str:
        return extract_intent_payload(self.raw_text)


def strip_omh_ulw_prefix(text: str) -> str:
    stripped = ULW_PREFIX_RE.sub('', text or '', count=1)
    return stripped.strip()


def strip_ulw_trigger(text: str) -> str:
    stripped = TRIGGER_RE.sub('', text or '', count=1)
    return re.sub(r'\s{2,}', ' ', stripped).strip(' :-\n\t')


def extract_intent_payload(user_message: str) -> str:
    text = (user_message or '').strip()
    if ULW_PREFIX_RE.search(text):
        return strip_omh_ulw_prefix(text)
    if TRIGGER_RE.search(text):
        cleaned = strip_ulw_trigger(text)
        return cleaned or text
    return text


def classify_intent(user_message: str) -> IntentDecision:
    raw_text = user_message or ''
    payload = extract_intent_payload(raw_text)
    lowered = payload.lower()

    if any(token in lowered for token in ['status', 'progress', 'state', 'what are we doing', 'where are we at']):
        return IntentDecision('status', 0.96, raw_text)

    if any(token in lowered for token in ['investigate', 'look into', 'check why', 'debug why', 'analyze', 'inspect']):
        return IntentDecision('investigation', 0.93, raw_text)

    if any(token in lowered for token in ['research', 'compare', 'find out', 'explain', 'how does', 'what is']):
        return IntentDecision('research', 0.95, raw_text)

    if any(token in lowered for token in ['what do you think', 'opinion', 'evaluate', 'should we', 'is it better']):
        return IntentDecision('evaluation', 0.9, raw_text)

    if any(token in lowered for token in ['fix', 'bug', 'broken', 'error', 'failing', 'regression']):
        return IntentDecision('fix', 0.94, raw_text)

    if any(token in lowered for token in ['implement', 'build', 'create', 'add', 'wire up', 'set up']):
        return IntentDecision('implementation', 0.92, raw_text)

    return IntentDecision('open-ended', 0.35, raw_text)
