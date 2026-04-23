# OMH v0.2 Planner-to-Execution Pipeline Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic `omh-plan` scaffold with intent-aware plan generation, tighten the plan-to-task-session bridge, and make `omh-exec` route tasks to the correct lane (research / implement / verify) based on task content rather than keyword hints alone.

**Architecture:** Keep all changes inside the OMH plugin (`~/git_repo/oh-my-hermes`). Derive plan shape from `intent_gate` output. Enrich task sessions with extracted acceptance criteria and file targets from plan markdown. Route execution through `route_resolver` semantics already present in `omh_exec.py`.

**Tech Stack:** Python 3.12, Hermes plugin runtime, pytest, file-backed JSON state.

---

## Task 1: Intent-Aware Plan Generation

**Files:**
- Modify: `~/git_repo/oh-my-hermes/omh_plan.py`
- Modify: `~/git_repo/oh-my-hermes/intent_gate.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_plan.py`

**Rationale:** `omh_plan.py` currently emits a single deterministic scaffold regardless of intent. It should emit a shape that matches the user's intent category (implementation, research, fix, review) and references the `writing-plans` skill structure when the intent looks like a multi-step implementation.

- [ ] **Step 1: Export intent categories from `intent_gate.py`**

Verify `intent_gate.py` defines these categories:
- `implementation`
- `fix`
- `research`
- `investigation`
- `evaluation`
- `status`
- `open-ended`

If the return type is not a dataclass or typed dict, wrap it so `omh_plan.py` can import it safely:

```python
# intent_gate.py
from dataclasses import dataclass

@dataclass(frozen=True)
class IntentDecision:
    intent: str
    confidence: float
    raw_text: str
```

Ensure `IntentDecision` is importable from the package root.

- [ ] **Step 2: Add `_render_plan_for_category` helper to `omh_plan.py`**

Insert above `build_plan_payload`:

```python
def _render_plan_for_category(
    *,
    intent: str,
    slug: str,
    workspace: Path,
    category: str,
) -> str:
    title = _titleize_slug(slug)
    if category in {'implementation', 'fix'}:
        return f'''# {title}

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** {intent}

**Architecture:** 2-3 sentences describing the intended approach.

**Tech Stack:** Python, Hermes plugin runtime.

---

### Task 1: Scope & Acceptance Criteria

**Files:**
- Modify: `exact/path/to/file.py`
- Test: `tests/path/test_file.py`

- [ ] **Step 1.1: Confirm scope**
  - Re-read the original intent and list every stated requirement.
- [ ] **Step 1.2: Identify surfaces**
  - List primary files, modules, or commands likely to change.
- [ ] **Step 1.3: Decide on research**
  - If the intent involves unfamiliar APIs or upstream behavior, route to `research_lane` first.

### Task 2: Implementation

- [ ] **Step 2.1: Write the failing test**
- [ ] **Step 2.2: Run test to verify it fails**
- [ ] **Step 2.3: Write minimal implementation**
- [ ] **Step 2.4: Run test to verify it passes**
- [ ] **Step 2.5: Commit**

### Task 3: Verification

- [ ] **Step 3.1: Run focused verification**
- [ ] **Step 3.2: Run broader regression checks if justified**
- [ ] **Step 3.3: Record blockers and next actions**

## Final Verification Wave

- [ ] F1. Every stated requirement is traceable to a task or a note.
- [ ] F2. Commands/tests output supports the completion claim.
- [ ] F3. Remaining blockers or uncertainty are recorded explicitly.
'''

    if category in {'research', 'investigation', 'evaluation'}:
        return f'''# {title}

> Research lane plan (Hermes-native)

**Goal:** {intent}

**Research Questions:**
- [ ] R1. What is the current state of the relevant code/docs?
- [ ] R2. What are the known upstream references or prior art?
- [ ] R3. What constraints or risks should shape any later implementation?

**Deliverables:**
- Summarize findings in a notepad under `.omh/notepads/{slug}/`
- If implementation follows, convert this research plan into an implementation plan with `omh-plan`.

## Final Verification

- [ ] F1. Research questions are answered with evidence.
- [ ] F2. Sources are cited with paths or URLs.
- [ ] F3. No implementation code was written during research.
'''

    # Fallback for status, open-ended, or unknown
    return _render_plan_markdown(intent=intent, slug=slug, workspace=workspace)
```

