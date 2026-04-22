from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .atlas_state import discover_canonical_plans, get_workspace_root
from .intent_gate import classify_intent

_SLUG_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')
_DRAFT_BANNER = '> Draft OMH plan (Hermes-first scaffold)'
_CANONICAL_BANNER = '> Canonical OMH plan (Hermes-first scaffold)'
_SOURCE_INTENT_RE = re.compile(r'^\*\*Source Intent:\*\*\s*(.+?)\s*$', re.MULTILINE)


def _parse_args(raw_args: str) -> Tuple[str | None, str, bool]:
    tokens = (raw_args or '').strip().split()
    json_mode = False
    kept: List[str] = []
    for token in tokens:
        if token == '--json':
            json_mode = True
        else:
            kept.append(token)

    action: str | None = None
    if kept and kept[0].strip().lower() == 'finalize':
        action = 'finalize'
        kept = kept[1:]

    return action, ' '.join(kept).strip(), json_mode


def _slugify(text: str) -> str:
    lowered = text.lower().strip()
    slug = _SLUG_NON_ALNUM_RE.sub('-', lowered).strip('-')
    return slug or 'plan'


def _titleize_slug(slug: str) -> str:
    return ' '.join(part.capitalize() for part in slug.split('-') if part)


def _plan_dir(workspace: Path) -> Path:
    return workspace / '.omh' / 'plans'


def _draft_dir(workspace: Path) -> Path:
    return workspace / '.omh' / 'drafts'


def _plan_path_for_slug(slug: str, workspace: Path) -> Path:
    return _plan_dir(workspace) / f'{slug}.md'


def _draft_path_for_slug(slug: str, workspace: Path) -> Path:
    return _draft_dir(workspace) / f'{slug}.md'


def _plan_path_for_intent(intent: str, workspace: Path) -> Path:
    return _plan_path_for_slug(_slugify(intent), workspace)


def _draft_path_for_intent(intent: str, workspace: Path) -> Path:
    return _draft_path_for_slug(_slugify(intent), workspace)


def _render_plan_markdown(*, intent: str, slug: str, workspace: Path, draft: bool) -> str:
    title = _titleize_slug(slug)
    banner = _DRAFT_BANNER if draft else _CANONICAL_BANNER
    planning_backend = 'Hermes-first draft scaffold' if draft else 'Hermes-first scaffold'
    next_step_block = (
        f'## Next Step\n\n- Run `omh-plan finalize {slug}` when this draft is ready to become the canonical OMH plan.\n'
        if draft
        else ''
    )
    return f'''# {title}

{banner}

**Plan Name:** `{slug}`
**Workspace:** `{workspace}`
**Source Intent:** {intent}
**Planning Backend:** {planning_backend}

## Goal

Turn the user intent into an execution-ready canonical OMH plan without depending on an external planner.

## Architecture

This initial {'draft' if draft else 'canonical'} plan is a deterministic scaffold. It is intentionally conservative: it captures intent, expected work lanes, and verification expectations while leaving room for later refinement by a richer planning backend.

## Constraints

- Keep planning and execution separate.
- The canonical plan is read-only once execution begins.
- Workers may append notes or handoffs, but should not rewrite this plan during execution.
- Verification evidence is required before completion claims.

## Task 1: Scope & Acceptance Criteria

**blockedBy:** `[]`
**blocks:** `[T2, T3]`
**parentID:** `null`

- [ ] Define the precise user-visible behavior for: {intent}
- [ ] Write acceptance criteria as observable outcomes
- [ ] Identify non-goals and risk boundaries

## Task 2: Identify Surfaces & Research

**blockedBy:** `[T1]`
**blocks:** `[T4]`
**parentID:** `null`

- [ ] Identify the primary files, modules, or surfaces likely to change
- [ ] Decide whether supporting research/exploration is needed before implementation
- [ ] Record any file placeholders to update

## Task 3: Implement

**blockedBy:** `[T1]`
**blocks:** `[T4]`
**parentID:** `null`

- [ ] Implement the required change in the smallest safe sequence
- [ ] Run focused verification for the changed surfaces

## Task 4: Regression & Finalize

**blockedBy:** `[T2, T3]`
**blocks:** `[T5]`
**parentID:** `null`

- [ ] Run broader regression checks if the blast radius justifies it
- [ ] Summarize outcomes, blockers, and next actions

## Task 5: Final Verification Wave

**blockedBy:** `[T4]`
**blocks:** `[]`
**parentID:** `null`

- [ ] F1. Re-read the original intent and confirm every stated requirement is covered
- [ ] F2. Verify commands/tests output supports the completion claim
- [ ] F3. Record any remaining blockers or uncertainty explicitly

{next_step_block}'''


