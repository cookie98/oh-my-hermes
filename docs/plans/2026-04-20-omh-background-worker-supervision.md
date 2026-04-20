# OMH Background Worker Supervision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add detached/background worker lifecycle supervision to OMH so persisted state can track a live background worker session and surface that lifecycle across exec/status/resume/continuation flows.

**Architecture:** Keep this slice Hermes-native and file-backed. Do not implement actual process spawning inside OMH yet; instead add a supervision contract to worker orchestration, let `omh-exec` attach/poll detached session metadata, and expose that state through observability surfaces. This gives OMH a truthful detached-worker lifecycle without pretending to own the runtime spawn layer already.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json`, existing OMH worker/task state helpers.

---

### Task 1: Add detached worker supervision state + helpers

**Files:**
- Modify: `worker_orchestration.py`
- Test: `tests/test_omh_worker_orchestration_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add focused tests for a nested supervision contract on worker sessions.

```python
def test_dispatch_exec_worker_seeds_detached_supervision_metadata():
    next_state = orchestration_module.dispatch_exec_worker(state, workspace, task_slug='task-a', summary='draft handoff')
    worker_id = next_state['worker_orchestration']['active_worker_id']
    session = next_state['worker_orchestration']['worker_sessions'][worker_id]

    assert session['supervision'] == {
        'detached': False,
        'session_id': None,
        'status': 'untracked',
        'command': None,
        'attached_at': None,
        'last_polled_at': None,
        'last_exit_code': None,
        'last_observation': None,
    }
```

```python
def test_attach_worker_supervision_marks_active_worker_as_detached_running():
    next_state = orchestration_module.attach_worker_supervision(state, session_id='proc-123', command='codex exec ...')
    session = next_state['worker_orchestration']['worker_sessions']['worker-a']

    assert session['supervision']['detached'] is True
    assert session['supervision']['session_id'] == 'proc-123'
    assert session['supervision']['status'] == 'running'
    assert next_state['worker_orchestration']['mode'] == 'running'
```

```python
def test_record_worker_supervision_poll_tracks_terminal_background_state_without_consuming_task_result():
    next_state = orchestration_module.record_worker_supervision_poll(
        state,
        session_id='proc-123',
        status='completed',
        observation='process exited cleanly',
        exit_code=0,
    )
    session = next_state['worker_orchestration']['worker_sessions']['worker-a']

    assert session['supervision']['status'] == 'completed'
    assert session['supervision']['last_exit_code'] == 0
    assert session['supervision']['last_observation'] == 'process exited cleanly'
    assert next_state['worker_orchestration']['active_worker_id'] == 'worker-a'
    assert next_state['worker_orchestration']['mode'] == 'awaiting-worker-result'
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q test_omh_worker_orchestration_plugin.py
```

Expected: FAIL because worker sessions do not yet carry supervision metadata and the helper functions do not exist.

- [ ] **Step 3: Write minimal implementation**

In `worker_orchestration.py`:
- add a normalized `supervision` payload per worker session
- keep valid supervision statuses deliberately small (`untracked`, `running`, `completed`, `failed`, `lost`)
- add `attach_worker_supervision(...)`
- add `record_worker_supervision_poll(...)`
- add `build_worker_supervision_summary(...)`
- update dispatch/result helpers so supervision metadata survives state transitions cleanly

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q test_omh_worker_orchestration_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker_orchestration.py tests/test_omh_worker_orchestration_plugin.py
git commit -m "feat: add detached worker supervision state"
```

### Task 2: Wire supervision through `omh-exec`

**Files:**
- Modify: `omh_exec.py`
- Test: `tests/test_omh_exec_driver_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add explicit command-surface tests for detached supervision.

```python
def test_handle_omh_exec_command_attaches_detached_supervision_to_active_worker():
    result = module.handle_omh_exec_command('supervise proc-123 codex exec worker lane', workspace=workspace)
    updated = json.loads(state_path.read_text(encoding='utf-8'))
    worker_id = updated['worker_orchestration']['active_worker_id']
    session = updated['worker_orchestration']['worker_sessions'][worker_id]

    assert 'Attached OMH worker supervision' in result
    assert session['supervision']['session_id'] == 'proc-123'
    assert session['supervision']['status'] == 'running'
```

