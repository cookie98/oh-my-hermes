from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .atlas_state import discover_canonical_plans, get_workspace_root
from .intent_gate import classify_intent

_SLUG_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


def _parse_args(raw_args: str) -> Tuple[str, bool]:
    tokens = (raw_args or '').strip().split()
    json_mode = False
    kept: List[str] = []
    for token in tokens:
        if token == '--json':
            json_mode = True
        else:
            kept.append(token)
    return ' '.join(kept).strip(), json_mode


def _slugify(text: str) -> str:
    lowered = text.lower().strip()
    slug = _SLUG_NON_ALNUM_RE.sub('-', lowered).strip('-')
    return slug or 'plan'


def _titleize_slug(slug: str) -> str:
    return ' '.join(part.capitalize() for part in slug.split('-') if part)


def _plan_dir(workspace: Path) -> Path:
    return workspace / '.omh' / 'plans'


def _plan_path_for_intent(intent: str, workspace: Path) -> Path:
    return _plan_dir(workspace) / f'{_slugify(intent)}.md'


def _render_plan_markdown(*, intent: str, slug: str, workspace: Path) -> str:
    title = _titleize_slug(slug)
    return f'''# {title}

> Canonical OMH plan (Hermes-first scaffold)

**Plan Name:** `{slug}`
**Workspace:** `{workspace}`
**Source Intent:** {intent}
**Planning Backend:** Hermes-first scaffold

## Goal

Turn the user intent into an execution-ready canonical OMH plan without depending on an external planner.

## Architecture

This initial canonical plan is a deterministic scaffold. It is intentionally conservative: it captures intent, expected work lanes, and verification expectations while leaving room for later refinement by a richer planning backend.

## Constraints

- Keep planning and execution separate.
- The canonical plan is read-only once execution begins.
- Workers may append notes or handoffs, but should not rewrite this plan during execution.
- Verification evidence is required before completion claims.

## TODOs

- [ ] 1. Confirm scope and acceptance criteria for: {intent}
- [ ] 2. Identify the primary files, modules, or surfaces likely to change
- [ ] 3. Decide whether supporting research/exploration is needed before implementation
- [ ] 4. Implement the required change in the smallest safe sequence
- [ ] 5. Run focused verification for the changed surfaces
- [ ] 6. Run broader regression checks if the blast radius justifies it
- [ ] 7. Summarize outcomes, blockers, and next actions

## Final Verification Wave

- [ ] F1. Re-read the original intent and confirm every stated requirement is covered
- [ ] F2. Verify commands/tests output supports the completion claim
- [ ] F3. Record any remaining blockers or uncertainty explicitly
'''


