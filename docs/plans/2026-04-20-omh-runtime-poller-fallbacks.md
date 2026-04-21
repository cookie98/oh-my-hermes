# OMH Runtime Poller Fallbacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let OMH auto-refresh detached worker supervision across more runtimes by resolving generic process polling surfaces from plugin context instead of depending only on one explicit `poll_background_process` callback.

**Architecture:** Keep the existing `refresh_detached_worker_supervision(..., process_poller=...)` contract intact and widen only the adapter layer in `__init__.py`. `_resolve_process_poller(ctx)` should discover a small fallback chain from common context shapes (`ctx.poll_background_process`, `ctx.process.poll_background_process`, `ctx.process.poll`, `ctx.process_manager.poll_background_process`) and normalize them into the same callable signature used by status/resume/pre-LLM entrypoints.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Add runtime poller fallback resolution

**Files:**
- Modify: `__init__.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving `_resolve_process_poller(ctx)` supports generic process namespaces.

```python
def test_resolve_process_poller_prefers_direct_ctx_callback():
    poller = module._resolve_process_poller(ctx)
    assert poller is not None
    assert poller('proc-1')['status'] == 'completed'
```

```python
def test_resolve_process_poller_falls_back_to_ctx_process_poll_method():
    poller = module._resolve_process_poller(ctx)
    assert poller is not None
    assert poller('proc-2')['status'] == 'completed'
```

```python
def test_resolve_process_poller_falls_back_to_process_manager_namespace():
    poller = module._resolve_process_poller(ctx)
    assert poller is not None
    assert poller('proc-3')['status'] == 'failed'
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py
```

Expected: FAIL because `_resolve_process_poller` only supports the direct callback today.

- [ ] **Step 3: Write minimal implementation**

Extend `_resolve_process_poller(ctx)` to try the fallback chain in priority order:
- `ctx.poll_background_process(session_id)`
- `ctx.process.poll_background_process(session_id)`
- `ctx.process.poll(session_id)`
- `ctx.process_manager.poll_background_process(session_id)`

Normalize each discovered callable into the same `Callable[[str], dict | None]` shape already used by the refresh helper.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add __init__.py tests/test_omh_continuation_hooks_plugin.py
git commit -m "feat: add runtime poller fallback resolution"
```

### Task 2: Prove the fallback chain works at OMH entry surfaces

**Files:**
- Modify: `tests/test_omh_continuation_hooks_plugin.py`
- Modify: `tests/test_omh_status_plugin.py`
- Modify: `tests/test_omh_resume_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add end-to-end tests that use generic runtime namespaces instead of the direct callback.

```python
def test_pre_llm_call_refreshes_worker_via_ctx_process_poll_fallback():
    result = hook(user_message='continue', platform='cli', is_first_turn=True)
    assert 'Detached Worker Status: completed' in result['context']
```

```python
def test_status_factory_refreshes_worker_via_ctx_process_manager_fallback():
    result = handler('')
    assert 'Worker Supervision: detached session proc-123 (completed)' in result
```

```python
def test_resume_factory_refreshes_worker_via_ctx_process_poll_background_process_fallback():
    result = handler('')
    assert 'Detached Worker Status: completed' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
```

Expected: FAIL because the factories only work with the direct callback today.

- [ ] **Step 3: Write minimal implementation**

Keep the entrypoints unchanged and rely on the new resolver so the factories automatically pass the discovered poller into existing refresh logic.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
git commit -m "test: cover runtime poller fallback entrypoints"
```

### Task 3: Refresh docs and run full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-04-20-omh-runtime-poller-fallbacks.md`

- [ ] **Step 1: Update docs**

Document that OMH can now auto-refresh detached worker supervision from more generic runtime process namespaces, not only a dedicated `poll_background_process` callback.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-runtime-poller-fallbacks.md
git commit -m "docs: add runtime poller fallback plan and readme note"
```
