# OMH Continuation Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe Hermes-native continuation hook so OMH can re-surface resumable execution context on new sessions or continuation-like prompts without requiring the user to remember `omh-ulw` every time.

**Architecture:** Keep the slice narrow and safe. Add a small `continuation_hooks.py` helper that decides when continuation context should be injected and renders a compact continuation reminder from `atlas_state`. Then extend plugin `pre_llm_call` so it can inject OMH context not only on trigger keywords, but also when a resumable OMH state exists and either (a) the message is a clear continuation prompt or (b) it is the first turn of a session and a resumable state is active. Do not add background jobs or timers in this phase.

**Tech Stack:** Python 3, Hermes plugin hooks, file-backed OMH state, pytest.

---

## File structure

### Create
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/continuation_hooks.py`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/tests/test_omh_continuation_hooks_plugin.py`

### Modify
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/__init__.py`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/README.md`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/tests/test_omh_ulw_routing_plugin.py` only if integration coverage is genuinely needed

## Scope

Implement only these behaviors:
1. Detect a small set of explicit continuation cues such as `continue`, `resume`, `go on`, `keep going`, `이어`, `계속`, `진행`, `계속하자`, `이어가자`, `다음 작업`, `다음 구현 작업`.
2. Build a compact continuation context from active resumable OMH state including plan, stage, wave, and current task slug.
3. Extend `pre_llm_call` so OMH context is injected when:
   - normal trigger keywords match, **or**
   - resumable OMH state exists and the current message is a continuation cue, **or**
   - resumable OMH state exists and this is the first user turn of the session.
4. Keep the behavior non-mutating: do not automatically dispatch workers or modify OMH state from the continuation hook.

Out of scope:
- timers or background polling
- auto-resume side effects without a user message
- queueing cron jobs or detached sessions

## Tasks

### Task 1: Add continuation hook helper + tests
- Create `continuation_hooks.py` with:
  - `is_continuation_prompt(user_message: str) -> bool`
  - `build_continuation_context(snapshot) -> str`
- Test English + Korean continuation phrases and non-matches.
- Test rendered continuation context includes plan/stage/wave/current task when resumable state exists.

### Task 2: Extend plugin pre-LLM activation logic
- Update `__init__.py` so `_pre_llm_call` injects context when resumable OMH state exists and either:
  - `is_first_turn == true`, or
  - `is_continuation_prompt(user_message)` is true.
- Keep existing trigger-keyword behavior unchanged.
- Add focused tests for `_pre_llm_call` behavior with a fake workspace + resumable atlas state.

### Task 3: Refresh README + full verification
- Update README “Still missing” text so it no longer treats continuation hooks as entirely absent once this slice lands.
- Run focused tests, then full `pytest -q` from the `tests/` directory.

## Verification target

At minimum, fresh verification should include:
```bash
cd /Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-continuation-hooks/tests && pytest -q
```
