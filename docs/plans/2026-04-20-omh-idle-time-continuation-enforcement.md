# OMH Idle-Time Continuation Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OMH actively pull the user back into unfinished work after real idle time by deriving a time-aware continuation-pressure decision, injecting it on otherwise unrelated re-entry turns, and persisting lightweight nudge cadence in atlas state so the reminder behaves predictably instead of spamming.

**Architecture:** Extend continuation enforcement with a time-aware idle decision derived from `updated_at`, current strict/soft unresolved state, and persisted idle-nudge bookkeeping in `.omh/state/atlas-state.json`. Use that decision in `pre_llm_call` so unrelated first-turn re-entry can still get continuation context once the idle threshold is crossed, while a cooldown prevents repeated nags. Surface the idle pressure state in continuation/status/resume text so the policy is inspectable.

**Tech Stack:** Python 3.11, pytest, file-backed `.omh/state/atlas-state.json` state machine.

---

### Task 1: Add time-aware idle continuation decision logic

**Files:**
- Modify: `continuation_enforcement.py`
- Test: `tests/test_omh_continuation_enforcement_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove OMH can tell when idle-time continuation pressure is due.

```python
def test_build_idle_continuation_pressure_marks_soft_resumable_state_due_after_threshold():
    decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T02:00:00Z')
    assert decision.active is True
    assert decision.due is True
    assert decision.level == 'soft'
    assert decision.idle_minutes == 120
```

```python
def test_build_idle_continuation_pressure_uses_shorter_threshold_for_strict_state():
    decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T00:20:00Z')
    assert decision.active is True
    assert decision.due is True
    assert decision.level == 'strict'
```

```python
def test_build_idle_continuation_pressure_respects_recent_nudge_cooldown():
    decision = enforcement_module.build_idle_continuation_pressure(snapshot, now='2026-04-20T02:00:00Z')
    assert decision.due is False
    assert decision.cooldown_active is True
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: FAIL because time-aware idle continuation pressure does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add a helper that:
- parses `updated_at` / `started_at`
- measures idle age
- chooses strict vs soft idle threshold from config defaults
- reads persisted nudge bookkeeping from atlas state
- reports whether an idle reminder is currently due
- returns compact inspectable fields (`due`, `level`, `idle_minutes`, `threshold_minutes`, `cooldown_active`, `reason`)

Keep current route-enforcement behavior unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add continuation_enforcement.py tests/test_omh_continuation_enforcement_plugin.py
git commit -m "feat: add idle continuation pressure decisions"
```

### Task 2: Trigger idle continuation reminders from pre-LLM re-entry and persist cooldown bookkeeping

**Files:**
- Modify: `__init__.py`
- Modify: `continuation_hooks.py`
- Modify: `omh_resume.py`
- Test: `tests/test_omh_continuation_hooks_plugin.py`
- Test: `tests/test_omh_resume_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove unrelated re-entry turns get continuation pressure only when the idle threshold is crossed and not while cooldown is active.

```python
def test_pre_llm_call_injects_continuation_context_for_unrelated_first_turn_after_idle_threshold():
    result = hook(user_message='what restaurants are nearby?', platform='cli', is_first_turn=True)
    assert result is not None
    assert 'Idle Continuation: due' in result['context']
```

```python
def test_pre_llm_call_persists_idle_nudge_timestamp_when_idle_pressure_fires():
    hook(user_message='what restaurants are nearby?', platform='cli', is_first_turn=True)
    raw_state = json.loads(state_path.read_text(encoding='utf-8'))
    assert raw_state['continuation_enforcement']['idle']['last_nudged_at'] == '2026-04-20T02:00:00Z'
```

```python
def test_pre_llm_call_skips_unrelated_idle_nudge_inside_cooldown_window():
    result = hook(user_message='what restaurants are nearby?', platform='cli', is_first_turn=True)
    assert result is None
```

```python
def test_render_resume_text_mentions_idle_continuation_status_when_due():
    assert 'Idle Continuation: due' in text
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_resume_plugin.py
```

Expected: FAIL because idle-time unrelated re-entry is not enforced yet.

- [ ] **Step 3: Write minimal implementation**

Implement the hook behavior:
- add config defaults for strict/soft idle thresholds and cooldown
- allow `pre_llm_call` to inject continuation context on unrelated first turns when idle pressure is due
- persist `last_nudged_at` (and minimal count metadata if useful) back into atlas state
- include a compact idle-pressure section in continuation/resume text

Do not inject on every unrelated message; only the idle-due path should override the current “None” behavior.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_omh_continuation_hooks_plugin.py tests/test_omh_resume_plugin.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add __init__.py continuation_hooks.py omh_resume.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_resume_plugin.py
git commit -m "feat: enforce continuation after idle re-entry"
```

### Task 3: Surface idle continuation pressure in status and docs

**Files:**
- Modify: `omh_status.py`
- Modify: `README.md`
- Modify: `config.yaml`
- Create: `docs/plans/2026-04-20-omh-idle-time-continuation-enforcement.md`
- Test: `tests/test_omh_status_plugin.py`

- [ ] **Step 1: Write the failing status test**

```python
def test_render_status_text_mentions_idle_continuation_when_due():
    assert 'Idle Continuation: due' in text
    assert 'Idle Age: 120m' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest -q tests/test_omh_status_plugin.py
```

Expected: FAIL because status does not yet expose idle continuation pressure.

- [ ] **Step 3: Write minimal implementation**

Expose idle continuation pressure in status with compact lines such as:
- `Idle Continuation: due|waiting|cooldown`
- `Idle Age: Xm`
- `Idle Threshold: Ym`

Update README/config comments to document the new behavior and knobs.

- [ ] **Step 4: Run targeted and full verification**

Run:

```bash
pytest -q tests/test_omh_continuation_enforcement_plugin.py tests/test_omh_continuation_hooks_plugin.py tests/test_omh_resume_plugin.py tests/test_omh_status_plugin.py
cd tests && pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omh_status.py README.md config.yaml docs/plans/2026-04-20-omh-idle-time-continuation-enforcement.md tests/test_omh_status_plugin.py
git commit -m "docs: document idle continuation enforcement"
```