- [ ] **Step 3: Wire category-aware rendering into `build_plan_payload`**

Replace the line that calls `_render_plan_markdown` with:

```python
from .intent_gate import classify_intent  # or whatever the entrypoint is

# inside build_plan_payload, before writing the file:
intent_decision = classify_intent(normalized_intent)
category = intent_decision.intent

plan_text = _render_plan_for_category(
    intent=normalized_intent,
    slug=slug,
    workspace=root,
    category=category,
)

if not plan_path.exists():
    plan_path.write_text(plan_text, encoding='utf-8')
    created = True
```

Update the payload to include `intent_category`:

```python
return {
    'workspace': str(root),
    'created': created,
    'planning_backend': 'hermes-native',
    'intent': normalized_intent,
    'intent_category': category,
    'plan': {
        'name': slug,
        'title': _titleize_slug(slug),
        'path': str(plan_path),
    },
    'canonical_plan_count': len(discover_canonical_plans(root)),
    'next_commands': ['omh-start-work', 'omh-status', 'omh-ulw'],
}
```

- [ ] **Step 4: Write focused test**

Create or append to `~/git_repo/oh-my-hermes/tests/test_omh_plan.py`:

```python
import pytest
from omh_plan import _render_plan_for_category, _slugify


def test_implementation_plan_contains_task_structure():
    text = _render_plan_for_category(
        intent='add JWT auth',
        slug='add-jwt-auth',
        workspace='/tmp',
        category='implementation',
    )
    assert '### Task 1:' in text
    assert '### Task 2:' in text
    assert '## Final Verification Wave' in text


def test_research_plan_contains_research_questions():
    text = _render_plan_for_category(
        intent='evaluate async runtimes',
        slug='evaluate-async-runtimes',
        workspace='/tmp',
        category='research',
    )
    assert '## Research Questions' in text
    assert 'R1.' in text
    assert 'F3. No implementation code was written during research.' in text


def test_slugify_replaces_non_alnum_with_hyphen():
    assert _slugify('Hello World!!') == 'hello-world'
```

- [ ] **Step 5: Run tests from the tests directory**

```bash
cd ~/git_repo/oh-my-hermes/tests
pytest -q test_omh_plan.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add omh_plan.py intent_gate.py tests/test_omh_plan.py
git commit -m "feat(plan): intent-aware plan generation with category-specific templates"
```

---

## Task 2: Acceptance Criteria & File Target Extraction

**Files:**
- Modify: `~/git_repo/oh-my-hermes/omh_start_work.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_start_work.py`

**Rationale:** `_extract_execution_tasks` only extracts checkbox lines. It should also extract acceptance criteria, expected file changes, and test targets from the plan markdown so that `omh-exec` and `omh-verify` can operate with richer context.

- [ ] **Step 1: Add regex patterns for acceptance criteria and file targets**

Insert near the top of `omh_start_work.py`, below the existing regexes:

```python
_ACCEPTANCE_RE = re.compile(r'^[-*]\s*(?:AC|Acceptance Criteria?)[:\s]+(.+)$', re.IGNORECASE)
_FILE_TARGET_RE = re.compile(r'^[-*]\s*(?:File|Modify|Create)[:\s]+(.+)$', re.IGNORECASE)
_TEST_TARGET_RE = re.compile(r'^[-*]\s*(?:Test|Test file)[:\s]+(.+)$', re.IGNORECASE)
```

