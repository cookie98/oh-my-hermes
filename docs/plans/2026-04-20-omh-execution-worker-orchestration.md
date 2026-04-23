# OMH Execution Worker Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Hermes-native execution worker orchestration layer so `omh-start-work` / `omh-exec` can dispatch the current task into a tracked worker lane instead of stopping at state transitions and guidance text.

**Architecture:** Keep OMH as the control plane and implement a narrow v1 orchestration contract inside the plugin. The plugin should persist worker dispatch state, render execution handoffs, and track worker outcomes, but it should not become a full background process manager in this phase. The first version should orchestrate one active implementation worker per execution session, with optional future expansion for specialist support lanes.

**Tech Stack:** Python 3, Hermes plugin commands, JSON state in `.omh/state/atlas-state.json`, markdown handoff artifacts in `.omh/handoffs/`, pytest.

---

## Scope and boundaries

This plan intentionally targets **control-plane orchestration**, not full autonomous process supervision.

In scope:
- persist worker dispatch metadata in OMH state
- generate a deterministic worker handoff from the current plan/task
- let `omh-exec` move between `dispatch-ready`, `dispatched`, `awaiting-result`, `completed`, and `blocked`
- keep verification/fix loops intact after worker execution result is reported
- surface worker orchestration status through `omh-status` and `omh-ulw`

Out of scope for this phase:
- long-running background process supervision
- multiple concurrent implementation workers mutating the same worktree
- automatic delegate-task invocation from plugin code
- full explore/librarian/oracle parallel lane execution

## File structure

### Create
- `~/git_repo/oh-my-hermes/worker_orchestration.py` — worker orchestration helpers: worker session schema, handoff creation, dispatch/result transition helpers, state normalization helpers.
- `~/git_repo/oh-my-hermes/tests/test_omh_worker_orchestration_plugin.py` — unit tests for the new worker orchestration helpers.

### Modify
- `~/git_repo/oh-my-hermes/omh_start_work.py` — seed empty worker orchestration state on fresh execution bootstrap.
- `~/git_repo/oh-my-hermes/atlas_state.py` — normalize/validate worker session metadata and expose current worker posture.
- `~/git_repo/oh-my-hermes/omh_exec.py` — dispatch current exec-stage task into a worker lane and track worker result transitions.
- `~/git_repo/oh-my-hermes/omh_status.py` — render worker orchestration information in text and JSON output.
- `~/git_repo/oh-my-hermes/omh_ulw.py` — ensure resumable execution through `omh-ulw` can surface dispatch/awaiting-result states cleanly.
- `~/git_repo/oh-my-hermes/__init__.py` — register any new helper command only if one is truly needed; prefer extending existing surfaces.
- `~/git_repo/oh-my-hermes/tests/test_omh_exec_driver_plugin.py` — cover new exec-stage dispatch/worker-result behavior.
- `~/git_repo/oh-my-hermes/tests/test_omh_start_work_plugin.py` — cover worker-state seeding.
- `~/git_repo/oh-my-hermes/tests/test_omh_ulw_exec_integration_plugin.py` — cover `omh-ulw` integration with active worker state.
- `~/git_repo/oh-my-hermes/tests/test_omh_status_plugin.py` — add if status coverage is easier in a dedicated file; otherwise extend existing status-oriented coverage.
- `~/git_repo/oh-my-hermes/README.md` — update current-state documentation after behavior is implemented.

## Worker orchestration contract (v1)

State should gain a stable top-level object:

```json
{
  "worker_orchestration": {
    "active_worker_id": null,
    "current_task_slug": null,
    "mode": "idle",
    "backend": "hermes-native",
    "worker_sessions": {}
  }
}
```

Each `worker_sessions.<worker_id>` entry should look like:

```json
{
  "worker_id": "exec-1",
  "role": "build",
  "task_slug": "confirm-scope-and-acceptance-criteria-for-add-auth-middleware",
  "status": "dispatch_ready",
  "wave": 1,
  "handoff_path": ".omh/handoffs/exec-1.md",
  "summary": null,
  "result": null,
  "started_at": "2026-04-20T00:00:00Z",
  "updated_at": "2026-04-20T00:00:00Z"
}
```

Allowed worker session statuses in v1:
- `dispatch_ready`
- `dispatched`
- `awaiting_result`
- `completed`
- `blocked`
- `cancelled`

## Command/behavior contract (v1)

### `omh-start-work`
- Fresh execution bootstrap must seed `worker_orchestration` with `mode: "idle"`, `active_worker_id: null`, and an empty `worker_sessions` map.
- It must not dispatch a worker immediately.

### `omh-exec` when `current_stage == "exec"`
- With no args:
  - if no active worker exists, return deterministic guidance for dispatching the current task
  - if a worker is already dispatched or awaiting result, return deterministic status text showing the worker id, role, task slug, and handoff path
