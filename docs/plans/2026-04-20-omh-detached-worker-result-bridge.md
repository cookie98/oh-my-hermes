# OMH Detached Worker Result Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn terminal detached-worker supervision state into an explicit, actionable OMH exec continuation path so a finished background worker can be adopted quickly without manual translation into `complete` vs `block` every time.

**Architecture:** Keep the worker/session model file-backed and derive a lightweight `worker result bridge` from existing detached supervision data instead of inventing a second async subsystem. The bridge should infer a recommended OMH exec action plus summary from supervision status / exit code / observation, surface that recommendation in status/resume/continuation/enforcement, and let `omh-exec accept` explicitly adopt the bridged outcome into the normal task-session transition flow.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Derive a worker result bridge from detached supervision terminal state

**Files:**
- Modify: `worker_orchestration.py`
- Test: `tests/test_omh_worker_orchestration_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving OMH can derive a recommended outcome from detached supervision terminal state.

```python
def test_build_worker_result_bridge_recommends_complete_for_clean_completed_detached_worker():
    bridge = module.build_worker_result_bridge(payload)
    assert bridge is not None
    assert bridge['ready'] is True
    assert bridge['recommended_action'] == 'complete'
    assert bridge['summary'] == 'process exited cleanly'
```

```python
def test_build_worker_result_bridge_recommends_block_for_failed_detached_worker():
    bridge = module.build_worker_result_bridge(payload)
    assert bridge is not None
    assert bridge['recommended_action'] == 'block'
    assert 'exit code 2' in bridge['summary']
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_worker_orchestration_plugin.py
```

Expected: FAIL because no worker result bridge helper exists yet.

- [ ] **Step 3: Write minimal implementation**

Implement `build_worker_result_bridge(...)` on top of normalized worker orchestration state. It should:
- detect an active worker session in `awaiting-worker-result`
- inspect detached supervision terminal state
- map clean completion to `complete`
- map failed/lost/nonzero exit to `block`
- reuse supervision observation when present, otherwise synthesize a short summary from status / exit code
- return `None` when no actionable bridge exists

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_worker_orchestration_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker_orchestration.py tests/test_omh_worker_orchestration_plugin.py
git commit -m "feat: add detached worker result bridge"
```

### Task 2: Surface the bridge in OMH re-entry / enforcement surfaces

**Files:**
- Modify: `continuation_enforcement.py`
- Modify: `continuation_hooks.py`
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Test: `tests/test_omh_continuation_enforcement_plugin.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving OMH surfaces the bridged recommendation instead of a vague generic worker-result reminder.

```python
def test_build_continuation_enforcement_uses_accept_action_for_ready_worker_result_bridge():
    enforcement = module.build_continuation_enforcement(snapshot)
    assert enforcement.strict is True
    assert 'omh-exec accept' in enforcement.next_action
```

```python
def test_build_continuation_context_includes_worker_result_bridge_lines():
    text = module.build_continuation_context(snapshot)
    assert 'Worker Result Bridge: ready (recommended=complete)' in text
    assert 'Suggested Command: omh-exec accept' in text
```

```python
def test_handle_omh_status_command_surfaces_worker_result_bridge_summary():
    text = module.handle_omh_status_command('', workspace=workspace)
    assert 'Worker Result Bridge: ready (recommended=complete)' in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
```

Expected: FAIL because worker result bridge is not yet surfaced.

- [ ] **Step 3: Write minimal implementation**

Update the user-facing surfaces so that:
- strict `awaiting-worker-result` enforcement prefers `omh-exec accept`
- continuation context shows bridge readiness / recommendation / suggested command
- status and resume show the same compact bridge lines
- behavior stays unchanged when no bridge exists

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add continuation_enforcement.py continuation_hooks.py omh_status.py omh_resume.py tests/test_omh_continuation_enforcement_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py
git commit -m "feat: surface detached worker result bridge"
```

### Task 3: Add `omh-exec accept` to adopt the bridged result explicitly

**Files:**
- Modify: `omh_exec.py`
- Test: `tests/test_omh_exec_driver_plugin.py`
- Modify: `README.md`
- Modify: `docs/plans/2026-04-20-omh-detached-worker-result-bridge.md`

- [ ] **Step 1: Write the failing tests**

Add tests proving `omh-exec accept` adopts the recommended bridged outcome.

```python
def test_handle_omh_exec_command_accepts_ready_detached_worker_result_bridge_as_complete():
    result = module.handle_omh_exec_command('accept', workspace=workspace)
    assert 'Outcome: completed' in result
```

```python
def test_handle_omh_exec_command_accepts_failed_detached_worker_result_bridge_as_blocked():
    result = module.handle_omh_exec_command('accept', workspace=workspace)
    assert 'Outcome: blocked' in result
```

```python
def test_handle_omh_exec_command_guides_toward_accept_when_worker_result_bridge_is_ready():
    result = module.handle_omh_exec_command('', workspace=workspace)
    assert 'omh-exec accept' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_exec_driver_plugin.py
```

Expected: FAIL because `accept` is not implemented yet.

- [ ] **Step 3: Write minimal implementation**

Extend the exec driver so that:
- `accept` is a valid exec action
- if a ready worker result bridge exists, `accept` maps to the recommended `complete` or `block` transition with the bridged summary
- empty exec guidance in this state points users at `omh-exec accept`
- non-bridge behavior remains unchanged

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_exec_driver_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_exec.py README.md docs/plans/2026-04-20-omh-detached-worker-result-bridge.md tests/test_omh_exec_driver_plugin.py
git commit -m "feat: allow omh exec to accept detached worker results"
```