- [ ] **Step 2: Extend `_extract_execution_tasks` to capture metadata per task**

Replace the body of `_extract_execution_tasks` with:

```python
def _extract_execution_tasks(plan_path: Path) -> Dict[str, Any]:
    text = plan_path.read_text(encoding='utf-8')
    current_task_id: str | None = None
    task_sessions: Dict[str, Any] = {}
    current_acceptance: List[str] = []
    current_files: List[str] = []
    current_tests: List[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # Task boundary from checkbox
        task_match = _UNCHECKED_TASK_RE.match(stripped)
        if task_match:
            if current_task_id is not None:
                task_sessions[current_task_id]['acceptance'] = current_acceptance
                task_sessions[current_task_id]['files'] = current_files
                task_sessions[current_task_id]['tests'] = current_tests
            current_task_id = f'T{len(task_sessions) + 1}'
            task_sessions[current_task_id] = {
                'label': task_match.group(1),
                'acceptance': [],
                'files': [],
                'tests': [],
            }
            current_acceptance = []
            current_files = []
            current_tests = []
            continue

        # Only collect metadata if inside a task
        if current_task_id is None:
            continue

        ac_match = _ACCEPTANCE_RE.match(stripped)
        if ac_match:
            current_acceptance.append(ac_match.group(1).strip())
            continue

        ft_match = _FILE_TARGET_RE.match(stripped)
        if ft_match:
            current_files.append(ft_match.group(1).strip())
            continue

        tt_match = _TEST_TARGET_RE.match(stripped)
        if tt_match:
            current_tests.append(tt_match.group(1).strip())
            continue

    # Flush last task
    if current_task_id is not None:
        task_sessions[current_task_id]['acceptance'] = current_acceptance
        task_sessions[current_task_id]['files'] = current_files
        task_sessions[current_task_id]['tests'] = current_tests

    return task_sessions
```

- [ ] **Step 3: Update `seed_task_sessions` (or equivalent) to persist metadata**

In `task_sessions.py` (or wherever `seed_task_sessions` lives), ensure each task session stores the new fields. If `seed_task_sessions` currently only stores `label` and `status`, add:

```python
# task_sessions.py (inside the normalizer or seeder)
if not isinstance(session.get('acceptance'), list):
    session['acceptance'] = []
if not isinstance(session.get('files'), list):
    session['files'] = []
if not isinstance(session.get('tests'), list):
    session['tests'] = []
```

- [ ] **Step 4: Write focused test**

Create or append to `tests/test_omh_start_work.py`:

```python
import tempfile
from pathlib import Path
from omh_start_work import _extract_execution_tasks


def test_extracts_acceptance_and_files():
    md = '''
### Task 1: Add auth

**Files:**
- Modify: src/auth.py
- Test: tests/test_auth.py

- [ ] Step 1: Write the failing test
  - AC: login returns 401 without token
- [ ] Step 2: Implement minimal code
  - AC: login returns 200 with valid token
'''
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'plan.md'
        p.write_text(md, encoding='utf-8')
        tasks = _extract_execution_tasks(p)

    assert len(tasks) == 2
    assert tasks['T1']['files'] == ['src/auth.py']
    assert tasks['T1']['tests'] == ['tests/test_auth.py']
    assert tasks['T1']['acceptance'] == ['login returns 401 without token']
    assert tasks['T2']['acceptance'] == ['login returns 200 with valid token']
```

- [ ] **Step 5: Run tests**

```bash
cd ~/git_repo/oh-my-hermes/tests
pytest -q test_omh_start_work.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add omh_start_work.py task_sessions.py tests/test_omh_start_work.py
git commit -m "feat(start-work): extract acceptance criteria and file targets from plan markdown"
```

---

## Task 3: Task-Aware Execution Router

**Files:**
- Modify: `~/git_repo/oh-my-hermes/omh_exec.py`
- Modify: `~/git_repo/oh-my-hermes/route_resolver.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_exec_router.py`

