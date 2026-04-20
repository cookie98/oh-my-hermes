# OMH Research Lane Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current OMH research lane from a mostly placeholder queue into a concrete Hermes-native specialist fanout that prepares research work for `explore`, `librarian`, and `oracle` style lanes.

**Architecture:** Add a small `research_lane.py` helper that builds deterministic specialist prompts from the original ULW request. Keep OMH plugin behavior simple: when a context object is available, queue multiple specialist prompts into the current conversation; otherwise, render a structured research-lane handoff summary. Do not add background execution or delegate-task calls from plugin code in this slice.

**Tech Stack:** Python 3, Hermes plugin command surfaces, pytest.

---

## File structure

### Create
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/research_lane.py`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/tests/test_omh_research_lane_plugin.py`

### Modify
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/omh_ulw.py`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/tests/test_omh_ulw_routing_plugin.py`
- `/Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/README.md`

## Scope

Implement these behaviors only:
1. Build deterministic specialist prompts for `explore`, `librarian`, and `oracle` roles from a research/investigation/evaluation request.
2. When `ctx.inject_message` exists, queue one message per specialist instead of one generic self-echo.
3. Return a structured confirmation mentioning the queued lanes.
4. When no `ctx` exists, return a structured non-mutating research summary that names the specialist lanes that would run.

Do not implement background workers, delegate-task execution, or research result aggregation in this slice.

## Tasks

### Task 1: Add research lane helper + focused tests
- Create helper with:
  - `build_research_lane_payload(request, workspace=None)`
  - `build_specialist_messages(request)`
  - `render_research_lane_text(payload)`
- Messages should be explicit and lane-specific:
  - `omh-ulw explore <request>`
  - `omh-ulw librarian <request>`
  - `omh-ulw oracle <request>`
- Add focused tests for payload shape and specialist messages.

### Task 2: Wire `omh_ulw.py` to use the helper
- Replace the single generic `ctx.inject_message(f'omh-ulw {args}')` behavior.
- Queue 3 specialist messages when `ctx` is available.
- Return a confirmation that includes the lane names.
- Add/adjust routing tests accordingly.

### Task 3: Refresh docs + verify
- Update README so research lane status is described accurately.
- Run focused tests, then broad `pytest -q` from the `tests/` directory.

## Verification target

At minimum, fresh verification should include:
```bash
cd /Users/onepredict/.config/superpowers/worktrees/oh-my-hermes/omh-exec-worker-orchestration/tests && pytest -q
```
