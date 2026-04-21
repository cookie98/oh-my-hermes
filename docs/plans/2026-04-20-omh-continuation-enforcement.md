# OMH Practical Continuation Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OMH practically harder to abandon mid-execution by deriving an exact next action from unresolved state, surfacing it everywhere, and redirecting the low-ceremony frontdoor back into the current execution instead of starting unrelated new work.

**Architecture:** Add a small continuation-enforcement helper that inspects active OMH state and returns a strict/soft enforcement decision with a concrete next action. Wire that decision into routing, status/resume/continuation surfaces, and ULW context. Strict unresolved stages (verify/fix/awaiting-worker-result/detached-running) should gate the frontdoor away from unrelated new work.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Add continuation-enforcement decision helper

**Files:**
- Create: `continuation_enforcement.py`
- Test: `tests/test_omh_continuation_enforcement_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove strict unresolved states produce exact next actions.

```python
def test_build_continuation_enforcement_returns_verify_gate_with_exact_next_action():
    decision = enforcement_module.build_continuation_enforcement(snapshot)
    assert decision.strict is True
    assert decision.route == 'omh-exec'
    assert decision.next_action == 'Run `omh-verify <pass|fail> [summary...]` to resolve the current verify stage before starting unrelated work.'
```

```python
def test_build_continuation_enforcement_returns_status_gate_for_running_detached_worker():
    decision = enforcement_module.build_continuation_enforcement(snapshot)
    assert decision.strict is True
    assert decision.route == 'omh-status'
    assert 'Detached worker session is still running' in decision.next_action
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: FAIL because the helper does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement a helper that derives:
- whether continuation enforcement is active
- whether it is strict
- which route should win (`omh-status` vs `omh-exec`)
- an exact human-readable next action
- a short reason string

Handle at minimum:
- `verify` stage
- `fix` stage
- `awaiting-worker-result`
- detached worker supervision `running`
- ordinary resumable exec stage as a softer continuation reminder

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add continuation_enforcement.py tests/test_omh_continuation_enforcement_plugin.py
git commit -m "feat: add omh continuation enforcement decisions"
```

### Task 2: Surface next-action enforcement in status, resume, continuation, and ULW context

**Files:**
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Modify: `continuation_hooks.py`
- Modify: `omh_ulw.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`
- Test: `tests/test_omh_ulw_routing_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add assertions that the exact next action is visible on read/re-entry surfaces.

```python
def test_render_status_text_mentions_exact_next_action_for_verify_gate():
    assert 'Next Action: Run `omh-verify <pass|fail> [summary...]`' in text
```

```python
def test_render_resume_text_mentions_exact_next_action_for_detached_running_worker():
    assert 'Next Action: Detached worker session is still running.' in result
```

```python
def test_build_continuation_context_mentions_next_action():
    assert 'Next Action:' in context
```

```python
def test_build_ulw_context_mentions_continuation_enforcement_when_active():
    assert 'Continuation Enforcement: strict' in context
    assert 'Next Action:' in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_ulw_routing_plugin.py
```

Expected: FAIL because these surfaces do not yet expose enforcement decisions.

- [ ] **Step 3: Write minimal implementation**

Wire the helper into those surfaces and add compact lines like:
- `Continuation Enforcement: strict|soft`
- `Next Action: ...`

Keep text concise and operational.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_ulw_routing_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_status.py omh_resume.py continuation_hooks.py omh_ulw.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_ulw_routing_plugin.py
git commit -m "feat: surface omh continuation enforcement hints"
```

### Task 3: Gate ULW routing when strict unresolved work exists

**Files:**
- Modify: `route_resolver.py`
- Modify: `omh_ulw.py`
- Test: `tests/test_omh_ulw_exec_integration_plugin.py`
- Test: `tests/test_omh_ulw_routing_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove strict unresolved work blocks unrelated new work through the frontdoor.

```python
def test_resolve_route_redirects_new_implementation_to_omh_exec_during_verify_gate():
    assert decision.route == 'omh-exec'
    assert 'must resolve the current verify stage' in decision.summary
```

```python
def test_resolve_route_redirects_research_request_to_status_while_detached_worker_is_running():
    assert decision.route == 'omh-status'
```

```python
def test_handle_omh_ulw_command_refuses_to_start_new_work_when_strict_gate_is_active():
    assert 'Next Action:' in result
    assert 'omh-verify <pass|fail>' in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_ulw_exec_integration_plugin.py tests/test_omh_ulw_routing_plugin.py
```

Expected: FAIL because strict unresolved state does not yet override unrelated frontdoor routing.

- [ ] **Step 3: Write minimal implementation**

Modify routing so that when strict continuation enforcement is active:
- detached running worker -> route non-status requests to `omh-status`
- verify/fix/awaiting-worker-result -> route non-status requests to `omh-exec`
- route summary must explain that unrelated new work is being deferred until the current execution is resolved

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_ulw_exec_integration_plugin.py tests/test_omh_ulw_routing_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add route_resolver.py omh_ulw.py tests/test_omh_ulw_exec_integration_plugin.py tests/test_omh_ulw_routing_plugin.py
git commit -m "feat: enforce continuation on the omh frontdoor"
```

### Task 4: Update docs and run full verification

**Files:**
- Modify: `README.md`
- Create: `docs/plans/2026-04-20-omh-continuation-enforcement.md`

- [ ] **Step 1: Update docs**

Document that OMH now derives an exact next action from unresolved execution state and that strict unresolved stages redirect the frontdoor back into the current execution instead of starting unrelated new work.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS with the full suite green.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-continuation-enforcement.md
git commit -m "docs: add continuation enforcement plan and readme note"
```