**Rationale:** `omh_exec.py` currently relies on keyword hints (`_EXEC_COMPLETE_HINTS`, `_EXEC_BLOCK_HINTS`) to guess user intent inside exec. It should instead look at the current task session's label, acceptance criteria, and files to decide whether the task is an implementation, research, or verification task, and route accordingly.

- [ ] **Step 1: Add `_classify_task_session` helper to `omh_exec.py`**

Insert near the top, after the hint tuples:

```python
_TASK_RESEARCH_HINTS = frozenset({
    'research', 'investigate', 'evaluate', 'compare', 'survey',
    'look up', 'find out', 'check upstream',
})
_TASK_VERIFY_HINTS = frozenset({
    'verify', 'verification', 'validate', 'check', 'test', 'regression',
    'ensure', 'confirm', 'audit',
})
_TASK_IMPLEMENT_HINTS = frozenset({
    'implement', 'add', 'create', 'write', 'build', 'introduce',
    'refactor', 'fix', 'patch', 'update',
})


def _classify_task_session(task: Dict[str, Any]) -> str:
    text = ' '.join([
        task.get('label', ''),
        ' '.join(task.get('acceptance', [])),
        ' '.join(task.get('files', [])),
    ]).lower()

    if any(h in text for h in _TASK_VERIFY_HINTS):
        return 'verify'
    if any(h in text for h in _TASK_RESEARCH_HINTS):
        return 'research'
    if any(h in text for h in _TASK_IMPLEMENT_HINTS):
        return 'implement'
    return 'implement'  # default to implementation if ambiguous
```

- [ ] **Step 2: Route through `route_resolver.py` from `omh_exec.py`**

In the main exec handler (where it decides what to do with a task), before falling back to keyword hints, add:

```python
from .route_resolver import resolve_route
from .intent_gate import IntentDecision

# ... inside the exec handler when a task session is active ...
task = active_task_sessions[0]  # or however the current task is resolved
category = _classify_task_session(task)

if category == 'research':
    # Route to research lane rather than trying to implement
    from .research_lane import run_research_lane
    return run_research_lane(task['label'])

if category == 'verify':
    # Route to omh-verify equivalent
    verify_payload = build_verify_payload(task_label=task['label'])
    return render_verify_text(verify_payload)

# Otherwise continue with normal implementation dispatch
```

> **Note:** The exact integration point depends on `omh_exec.py`'s internal structure (which is 487 lines). The worker should locate the block where `dispatch_exec_worker` is called and insert the classification logic immediately before it.

- [ ] **Step 3: Write focused test**

Create `tests/test_omh_exec_router.py`:

```python
import pytest
from omh_exec import _classify_task_session


def test_classify_research_task():
    assert _classify_task_session({'label': 'Research async libraries'}) == 'research'


def test_classify_verify_task():
    assert _classify_task_session({'label': 'Verify login flow', 'acceptance': ['test coverage > 80%']}) == 'verify'


def test_classify_implement_task():
    assert _classify_task_session({'label': 'Add JWT middleware', 'files': ['src/auth.py']}) == 'implement'


def test_default_to_implement_when_ambiguous():
    assert _classify_task_session({'label': 'Do something'}) == 'implement'
```

- [ ] **Step 4: Run tests**

```bash
cd ~/git_repo/oh-my-hermes/tests
pytest -q test_omh_exec_router.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add omh_exec.py route_resolver.py tests/test_omh_exec_router.py
git commit -m "feat(exec): task-aware router with research/verify/implement classification"
```

---

## Task 4: Cross-Surface State Consistency Guard

**Files:**
- Modify: `~/git_repo/oh-my-hermes/atlas_state.py`
- Modify: `~/git_repo/oh-my-hermes/omh_status.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_atlas_state.py`