def _extract_source_intent(markdown: str, slug: str) -> str:
    match = _SOURCE_INTENT_RE.search(markdown)
    if match:
        return match.group(1).strip()
    return _titleize_slug(slug)


def _match_markdown_paths(name: str, paths: List[Path]) -> List[Path]:
    wanted = (name or '').strip().lower()
    if not wanted:
        return []
    exact = [p for p in paths if p.stem.lower() == wanted]
    if exact:
        return exact
    return [p for p in paths if wanted in p.stem.lower()]


def discover_plan_drafts(workspace: Path | None = None) -> List[Path]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    draft_dir = _draft_dir(root)
    if not draft_dir.exists():
        return []
    return sorted((p.resolve() for p in draft_dir.glob('*.md')), key=lambda p: p.name)


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

**blockedBy:** `[]`
**blocks:** `[T1, T2]`
**parentID:** `null`

- [ ] Restate the requested change in one sentence
- [ ] Confirm the acceptance criteria and non-goals
- [ ] Identify the primary files likely to change: `{workspace}/path/to/primary_module.py`

## Task 1: Architecture & Tech Stack

**blockedBy:** `[T0]`
**blocks:** `[T3]`
**parentID:** `null`

- [ ] Describe the current flow and the proposed control flow
- [ ] Call out integration points, state, and dependencies
- [ ] Confirm runtime, framework, and test tooling constraints
- [ ] Record any file placeholders to update:
  - `{workspace}/path/to/primary_module.py`
  - `{workspace}/path/to/test_primary_module.py`

## Task 2: Scope & Acceptance Criteria

**blockedBy:** `[T0]`
**blocks:** `[T3]`
**parentID:** `null`

- [ ] Define the precise user-visible behavior
- [ ] Write acceptance criteria as observable outcomes
- [ ] Identify non-goals and risk boundaries
- [ ] File placeholder: `{workspace}/docs/{slug}-scope.md`

## Task 3: Implementation with TDD

**blockedBy:** `[T1, T2]`
**blocks:** `[T4]`
**parentID:** `null`

- [ ] Write or update a failing test first
- [ ] Implement the smallest change needed to satisfy the test
- [ ] Refactor only after the test is green
- [ ] Update the relevant files:
  - `{workspace}/path/to/primary_module.py`
  - `{workspace}/path/to/tests/test_primary_module.py`

## Task 4: Verification

**blockedBy:** `[T3]`
**blocks:** `[T5]`
**parentID:** `null`

- [ ] Run focused tests for the touched behavior
- [ ] Run any adjacent regression tests that protect the change
- [ ] Capture evidence that the acceptance criteria are met
- [ ] File placeholder: `{workspace}/artifacts/{slug}-verification.log`

## Task 5: Final Verification Wave

**blockedBy:** `[T4]`
**blocks:** `[]`
**parentID:** `null`

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

## Task 0: Research Questions

**blockedBy:** `[]`
**blocks:** `[T1]`
**parentID:** `null`

- [ ] R1. What is the current state of the target area or problem?
- [ ] R2. What options, constraints, or trade-offs should be evaluated?
- [ ] R3. What evidence is needed to choose the safest next step?

## Task 1: Deliverables

**blockedBy:** `[T0]`
**blocks:** `[T2]`
**parentID:** `null`

- [ ] Summarize findings in a concise decision note
- [ ] Capture references, data points, or reproduction evidence
- [ ] Identify any follow-up implementation or verification tasks
- [ ] File placeholder: `{workspace}/docs/{slug}-research-notes.md`

## Task 2: Final Verification

**blockedBy:** `[T1]`
**blocks:** `[]`
**parentID:** `null`

