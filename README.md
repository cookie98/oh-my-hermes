# oh-my-hermes

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

- `pre_llm_call` hook injects OMH ultrawork context
- `/omh-ulw` slash command queues the same mode into the conversation
- `intent_gate.py` classifies user intent
- `route_resolver.py` maps intent + workspace state to OMH internal routes
- `atlas_state.py` inspects `.omh/state/atlas-state.json` and `.omh/plans/`
- plugin skill registration for `oh-my-hermes:sisyphus-orchestrator`

## Still missing

- true OMH-native `omh-plan`, `omh-start-work`, `omh-resume`, `omh-status` command implementations
- session-idle continuation hooks comparable to Atlas backpressure
- notepad/handoff helpers
- richer route-aware delegation behavior