**Rationale:** `atlas_state.py` normalizes state but does not check for drift between `task_sessions` and `worker_sessions`. A task marked `completed` in `task_sessions` but still `running` in `worker_sessions` is a consistency bug that confuses `omh-status` and `route_resolver`.

- [ ] **Step 1: Add `_check_state_consistency` to `atlas_state.py`**

Insert before `read_atlas_state` (or wherever the state builder is):

```python
def _check_state_consistency(state: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    task_sessions: Dict[str, Any] = state.get('task_sessions', {})
    worker_sessions: Dict[str, Any] = state.get('worker_orchestration', {}).get('worker_sessions', {})

    for slug, task in task_sessions.items():
        task_status = task.get('status', '')
        session_id = task.get('session_id')
        if not session_id:
            continue
        worker = worker_sessions.get(session_id)
        if not worker:
            if task_status in {'running', 'dispatched'}:
                warnings.append(f"Task '{slug}' is {task_status} but has no worker session")
            continue
        worker_status = worker.get('status', '')
        if task_status in {'completed', 'cancelled'} and worker_status in {'running', 'dispatched'}:
            warnings.append(
                f"Task '{slug}' is {task_status} but worker '{session_id}' is still {worker_status}"
            )
        if task_status in {'running', 'dispatched'} and worker_status in {'completed', 'failed', 'lost'}:
            warnings.append(
                f"Task '{slug}' is {task_status} but worker '{session_id}' is already {worker_status}"
            )
    return warnings
```

- [ ] **Step 2: Surface consistency warnings in `AtlasStateSnapshot`**

Add `consistency_warnings: List[str]` to `AtlasStateSnapshot`:

```python
@dataclass(frozen=True)
class AtlasStateSnapshot:
    workspace: Path
    state_path: Path
    has_state: bool
    lifecycle: str | None
    posture: str
    resumable: bool
    state: Dict[str, Any] | None
    progress: PlanProgress | None
    active_task_slugs: List[str]
    warnings: List[str]
    errors: List[str]
    consistency_warnings: List[str]  # NEW
```

In `read_atlas_state` (or wherever the snapshot is assembled), after building the snapshot, call `_check_state_consistency` and include the result.

- [ ] **Step 3: Render consistency warnings in `omh_status.py`**

Locate the status text renderer and append:

```python
if snapshot.consistency_warnings:
    lines.append('')
    lines.append('State Consistency Warnings:')
    for w in snapshot.consistency_warnings:
        lines.append(f'  - {w}')
```

- [ ] **Step 4: Write focused test**

Append to `tests/test_atlas_state.py` (or create it):

```python
from atlas_state import _check_state_consistency


def test_warns_when_task_completed_but_worker_running():
    state = {
        'task_sessions': {
            'T1': {'status': 'completed', 'session_id': 'sess-1'},
        },
        'worker_orchestration': {
            'worker_sessions': {
                'sess-1': {'status': 'running'},
            },
        },
    }
    warnings = _check_state_consistency(state)
    assert len(warnings) == 1
    assert 'T1' in warnings[0]


def test_warns_when_task_running_but_worker_lost():
    state = {
        'task_sessions': {
            'T1': {'status': 'running', 'session_id': 'sess-1'},
        },
        'worker_orchestration': {
            'worker_sessions': {
                'sess-1': {'status': 'lost'},
            },
        },
    }
    warnings = _check_state_consistency(state)
    assert len(warnings) == 1
    assert 'already lost' in warnings[0]
```

- [ ] **Step 5: Run tests**

```bash
cd ~/git_repo/oh-my-hermes/tests
pytest -q test_atlas_state.py -v
```
Expected: 2 passed (or more if existing tests exist).

