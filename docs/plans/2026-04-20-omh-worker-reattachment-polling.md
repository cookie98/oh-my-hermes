# OMH Worker Reattachment / Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reattach to persisted OMH worker state across sessions by inferring a resumable active worker from `worker_sessions` and surfacing that state in status, resume, and continuation reminders.

**Architecture:** Extend the existing file-backed worker orchestration model with deterministic reattachment inference. The inference lives close to worker orchestration normalization so all higher-level readers (`atlas_state`, `omh_status`, `omh_resume`, continuation hooks) get a stable view without bespoke recovery logic. Polling is limited to state-file reattachment in this slice; no background process control is introduced yet.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` orchestration state.

---

### Task 1: Add deterministic worker reattachment inference

**Files:**
- Modify: `worker_orchestration.py`
- Test: `tests/test_omh_worker_orchestration_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove normalization can recover an active worker from persisted `worker_sessions` when `active_worker_id` is missing or stale.

```python
def test_normalize_worker_orchestration_infers_active_worker_from_latest_nonterminal_session():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'mode': 'idle',
            'worker_sessions': {
                'worker-old': {
                    'worker_id': 'worker-old',
                    'task_slug': 'scope',
                    'status': 'completed',
                    'updated_at': '2026-04-20T00:00:00Z',
                },
                'worker-live': {
                    'worker_id': 'worker-live',
                    'task_slug': 'implement',
                    'status': 'dispatching',
                    'updated_at': '2026-04-20T00:05:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-live'
    assert normalized['current_task_slug'] == 'implement'
    assert normalized['mode'] == 'dispatching'
```

```python
def test_normalize_worker_orchestration_clears_stale_active_worker_reference():
    orchestration_module = _load_module('worker_orchestration')

    normalized = orchestration_module.normalize_worker_orchestration(
        {
            'active_worker_id': 'missing-worker',
            'current_task_slug': 'old-task',
            'mode': 'dispatching',
            'worker_sessions': {
                'worker-ready': {
                    'worker_id': 'worker-ready',
                    'task_slug': 'confirm-scope',
                    'status': 'running',
                    'updated_at': '2026-04-20T00:06:00Z',
                },
            },
        }
    )

    assert normalized['active_worker_id'] == 'worker-ready'
    assert normalized['current_task_slug'] == 'confirm-scope'
    assert normalized['mode'] == 'running'
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest -q tests/test_omh_worker_orchestration_plugin.py
```

Expected: the new assertions fail because normalization does not currently infer or repair active worker state.

- [ ] **Step 3: Write minimal implementation**

Implement deterministic reattachment helpers in `worker_orchestration.py`:
- identify non-terminal worker statuses
- pick the latest non-terminal worker session by timestamp fields (`updated_at`, `dispatched_at` fallback)
- restore `active_worker_id`, `current_task_slug`, and `mode` from that session when the stored top-level values are missing or stale
- leave terminal-only worker histories idle

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest -q tests/test_omh_worker_orchestration_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker_orchestration.py tests/test_omh_worker_orchestration_plugin.py
git commit -m "feat: infer omh worker reattachment state"
```

### Task 2: Surface reattachment details in OMH readers

**Files:**
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Modify: `continuation_hooks.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add assertions that a recovered worker is visible to user-facing readers.

```python
def test_build_status_payload_includes_reattachment_summary_when_worker_is_recovered():
    payload = status_module.build_status_payload(workspace=workspace)

    assert payload['worker_orchestration']['active_worker_id'] == 'worker-live'
    assert payload['worker_orchestration']['mode'] == 'dispatching'
    assert payload['worker_reattachment'] == {
        'needed': True,
        'active_worker_id': 'worker-live',
        'current_task_slug': 'implement-auth',
        'status': 'dispatching',
    }
```

```python
def test_render_resume_text_mentions_recovered_worker_context():
    text = resume_module.handle_omh_resume_command('', workspace=workspace)

    assert 'Recovered Worker: worker-live' in text
    assert 'Worker Status: dispatching' in text
```

```python
def test_build_continuation_context_mentions_recovered_worker_hint():
    context = continuation_module.build_continuation_context(snapshot)

    assert 'Recovered Worker: worker-live' in context
    assert 'Worker Status: dispatching' in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
```

Expected: FAIL because those surfaces do not yet include worker reattachment summary/hints.

- [ ] **Step 3: Write minimal implementation**

Extend the payload/rendering surfaces to expose a compact `worker_reattachment` summary when a non-idle worker is present after normalization. Keep the text concise and deterministic:
- status JSON gets a dedicated `worker_reattachment` object
- status text adds one human-readable recovery line
- resume text mentions recovered worker + status when present
- continuation reminder includes recovered worker + worker status

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_status.py omh_resume.py continuation_hooks.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py
git commit -m "feat: surface omh worker reattachment hints"
```

### Task 3: Refresh docs and run full verification

**Files:**
- Modify: `README.md`
- Create: `docs/plans/2026-04-20-omh-worker-reattachment-polling.md`

- [ ] **Step 1: Update docs**

Document that OMH now infers worker reattachment state from persisted orchestration metadata and surfaces that state in status/resume/continuation flows.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS with the full suite green.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-worker-reattachment-polling.md
git commit -m "docs: add worker reattachment polling plan and readme note"
```