```python
def test_handle_omh_exec_command_records_detached_worker_poll_update():
    result = module.handle_omh_exec_command('poll proc-123 completed process exited cleanly', workspace=workspace)
    updated = json.loads(state_path.read_text(encoding='utf-8'))
    session = updated['worker_orchestration']['worker_sessions'][worker_id]

    assert 'Recorded OMH worker supervision poll' in result
    assert session['supervision']['status'] == 'completed'
    assert updated['worker_orchestration']['mode'] == 'awaiting-worker-result'
```

```python
def test_handle_omh_exec_command_rejects_supervision_poll_for_unknown_session_id():
    result = module.handle_omh_exec_command('poll proc-missing running still alive', workspace=workspace)
    assert 'No active detached OMH worker matched session id' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q test_omh_exec_driver_plugin.py
```

Expected: FAIL because `omh-exec` does not yet understand `supervise` / `poll` detached lifecycle commands.

- [ ] **Step 3: Write minimal implementation**

Extend `omh_exec.py` to support:
- `omh-exec supervise <session-id> [command-summary...]`
- `omh-exec poll <session-id> <running|completed|failed|lost> [observation...]`

Rules:
- only valid while an active worker exists for the current execution
- do not auto-complete or auto-block the task on supervision polls
- use terminal poll statuses to move orchestration mode to `awaiting-worker-result`
- keep existing `run|complete|block` behavior unchanged

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q test_omh_exec_driver_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_exec.py tests/test_omh_exec_driver_plugin.py
git commit -m "feat: track detached worker supervision in exec"
```

### Task 3: Surface detached lifecycle in status/resume/continuation

**Files:**
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Modify: `continuation_hooks.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add assertions for detached lifecycle observability.

```python
def test_build_status_payload_includes_worker_supervision_summary_for_detached_session():
    payload = status_module.build_status_payload(workspace=workspace)

    assert payload['worker_supervision'] == {
        'session_id': 'proc-123',
        'status': 'running',
        'detached': True,
        'last_exit_code': None,
        'last_observation': None,
    }
```

```python
def test_render_status_text_mentions_running_detached_worker_session():
    text = status_module.render_status_text(payload)

    assert 'Worker Supervision: detached session proc-123 (running)' in text
```

```python
def test_render_resume_text_mentions_detached_worker_supervision():
    result = resume_module.handle_omh_resume_command('', workspace=workspace)

    assert 'Detached Worker Session: proc-123' in result
    assert 'Detached Worker Status: running' in result
```

```python
def test_build_continuation_context_mentions_detached_worker_supervision_hint():
    context = continuation_module.build_continuation_context(snapshot)

    assert 'Detached Worker Session: proc-123' in context
    assert 'Detached Worker Status: running' in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q test_omh_status_plugin.py test_omh_resume_plugin.py test_omh_continuation_hooks_plugin.py
```

Expected: FAIL because supervision summary is not yet exposed outside worker state.

- [ ] **Step 3: Write minimal implementation**

Add compact detached-worker observability:
- JSON payload: `worker_supervision`
- status text: one short supervision line + lifecycle-specific guidance
- resume text: detached session/status lines when present
- continuation reminder: detached session/status hint when present

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q test_omh_status_plugin.py test_omh_resume_plugin.py test_omh_continuation_hooks_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_status.py omh_resume.py continuation_hooks.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
git commit -m "feat: surface detached worker supervision hints"
```

### Task 4: Refresh docs and run full verification

**Files:**
- Modify: `README.md`
- Create: `docs/plans/2026-04-20-omh-background-worker-supervision.md`

- [ ] **Step 1: Update docs**

Document that OMH now tracks detached/background worker lifecycle in state and can surface supervision hints before task-result collection.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-background-worker-supervision.md
git commit -m "docs: add background worker supervision plan and readme note"
```