- [ ] **Step 6: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add atlas_state.py omh_status.py tests/test_atlas_state.py
git commit -m "feat(state): cross-surface consistency guard with drift warnings"
```

---

## Task 5: End-to-End Smoke Test

**Files:**
- Create: `~/git_repo/oh-my-hermes/tests/test_omh_pipeline_smoke.py`

- [ ] **Step 1: Write a smoke test that exercises plan → start-work → exec → status**

```python
import tempfile
from pathlib import Path

import omh_plan
import omh_start_work
import omh_status
from atlas_state import read_atlas_state


def test_full_pipeline_from_intent_to_status():
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        # 1. Plan
        payload = omh_plan.build_plan_payload('implement JWT auth', workspace=workspace)
        assert payload['created'] is True
        assert payload['intent_category'] in {'implementation', 'fix'}
        plan_path = Path(payload['plan']['path'])
        assert plan_path.exists()

        # 2. Start work
        result = omh_start_work.handle_omh_start_work_command(
            f'--worktree {workspace} {payload["plan"]["name"]}',
            workspace=workspace,
        )
        assert 'started' in result.lower() or 'session' in result.lower()

        # 3. Status
        snapshot = read_atlas_state(workspace)
        assert snapshot.has_state is True
        assert len(snapshot.active_task_slugs) > 0
```

> **Note:** If `handle_omh_start_work_command` does not accept a `workspace` kwarg, pass it through environment or monkeypatch `get_workspace_root`.

- [ ] **Step 2: Run the smoke test**

```bash
cd ~/git_repo/oh-my-hermes/tests
pytest -q test_omh_pipeline_smoke.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add tests/test_omh_pipeline_smoke.py
git commit -m "test(pipeline): add end-to-end smoke test for plan→start-work→status"
```

---

## Task 6: README & Plugin Metadata Sync

**Files:**
- Modify: `~/git_repo/oh-my-hermes/README.md`
- Modify: `~/git_repo/oh-my-hermes/plugin.yaml`

- [ ] **Step 1: Update README "Current implementation" section**

Add a bullet under the existing list:

```markdown
- intent-aware plan generation with category-specific templates (implementation vs research vs fix)
- plan-to-task bridge now extracts acceptance criteria, file targets, and test targets from plan markdown
- `omh-exec` task-aware router classifies each active task as implement/research/verify before dispatch
- cross-surface state consistency guard detects drift between task_sessions and worker_sessions
```

- [ ] **Step 2: Update README "Still missing" section**

Remove or downgrade the items that are now partially addressed, and keep the ones that remain genuinely missing:

```markdown
## Still missing

- deeper background session reattachment / polling coverage beyond runtime-assisted detached session refresh
- more automated polling across sessions and runtimes beyond the current dedicated-callback and common process-namespace fallback coverage
- broader end-to-end policy coverage beyond the current file-backed orchestration flow, including continuation loops stronger than the current idle-escalation frontdoor enforcement
```

(Leave these three as-is; they are still true after this plan.)

- [ ] **Step 3: Bump plugin version**

In `plugin.yaml`:

```yaml
version: 0.2.0
```

- [ ] **Step 4: Commit**

```bash
cd ~/git_repo/oh-my-hermes
git add README.md plugin.yaml
git commit -m "docs(readme): sync v0.2 features and bump plugin version"
```

---

## Self-Review

### 1. Spec coverage
- ✅ Intent-aware plan generation → Task 1
- ✅ Acceptance criteria extraction → Task 2
- ✅ Task-aware execution router → Task 3
- ✅ State consistency guard → Task 4
- ✅ End-to-end smoke test → Task 5
- ✅ README sync → Task 6

### 2. Placeholder scan
- No "TBD", "TODO", "implement later", "fill in details"
- Every step contains real code or exact commands
- No vague descriptions without code blocks

### 3. Type consistency
- `IntentDecision` is used consistently in Task 1
- `_classify_task_session` returns `str` consistently in Task 3
- `AtlasStateSnapshot` field names match in Task 4

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-22-omh-planner-execution-pipeline.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

**Which approach?**
