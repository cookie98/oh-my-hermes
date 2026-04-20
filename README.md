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

- `pre_llm_call` injects OMH ultrawork context on explicit triggers and can inject a safe continuation reminder for resumable OMH state on greetings / explicit continuation cues
- `/omh-ulw` slash command queues the same mode into the conversation
- user-facing command surface now exists for:
  - `omh-plan`
  - `omh-start-work`
  - `omh-resume`
  - `omh-status`
  - `omh-exec`
  - `omh-verify`
  - `omh-fix`
- `intent_gate.py` classifies user intent
- `route_resolver.py` maps intent + workspace state to OMH internal routes, including the fallback research lane
- `research_lane.py` fans out research requests into deterministic explore/librarian/oracle specialist prompts
- `atlas_state.py` inspects `.omh/state/atlas-state.json`, `.omh/plans/`, and execution artifacts
- v1 worker orchestration now exists: worker dispatch state, worker handoff files, worker result recording, file-backed reattachment summaries across status/resume/continuation, detached worker supervision metadata, and runtime-assisted detached session auto-refresh on status/resume/continuation entry are all implemented
- plugin skill registration for `oh-my-hermes:sisyphus-orchestrator`

## Still missing

- deeper background session reattachment / polling coverage beyond runtime-assisted detached session refresh
- more automated polling across sessions and runtimes without explicit callback plumbing
- broader end-to-end policy coverage beyond the current file-backed orchestration flow