- With `run`:
  - create a worker session for the current task if none exists
  - write an execution handoff markdown artifact under `.omh/handoffs/<worker-id>.md`
  - persist the worker session with `status: "awaiting_result"`
  - return a human-readable dispatch summary including the exact task slug and handoff path
- With `complete <summary...>`:
  - require an active worker session for the current task
  - mark the worker session `completed`
  - record the summary on the worker session
  - transition the task session to `completed`
- With `block <summary...>`:
  - require an active worker session for the current task
  - mark the worker session `blocked`
  - record the summary on the worker session
  - transition the task session to `blocked`

### `omh-ulw`
- For resumable implementation/fix work, continue routing through `omh-exec`.
- If the execution session has an active worker awaiting result, `omh-ulw` should surface that state instead of dropping into research or generic guidance.

### `omh-status`
- JSON output should include `worker_orchestration.mode`, `active_worker_id`, and a summary of current worker session state.
- Text output should show whether execution is idle, waiting to dispatch, or waiting for worker result.

## Task breakdown

### Task 1: Add worker orchestration helpers and state normalization

**Files:**
- Create: `~/git_repo/oh-my-hermes/worker_orchestration.py`
- Modify: `~/git_repo/oh-my-hermes/atlas_state.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_worker_orchestration_plugin.py`

- [ ] **Step 1: Write the failing test for worker orchestration normalization**

```python
def test_normalize_worker_orchestration_seeds_default_shape():
    module = _load_module('worker_orchestration')

    normalized = module.normalize_worker_orchestration({})

    assert normalized['active_worker_id'] is None
    assert normalized['current_task_slug'] is None
    assert normalized['mode'] == 'idle'
    assert normalized['backend'] == 'hermes-native'
    assert normalized['worker_sessions'] == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_worker_orchestration_plugin.py::test_normalize_worker_orchestration_seeds_default_shape
```

Expected: FAIL because `worker_orchestration.py` does not exist yet.

- [ ] **Step 3: Implement worker orchestration normalization helpers**

Create `~/git_repo/oh-my-hermes/worker_orchestration.py` with:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

