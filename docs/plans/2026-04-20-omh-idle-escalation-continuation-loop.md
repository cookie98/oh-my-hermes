# OMH Idle Escalation Continuation Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn repeated ignored idle continuation nudges into a stronger multi-session continuation loop by escalating resumable OMH execution from soft continuation guidance into strict frontdoor enforcement after a configurable number of ignored nudges.

**Architecture:** Reuse the already-persisted `.omh/state/atlas-state.json` idle bookkeeping (`last_nudged_at`, `nudge_count`) instead of inventing a new subsystem. Extend idle continuation pressure with escalation metadata, let continuation enforcement upgrade soft resumable execution to strict when the escalation threshold is reached, and surface that escalation state across continuation/status/resume so route resolution and user-facing reminders stay consistent.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Add idle escalation metadata to continuation pressure and enforcement

**Files:**
- Modify: `continuation_enforcement.py`
- Test: `tests/test_omh_continuation_enforcement_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving repeated idle nudges escalate soft resumable execution into strict continuation enforcement.

```python
def test_build_idle_continuation_pressure_marks_escalation_active_after_repeated_nudges():
    pressure = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T04:00:00Z')
    assert pressure.escalation_active is True
    assert pressure.nudge_count == 2
```

```python
def test_build_continuation_enforcement_escalates_soft_exec_state_after_idle_nudge_threshold():
    decision = enforcement_module.build_continuation_enforcement(snapshot)
    assert decision.strict is True
    assert 'ignored idle continuation nudges' in decision.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: FAIL because idle escalation metadata and strict-upgrade behavior do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Extend idle continuation pressure to expose:
- `nudge_count`
- `escalation_threshold`
- `escalation_active`

Then let `build_continuation_enforcement(snapshot)` upgrade otherwise-soft resumable exec state to strict once idle escalation is active.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add continuation_enforcement.py tests/test_omh_continuation_enforcement_plugin.py
git commit -m "feat: add idle continuation escalation decisions"
```

### Task 2: Surface idle escalation and enforce it at the frontdoor

**Files:**
- Modify: `continuation_hooks.py`
- Modify: `omh_status.py`
- Modify: `omh_resume.py`
- Modify: `route_resolver.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`
- Test: `tests/test_omh_status_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`
- Test: `tests/test_omh_ulw_exec_integration_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving escalation is visible and changes routing behavior.

```python
def test_build_continuation_context_mentions_idle_escalation_when_active():
    context = module.build_continuation_context(snapshot, now='2026-04-20T04:00:00Z')
    assert 'Idle Escalation: active' in context
```

```python
def test_render_status_text_mentions_idle_escalation_when_active():
    text = status_module.render_status_text(payload)
    assert 'Idle Escalation: active' in text
```

```python
def test_resolve_route_redirects_research_request_to_omh_exec_after_idle_escalation():
    decision = route_module.resolve_route(intent_module.classify_intent('research auth options'), workspace=workspace)
    assert decision.route == 'omh-exec'
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_ulw_exec_integration_plugin.py
```

Expected: FAIL because idle escalation is not yet surfaced or enforced.

- [ ] **Step 3: Write minimal implementation**

Update continuation/status/resume text to expose escalation lines, and rely on the strengthened continuation enforcement so route resolution frontdoor strict-gates escalated execution debt.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_ulw_exec_integration_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add continuation_hooks.py omh_status.py omh_resume.py route_resolver.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_status_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_ulw_exec_integration_plugin.py
git commit -m "feat: enforce idle continuation escalation on reentry"
```

### Task 3: Refresh docs and run full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-04-20-omh-idle-escalation-continuation-loop.md`

- [ ] **Step 1: Update docs**

Document that repeated ignored idle nudges now escalate resumable OMH work into stricter continuation enforcement across sessions.

- [ ] **Step 2: Run full verification**

Run:

```bash
cd tests && pytest -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plans/2026-04-20-omh-idle-escalation-continuation-loop.md
git commit -m "docs: add idle escalation continuation loop note"
```