# OMH Automated Polling Across Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically refresh detached worker supervision state when OMH re-entry surfaces are used in a new session, so running/completed background workers are reflected without requiring a manual `omh-exec poll` first.

**Architecture:** Add a tiny supervision refresh helper that accepts an optional process-poll callback. Wrapper/factory entrypoints for `omh-status`, `omh-resume`, and the continuation hook will call that helper before reading state. If no callback exists, behavior remains unchanged. This keeps pure state readers mostly intact while enabling cross-session polling when the runtime exposes a poll surface.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Add a supervision refresh helper with callback-based polling

**Files:**
- Create: `supervision_refresh.py`
- Test: `tests/test_omh_supervision_refresh_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove a running detached session can be refreshed through an injected callback and persisted back into state.

```python
def test_refresh_detached_worker_supervision_persists_completed_poll_result():
    refreshed = refresh_module.refresh_detached_worker_supervision(
        workspace,
        process_poller=lambda session_id: {
            'status': 'completed',
            'observation': 'process exited cleanly',
            'exit_code': 0,
        },
    )

    assert refreshed.state['worker_orchestration']['mode'] == 'awaiting-worker-result'
```

```python
def test_refresh_detached_worker_supervision_is_noop_without_running_detached_session():
    refreshed = refresh_module.refresh_detached_worker_supervision(
        workspace,
        process_poller=lambda session_id: {'status': 'completed'},
    )

    assert refreshed.state == original_snapshot.state
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_supervision_refresh_plugin.py
```

Expected: FAIL because the helper does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement a helper that:
- reads the current OMH state
- detects an active detached worker with supervision status `running`
- calls an injected `process_poller(session_id)` callback if provided
- accepts `status`, optional `observation`, and optional `exit_code`
- persists the resulting supervision poll back into the state file using the existing worker orchestration helpers
- returns a fresh `AtlasStateSnapshot`
- becomes a no-op when no callback exists or no running detached session exists

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_supervision_refresh_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supervision_refresh.py tests/test_omh_supervision_refresh_plugin.py
git commit -m "feat: add omh detached supervision refresh helper"
```

### Task 2: Wire automated refresh into status, resume, and continuation entrypoints

**Files:**
- Modify: `__init__.py`
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Modify: `continuation_hooks.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that inject a fake poll callback through a fake plugin context and verify auto-refresh occurs before rendering.

```python
def test_handle_omh_status_command_auto_polls_detached_worker_when_ctx_exposes_process_poller():
    result = handler('', workspace=workspace)
    assert 'Worker Supervision: detached session proc-123 (completed)' in result
```

```python
def test_handle_omh_resume_command_auto_polls_detached_worker_when_poller_available():
    result = handler('', workspace=workspace)
    assert 'Detached Worker Status: completed' in result
```

```python
def test_pre_llm_call_refreshes_detached_worker_before_building_continuation_context():
    result = hook(user_message='continue', platform='cli', is_first_turn=False)
    assert 'Worker Status: completed' in result['context']
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
```

Expected: FAIL because entrypoints do not auto-refresh supervision state yet.

- [ ] **Step 3: Write minimal implementation**

Implement wrapper/factory logic that:
- detects an optional context callback like `ctx.poll_background_process(session_id)`
- calls the new refresh helper before status/resume/continuation reads
- leaves behavior unchanged when the callback is missing
- keeps `omh_status.py` and `omh_resume.py` callable directly with optional poller injection for tests

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add __init__.py omh_status.py omh_resume.py continuation_hooks.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
git commit -m "feat: auto-refresh detached supervision on omh reentry"
```

### Task 3: Update docs and run full verification

**Files:**
- Modify: `README.md`
- Create: `docs/plans/2026-04-20-omh-automated-polling.md`

- [ ] **Step 1: Update docs**

Document that OMH can now auto-refresh detached worker supervision state on status/resume/continuation entry when the runtime exposes a process polling callback.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS with the full suite green.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-automated-polling.md
git commit -m "docs: add automated polling plan and readme note"
```