VALID_WORKER_STATUSES = {
    'dispatch_ready',
    'dispatched',
    'awaiting_result',
    'completed',
    'blocked',
    'cancelled',
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def normalize_worker_orchestration(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(payload or {})
    sessions = raw.get('worker_sessions') if isinstance(raw.get('worker_sessions'), dict) else {}
    normalized_sessions: Dict[str, Dict[str, Any]] = {}
    for worker_id, item in sessions.items():
        entry = dict(item) if isinstance(item, dict) else {}
        wid = str(entry.get('worker_id') or worker_id).strip() or str(worker_id).strip() or 'worker'
        status = str(entry.get('status') or 'dispatch_ready').strip().lower()
        if status not in VALID_WORKER_STATUSES:
            status = 'dispatch_ready'
        entry['worker_id'] = wid
        entry['role'] = str(entry.get('role') or 'build').strip() or 'build'
        entry['task_slug'] = str(entry.get('task_slug') or '').strip() or None
        entry['status'] = status
        entry['wave'] = entry.get('wave')
        entry['handoff_path'] = entry.get('handoff_path')
        entry['summary'] = entry.get('summary')
        entry['result'] = entry.get('result')
        entry['started_at'] = entry.get('started_at')
        entry['updated_at'] = entry.get('updated_at')
        normalized_sessions[wid] = entry

    return {
        'active_worker_id': raw.get('active_worker_id'),
        'current_task_slug': raw.get('current_task_slug'),
        'mode': str(raw.get('mode') or 'idle').strip() or 'idle',
        'backend': str(raw.get('backend') or 'hermes-native').strip() or 'hermes-native',
        'worker_sessions': normalized_sessions,
    }
```

- [ ] **Step 4: Teach `atlas_state.py` to normalize worker orchestration**

Modify the state normalizer to import and apply the helper:

```python
from .worker_orchestration import normalize_worker_orchestration
```

and inside `_normalize_state`:

```python
state['worker_orchestration'] = normalize_worker_orchestration(state.get('worker_orchestration'))
```

- [ ] **Step 5: Run the new helper test**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_worker_orchestration_plugin.py::test_normalize_worker_orchestration_seeds_default_shape
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C ~/git_repo/oh-my-hermes add worker_orchestration.py atlas_state.py tests/test_omh_worker_orchestration_plugin.py
git -C ~/git_repo/oh-my-hermes commit -m "feat: add worker orchestration state helpers"
```

### Task 2: Seed worker orchestration during `omh-start-work`

**Files:**
- Modify: `~/git_repo/oh-my-hermes/omh_start_work.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_start_work_plugin.py`

- [ ] **Step 1: Write the failing bootstrap test**

Add a test asserting fresh state includes worker orchestration defaults:

```python
def test_build_start_work_payload_seeds_worker_orchestration_defaults():
    module = _load_module('omh_start_work')
    plan_module = _load_module('omh_plan')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)

        payload = module.build_start_work_payload('', workspace=workspace)
        orchestration = payload['state']['worker_orchestration']

        assert orchestration['mode'] == 'idle'
        assert orchestration['active_worker_id'] is None
        assert orchestration['worker_sessions'] == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_start_work_plugin.py::test_build_start_work_payload_seeds_worker_orchestration_defaults
```

Expected: FAIL because the fresh state does not contain `worker_orchestration` yet.

- [ ] **Step 3: Seed worker orchestration in `_build_initial_state`**

In `omh_start_work.py`, import the helper and add:

```python
'worker_orchestration': normalize_worker_orchestration({}),
```

inside the returned initial state payload.

- [ ] **Step 4: Run the focused bootstrap test**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_start_work_plugin.py::test_build_start_work_payload_seeds_worker_orchestration_defaults
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ~/git_repo/oh-my-hermes add omh_start_work.py tests/test_omh_start_work_plugin.py
git -C ~/git_repo/oh-my-hermes commit -m "feat: seed worker orchestration on start work"
```

### Task 3: Add exec-stage worker dispatch and result tracking

**Files:**
- Modify: `~/git_repo/oh-my-hermes/worker_orchestration.py`
- Modify: `~/git_repo/oh-my-hermes/omh_exec.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_exec_driver_plugin.py`

- [ ] **Step 1: Write the failing dispatch test**

Add a test for `omh-exec run`:

```python
def test_handle_omh_exec_command_dispatches_current_exec_task_into_worker_lane():
    module = _load_module('omh_exec')
    plan_module = _load_module('omh_plan')
    start_module = _load_module('omh_start_work')

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        plan_module.build_plan_payload('add auth middleware', workspace=workspace)
        state = start_module.build_start_work_payload('', workspace=workspace)['state']
        state_path = _write_state(workspace, state)

        result = module.handle_omh_exec_command('run', workspace=workspace)
        updated = json.loads(state_path.read_text(encoding='utf-8'))
        orchestration = updated['worker_orchestration']
        worker_id = orchestration['active_worker_id']
        worker = orchestration['worker_sessions'][worker_id]

        assert 'Dispatched OMH exec worker' in result
        assert orchestration['mode'] == 'awaiting_result'
        assert worker['status'] == 'awaiting_result'
        assert worker['task_slug'] == 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware'
```

- [ ] **Step 2: Run the dispatch test to verify it fails**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_exec_driver_plugin.py::test_handle_omh_exec_command_dispatches_current_exec_task_into_worker_lane
```

Expected: FAIL because `run` is not currently supported.

- [ ] **Step 3: Implement worker dispatch helpers**

Extend `worker_orchestration.py` with:
- `build_worker_id(state)`
- `dispatch_exec_worker(state, workspace, task_slug, summary=None)`
- handoff writer that creates `.omh/handoffs/<worker-id>.md`
- `record_worker_result(state, outcome, summary)`

The dispatch helper should set:

```python
orchestration['active_worker_id'] = worker_id
orchestration['current_task_slug'] = task_slug
orchestration['mode'] = 'awaiting_result'
worker_sessions[worker_id]['status'] = 'awaiting_result'
```

- [ ] **Step 4: Extend `omh_exec.py` for `run`**

Add explicit support in exec stage:

```python
if raw == 'run':
    next_state, worker = dispatch_exec_worker(snapshot.state, workspace=root, task_slug=str(current_task_slug))
    state_path = _write_state(root, next_state)
    return {
        'mode': 'worker-dispatched',
        'workspace': str(root),
        'state_path': str(state_path),
        'worker': worker,
        'state': next_state,
    }
```

Render as:

```python
if mode == 'worker-dispatched':
    worker = payload.get('worker') or {}
    return (
        'Dispatched OMH exec worker\n\n'
        f'Worker: {worker.get("worker_id")}\n'
        f'Role: {worker.get("role")}\n'
        f'Task: {worker.get("task_slug")}\n'
        f'Handoff: {worker.get("handoff_path") or "none"}'
    )
```

- [ ] **Step 5: Attach worker result recording to `complete` and `block`**

Before task-session transition, update the active worker session:

```python
next_state = record_worker_result(snapshot.state, outcome=next_status, summary=summary)
next_state = transition_task_session(next_state, task_slug=str(current_task_slug), next_status=next_status)
```

- [ ] **Step 6: Run focused exec driver tests**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_exec_driver_plugin.py
```

Expected: PASS including the new dispatch test.

- [ ] **Step 7: Commit**

```bash
git -C ~/git_repo/oh-my-hermes add worker_orchestration.py omh_exec.py tests/test_omh_exec_driver_plugin.py
git -C ~/git_repo/oh-my-hermes commit -m "feat: dispatch exec tasks into worker lane"
```

### Task 4: Surface worker orchestration through status and ULW

**Files:**
- Modify: `~/git_repo/oh-my-hermes/omh_status.py`
- Modify: `~/git_repo/oh-my-hermes/omh_ulw.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_ulw_exec_integration_plugin.py`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_status_plugin.py`

- [ ] **Step 1: Write the failing status test**

Create a test that status JSON exposes worker orchestration:

```python
def test_build_status_payload_includes_worker_orchestration_summary():
    module = _load_module('omh_status')
    state = _seed_exec_state(workspace)
    state['worker_orchestration'] = {
        'active_worker_id': 'exec-1',
        'current_task_slug': 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware',
        'mode': 'awaiting_result',
        'backend': 'hermes-native',
        'worker_sessions': {
            'exec-1': {
                'worker_id': 'exec-1',
                'role': 'build',
                'task_slug': 'confirm-scope-and-acceptance-criteria-for-add-auth-middleware',
                'status': 'awaiting_result',
            }
        }
    }
```

and assert:

```python
assert payload['worker_orchestration']['mode'] == 'awaiting_result'
assert payload['worker_orchestration']['active_worker_id'] == 'exec-1'
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_status_plugin.py::test_build_status_payload_includes_worker_orchestration_summary
```

Expected: FAIL because `omh_status.py` does not expose the field yet.

- [ ] **Step 3: Add worker orchestration summary to `omh_status.py`**

Include:

```python
orchestration = state.get('worker_orchestration') if isinstance(state.get('worker_orchestration'), dict) else {}
payload['worker_orchestration'] = {
    'mode': orchestration.get('mode'),
    'active_worker_id': orchestration.get('active_worker_id'),
    'current_task_slug': orchestration.get('current_task_slug'),
}
```

and extend text rendering with a line such as:

```python
f'Worker Mode: {(payload.get("worker_orchestration") or {}).get("mode") or "idle"}\n'
```

- [ ] **Step 4: Add a ULW integration test**

Add a test asserting `omh-ulw` surfaces the awaiting-result state instead of generic guidance:

```python
def test_handle_omh_ulw_command_surfaces_active_worker_waiting_for_result():
    ...
    assert 'Dispatched OMH exec worker' in dispatch_result
    assert 'awaiting_result' in status_or_ulw_result.lower()
```

- [ ] **Step 5: Update `omh_ulw.py` only if needed**

If the existing `omh-exec` integration already renders enough information, keep `omh_ulw.py` unchanged. Only patch it if the integration test proves the current behavior is too vague.

- [ ] **Step 6: Run focused integration/status tests**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_ulw_exec_integration_plugin.py ~/git_repo/oh-my-hermes/tests/test_omh_status_plugin.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git -C ~/git_repo/oh-my-hermes add omh_status.py omh_ulw.py tests/test_omh_ulw_exec_integration_plugin.py tests/test_omh_status_plugin.py
git -C ~/git_repo/oh-my-hermes commit -m "feat: surface worker orchestration in status"
```

### Task 5: Run regression verification and update docs

**Files:**
- Modify: `~/git_repo/oh-my-hermes/README.md`
- Test: `~/git_repo/oh-my-hermes/tests/test_omh_*.py`

- [ ] **Step 1: Update README implementation status**

Replace stale “Still missing” bullets so they distinguish between:
- implemented worker orchestration v1
- still-missing background process supervision
- still-missing richer research lane delegation

- [ ] **Step 2: Run the full OMH regression suite**

Run:
```bash
pytest -q ~/git_repo/oh-my-hermes/tests/test_omh_*.py
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git -C ~/git_repo/oh-my-hermes add README.md tests
git -C ~/git_repo/oh-my-hermes commit -m "docs: update worker orchestration status"
```

## Self-review

- Spec coverage: this plan covers state shape, bootstrap seeding, exec dispatch, worker result tracking, status exposure, ULW integration, tests, and README refresh.
- Placeholder scan: there are no `TODO`, `TBD`, or “implement later” placeholders; each task names exact files and commands.
- Type consistency: worker orchestration is named consistently as `worker_orchestration`, with `active_worker_id`, `current_task_slug`, `mode`, `backend`, and `worker_sessions`.

## Recommendation

Implement this, but **only at the v1 control-plane level first**. That gets OMH past “state machine only” and into “real worker-aware orchestration” without prematurely building a background runtime we may regret.