def _render_plan_for_category(*, intent: str, slug: str, workspace: Path, category: str) -> str:
    title = _titleize_slug(slug)
    if category in {'implementation', 'fix'}:
        return f'''# {title}

> Intent-aware OMH implementation plan

**Plan Name:** `{slug}`
**Workspace:** `{workspace}`
**Source Intent:** {intent}
**Plan Category:** {category}

## Goal

- [ ] Restate the requested change in one sentence
- [ ] Confirm the acceptance criteria and non-goals
- [ ] Identify the primary files likely to change: `{workspace}/path/to/primary_module.py`

## Architecture

- [ ] Describe the current flow and the proposed control flow
- [ ] Call out integration points, state, and dependencies
- [ ] Record any file placeholders to update:
  - `{workspace}/path/to/primary_module.py`
  - `{workspace}/path/to/test_primary_module.py`

## Tech Stack

- [ ] Confirm runtime, framework, and test tooling constraints
- [ ] Note any new dependencies, feature flags, or environment variables
- [ ] Keep the implementation surface as small as possible

## Task 1 (Scope & Acceptance Criteria)

- [ ] Define the precise user-visible behavior
- [ ] Write acceptance criteria as observable outcomes
- [ ] Identify non-goals and risk boundaries
- [ ] File placeholder: `{workspace}/docs/{slug}-scope.md`

## Task 2 (Implementation with TDD steps)

- [ ] Write or update a failing test first
- [ ] Implement the smallest change needed to satisfy the test
- [ ] Refactor only after the test is green
- [ ] Update the relevant files:
  - `{workspace}/path/to/primary_module.py`
  - `{workspace}/path/to/tests/test_primary_module.py`

## Task 3 (Verification)

- [ ] Run focused tests for the touched behavior
- [ ] Run any adjacent regression tests that protect the change
- [ ] Capture evidence that the acceptance criteria are met
- [ ] File placeholder: `{workspace}/artifacts/{slug}-verification.log`

## Final Verification Wave

- [ ] Re-read the original request and confirm every requirement is covered
- [ ] Verify the plan references the right files and surfaces
- [ ] Record any remaining caveats or follow-up work explicitly
'''

    if category in {'research', 'investigation', 'evaluation'}:
        return f'''# {title}

> Intent-aware OMH research plan

**Plan Name:** `{slug}`
**Workspace:** `{workspace}`
**Source Intent:** {intent}
**Plan Category:** {category}

## Research Questions

- [ ] R1. What is the current state of the target area or problem?
- [ ] R2. What options, constraints, or trade-offs should be evaluated?
- [ ] R3. What evidence is needed to choose the safest next step?

## Deliverables

- [ ] Summarize findings in a concise decision note
- [ ] Capture references, data points, or reproduction evidence
- [ ] Identify any follow-up implementation or verification tasks
- [ ] File placeholder: `{workspace}/docs/{slug}-research-notes.md`

## Final Verification

- [ ] Confirm every research question was answered or explicitly marked unknown
- [ ] Ensure the deliverables are saved and easy to hand off
- [ ] Record unresolved risks or next actions
'''

    return _render_plan_markdown(intent=intent, slug=slug, workspace=workspace)


def build_plan_payload(intent: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    normalized_intent = (intent or '').strip()
    if not normalized_intent:
        raise ValueError('intent is required')

    slug = _slugify(normalized_intent)
    intent_decision = classify_intent(normalized_intent)
    intent_category = intent_decision.intent
    plan_dir = _plan_dir(root)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = _plan_path_for_intent(normalized_intent, root)

    created = False
    if not plan_path.exists():
        plan_path.write_text(
            _render_plan_for_category(intent=normalized_intent, slug=slug, workspace=root, category=intent_category),
            encoding='utf-8',
        )
        created = True

    return {
        'workspace': str(root),
        'created': created,
        'planning_backend': 'hermes-native',
        'intent': normalized_intent,
        'intent_category': intent_category,
        'plan': {
            'name': slug,
            'title': _titleize_slug(slug),
            'path': str(plan_path),
        },
        'canonical_plan_count': len(discover_canonical_plans(root)),
        'next_commands': ['omh-start-work', 'omh-status', 'omh-ulw'],
    }


def render_plan_text(payload: Dict[str, Any]) -> str:
    created = 'yes' if payload.get('created') else 'no (reused existing plan)'
    plan = payload.get('plan') or {}
    return (
        'OMH Canonical Plan\n\n'
        f'Intent: {payload.get("intent")}\n'
        f'Plan: {plan.get("name")}\n'
        f'Path: {plan.get("path")}\n'
        f'Created: {created}\n'
        f'Planning Backend: {payload.get("planning_backend")}\n'
        f'Canonical Plans: {payload.get("canonical_plan_count")}\n\n'
        'Next Step:\n'
        '- run `omh-start-work` to bootstrap execution from this plan\n'
        '- run `omh-status` to inspect execution posture later\n'
        '- or use `omh-ulw <intent>` to let OMH route the workflow'
    )


def handle_omh_plan_command(raw_args: str) -> str:
    intent, json_mode = _parse_args(raw_args)
    if not intent:
        return 'Usage: `/omh-plan <intent...> [--json]`'

    payload = build_plan_payload(intent)
    if json_mode:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_plan_text(payload)
