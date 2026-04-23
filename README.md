# oh-my-hermes

[![pytest](https://github.com/cookie98/oh-my-hermes/actions/workflows/pytest.yml/badge.svg?branch=main)](https://github.com/cookie98/oh-my-hermes/actions/workflows/pytest.yml)

Hermes-native orchestration layer inspired by oh-my-openagent / OMO.

## Current direction

This plugin is no longer just a keyword injector.

The primary frontdoor is:
- `omh-ulw <intent...>`
- conversational aliases: `ultrawork`, `ulw`

The goal is to make Hermes feel OMO-like at the behavior layer:
- low-ceremony entry
- intent-first routing
- planning/execution separation
- persistent execution state
- continuation pressure
- evidence-first verification

## Hermes-first planning

Planning does **not** hard-depend on Claude Code.

Current preference:
- primary: Hermes-native routing and planning behavior
- optional: Claude Code / OMC as a planning backend when explicitly useful

That means if the external Claude planning stage is flaky or unavailable, OMH should still behave coherently.

## Current implementation

- `pre_llm_call` injects OMH ultrawork context on explicit triggers, can inject a safe continuation reminder for resumable OMH state on greetings / explicit continuation cues, and now also fires idle-time continuation pressure on unrelated first-turn re-entry once the configured idle threshold is crossed
- `/omh-ulw` slash command queues the same mode into the conversation
- user-facing command surface now exists for:
  - `omh-plan`
  - `omh-start-work`
  - `omh-resume`
  - `omh-status`
  - `omh-exec`
  - `omh-verify`
  - `omh-fix`
  - `omh-complete`
- `intent_gate.py` classifies user intent
- `route_resolver.py` maps intent + workspace state to OMH internal routes, including the fallback research lane
- `research_lane.py` fans out research requests into deterministic explore/librarian/oracle specialist prompts
- `atlas_state.py` inspects `.omh/state/atlas-state.json`, `.omh/plans/`, and execution artifacts
- v1 worker orchestration now exists: worker dispatch state, worker handoff files, worker result recording, file-backed reattachment summaries across status/resume/continuation, detached worker supervision metadata, runtime-assisted detached session auto-refresh on status/resume/continuation entry via dedicated callbacks and common process-namespace fallbacks, detached worker result bridging with `omh-exec accept`, practical continuation enforcement with exact next-action hints, basic idle-time continuation pressure with persisted nudge cooldowns, and nudge-count-based idle escalation into stricter continuation enforcement are all implemented
- plugin skill registration for `oh-my-hermes:sisyphus-orchestrator`
- intent-aware plan generation with category-specific templates (implementation vs research vs fix)
- plan-to-task bridge now extracts acceptance criteria, file targets, and test targets from plan markdown
- `omh-exec` task-aware router classifies each active task as implement/research/verify before dispatch
- cross-surface state consistency guard detects drift between task_sessions and worker_sessions
- `omh-exec` now supports wave-aware scheduling for lineage-shaped task graphs, including topological wave computation, bounded parallel wave execution, and fail-fast blocking when a wave fails
- execution workers can bridge into external CLIs (`codex`, `claude`, `opencode`) with per-task prompts, persisted stdout/stderr logs, and deterministic manual fallback when no bridge runtime exists
- verification now records task-level acceptance evidence, retry counts, and escalation requirements so `omh-verify` can distinguish verified / partial / failed outcomes for each completed task
- status surfaces expose task artifact paths and dependency-tree lineage so operator re-entry shows outputs, wave shape, and completion context without opening the raw state JSON
- `omh-complete` generates a final completion bundle with archived state, copied task artifacts, lineage summary, and a completion-facing next action once the execution reaches a fully verified terminal state

## Still missing

- deeper background session reattachment / polling coverage beyond runtime-assisted detached session refresh
- more automated polling across sessions and runtimes beyond the current dedicated-callback and common process-namespace fallback coverage
- broader end-to-end policy coverage beyond the current file-backed orchestration flow, including continuation loops stronger than the current idle-escalation frontdoor enforcement