- [ ] Confirm every research question was answered or explicitly marked unknown
- [ ] Ensure the deliverables are saved and easy to hand off
- [ ] Record unresolved risks or next actions
'''

    return _render_plan_markdown(intent=intent, slug=slug, workspace=workspace, draft=False)


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


def build_draft_plan_payload(intent: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    normalized_intent = (intent or '').strip()
    if not normalized_intent:
        raise ValueError('intent is required')

    slug = _slugify(normalized_intent)
    draft_dir = _draft_dir(root)
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = _draft_path_for_intent(normalized_intent, root)

    created = False
    if not draft_path.exists():
        draft_path.write_text(
            _render_plan_markdown(intent=normalized_intent, slug=slug, workspace=root, draft=True),
            encoding='utf-8',
        )
        created = True

    return {
        'workspace': str(root),
        'created': created,
        'planning_backend': 'hermes-native',
        'intent': normalized_intent,
        'draft': {
            'name': slug,
            'title': _titleize_slug(slug),
            'path': str(draft_path),
        },
        'draft_count': len(discover_plan_drafts(root)),
        'canonical_plan_count': len(discover_canonical_plans(root)),
        'next_commands': [f'omh-plan finalize {slug}', 'omh-status', 'omh-ulw'],
    }


def finalize_draft_plan_payload(name: str, *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    matches = _match_markdown_paths(name, discover_plan_drafts(root))
    if not matches:
        raise ValueError('No OMH draft plan found to finalize')
    if len(matches) > 1:
        raise ValueError('Multiple OMH draft plans matched; choose one explicitly')

    draft_path = matches[0]
    slug = draft_path.stem
    draft_content = draft_path.read_text(encoding='utf-8')
    canonical_content = draft_content.replace(_DRAFT_BANNER, _CANONICAL_BANNER, 1)
    canonical_content = canonical_content.replace('Hermes-first draft scaffold', 'Hermes-first scaffold', 1)
    if 'This initial draft plan' in canonical_content:
        canonical_content = canonical_content.replace('This initial draft plan', 'This initial canonical plan', 1)
    if '## Next Step' in canonical_content:
        canonical_content = canonical_content.split('## Next Step')[0].rstrip() + '\n'
    intent = _extract_source_intent(draft_content, slug)

    canonical_dir = _plan_dir(root)
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = _plan_path_for_slug(slug, root)
    canonical_path.write_text(canonical_content, encoding='utf-8')
    draft_path.unlink()

    return {
        'workspace': str(root),
        'created': True,
        'planning_backend': 'hermes-native',
        'intent': intent,
        'plan': {
            'name': slug,
            'title': _titleize_slug(slug),
            'path': str(canonical_path),
        },
        'draft': {
            'name': slug,
            'path': str(draft_path),
        },
        'draft_deleted': not draft_path.exists(),
        'canonical_plan_count': len(discover_canonical_plans(root)),
        'next_commands': ['omh-start-work', 'omh-status', 'omh-ulw'],
    }


def render_draft_plan_text(payload: Dict[str, Any]) -> str:
    created = 'yes' if payload.get('created') else 'no (reused existing draft)'
    draft = payload.get('draft') or {}
    return (
        'OMH Draft Plan\n\n'
        f'Intent: {payload.get("intent")}\n'
        f'Draft: {draft.get("name")}\n'
        f'Path: {draft.get("path")}\n'
        f'Created: {created}\n'
        f'Planning Backend: {payload.get("planning_backend")}\n'
        f'Drafts: {payload.get("draft_count")}\n'
        f'Canonical Plans: {payload.get("canonical_plan_count")}\n\n'
        'Next Step:\n'
        f'- run `omh-plan finalize {draft.get("name")}` to materialize the canonical OMH plan\n'
        '- run `omh-status` to inspect execution posture later\n'
        '- or use `omh-ulw <intent>` to let OMH route the workflow'
    )


def render_plan_text(payload: Dict[str, Any]) -> str:
    created = 'yes' if payload.get('created') else 'no (reused existing plan)'
    plan = payload.get('plan') or {}
    draft_deleted = 'yes' if payload.get('draft_deleted') else 'no'
    return (
        'OMH Canonical Plan\n\n'
        f'Intent: {payload.get("intent")}\n'
        f'Plan: {plan.get("name")}\n'
        f'Path: {plan.get("path")}\n'
        f'Created: {created}\n'
        f'Planning Backend: {payload.get("planning_backend")}\n'
        f'Canonical Plans: {payload.get("canonical_plan_count")}\n'
        f'Draft cleaned up: {draft_deleted}\n\n'
        'Next Step:\n'
        '- run `omh-start-work` to bootstrap execution from this plan\n'
        '- run `omh-status` to inspect execution posture later\n'
        '- or use `omh-ulw <intent>` to let OMH route the workflow'
    )


def handle_omh_plan_command(raw_args: str) -> str:
    action, intent, json_mode = _parse_args(raw_args)
    if not intent:
        return 'Usage: `/omh-plan <intent...> [--json]` or `/omh-plan finalize <plan-name> [--json]`'

    try:
        if action == 'finalize':
            payload = finalize_draft_plan_payload(intent)
            if json_mode:
                return json.dumps(payload, ensure_ascii=False, indent=2)
            return render_plan_text(payload)

        payload = build_draft_plan_payload(intent)
        if json_mode:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return render_draft_plan_text(payload)
    except ValueError as exc:
        return str(exc)
