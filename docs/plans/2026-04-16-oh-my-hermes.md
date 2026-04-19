# Oh-My-Hermes Implementation Plan

> For Hermes: use subagent-driven-development only after this scaffold is accepted. For now, keep all work Hermes-native and avoid Hermes core edits.

Goal: Recreate the most valuable UX, philosophy, and execution behavior of oh-my-openagent inside Hermes as closely as practical, using a local plugin package plus supporting skills/config, while avoiding Hermes core modification unless plugin-only limits become genuinely unacceptable.

Architecture: Build a Hermes-native plugin called `oh-my-hermes` under `~/.hermes/plugins/` that uses existing Hermes plugin hooks (`pre_llm_call`, session hooks), plugin-provided skills, Hermes-native subagents, and optional future ACP-backed delegation. The target is not a superficial keyword clone — it is an OMO-like control plane in Hermes: low-ceremony entrypoints, intent-first routing, planning/execution separation, persistent execution state, continuation loops, and aggressive verification.

Tech Stack: Hermes plugin system (`plugin.yaml` + `__init__.py`), Python 3, YAML config, Hermes skills, Hermes subagents, optional future ACP/OpenCode runtime.

---

## Design goals

1. Preserve Hermes core unchanged unless plugin-only limits are proven inadequate in real use.
2. Make Hermes feel OMO-like at the behavior layer, not just the vocabulary layer.
3. Preserve OMO's key philosophy: low-ceremony entrypoints, intent-first routing, planning/execution separation, persistent momentum, and aggressive verification.
4. Keep the first version safe, reversible, and easy to inspect.
5. Prefer config + skills + hooks + Hermes-native subagents over hardcoded behavior.

## OMO behaviors OMH should preserve

From the upstream OMO repo and installed runtime, the behaviors worth copying most aggressively are:

- **Ultralow-ceremony frontdoor** — `ultrawork` / `ulw` means the user expresses intent once and the system takes responsibility from there.
- **Intent-first routing** — do not assume every complex prompt means "implement now"; classify the real request first.
- **Planning/execution split** — Prometheus plans, Atlas executes, specialists support.
- **Persistent execution state** — `.sisyphus/boulder.json` anchors multi-step work across interruptions.
- **Continuation pressure** — work should not silently die when there is still active execution state.
- **Parallel specialist support** — explore, librarian, oracle-style support should be cheap and routine.
- **Read-only planning artifacts** — plans guide execution but workers do not casually mutate them.
- **Verified completion** — completion claims require evidence, not vibes.

OMH should preserve these behaviors even where the exact OpenCode APIs do not exist.

## Non-goals for v0.1

1. No direct port of OpenCode `chat.message`, `chat.params`, or message-transform APIs.
2. No custom Hermes core patching for mutable tool/result transforms.
3. No large autonomous background manager inside Hermes yet.
4. No forced git workflow changes.

## Mapping: oh-my-opencode -> Hermes

| oh-my-opencode concept | Hermes-native equivalent | v0.1 status |
| --- | --- | --- |
| Sisyphus orchestrator | keyword-triggered orchestration context via `pre_llm_call` | implement |
| Specialist agents | plugin skill roles + future `delegate_task` conventions | scaffold |
| Category-based routing | config-driven category map stored in plugin config | scaffold |
| Ultrawork frontdoor | `omh-ulw` command + `ultrawork`/`ulw` conversational alias | implement |
| Hooks around tools/messages | Hermes plugin lifecycle hooks only | implement within current limits |
| Claude Code compatibility layer | not a goal; replace with Hermes-native prompts/skills | defer |
| Background async subagents | optional future ACP/OpenCode execution profile | defer |
| Rich tool mutation | not possible cleanly without Hermes core changes | defer |

## Proposed plugin layout

- Create: `~/.hermes/plugins/oh-my-hermes/plugin.yaml`
- Create: `~/.hermes/plugins/oh-my-hermes/__init__.py`
- Create: `~/.hermes/plugins/oh-my-hermes/config.yaml`
- Create: `~/.hermes/plugins/oh-my-hermes/README.md`
- Create: `~/.hermes/plugins/oh-my-hermes/skills/sisyphus-orchestrator/SKILL.md`

## Behavior of v0.1

Low-ceremony ultrawork entry should exist in two equivalent surfaces:

- explicit command surface: `omh-ulw <intent...>`
- conversational trigger surface: user message contains configured trigger keywords such as `ultrawork` or `ulw`

Both should activate the same OMH orchestration mode rather than two separate behaviors.

That mode should:

- switch the assistant into an orchestration mindset
- classify intent before choosing a route
- prefer planning before implementation when implementation is actually needed
- prefer specialist decomposition for complex work
- require explicit verification before saying work is done
- preserve the user's original language
- mention optional ACP/OpenCode delegation only as an implementation backend, not as a hard dependency
- keep working until the routed objective is complete instead of stopping at a hand-wavy midpoint

## Config surface for v0.1

- `enabled`
- `enabled_platforms`
- `trigger_keywords`
- `inject_on_first_turn_only`
- `max_instruction_chars`
- `agents` (named role metadata)
- `categories` (category -> routing guidance)
- `delegate_runtime` (document future OpenCode ACP integration)

## Missing execution-state concept to add before command-surface finalization

OMO has a concrete execution bootstrap/state artifact: `.sisyphus/boulder.json`. It is not just a cache file — it is the execution contract for `/start-work`.

Before OMH command definitions are finalized, OMH needs its own documented equivalent.

### What OMO `boulder.json` is doing

From the OMO runtime, `boulder.json` is used to:
- track the currently active plan
- decide whether `/start-work` should resume or start fresh
- remember participating session IDs and origins
- store the active worktree path
- anchor execution state before delegation begins

Observed OMO fields include:
- `active_plan`
- `started_at`
- `session_ids`
- `session_origins`
- `plan_name`
- `worktree_path`

### What OMH should document

OMH needs a Hermes-native execution state artifact that plays the same role before `omh-start-work`, `omh-resume`, and `omh-status` are fully specified.

For now, treat this as a required design item, not an implementation detail to hand-wave away.

### Recommended OMH equivalent (working proposal)

Use a project-local OMH state file, likely under a dedicated OMH workspace directory, for example:
- `.omh/state/atlas-state.json`

Candidate fields:
- `active_plan`: canonical OMH plan path
- `plan_name`: stable plan slug/name
- `started_at`: ISO timestamp
- `session_ids`: Hermes session IDs involved in execution
- `session_origins`: whether sessions are direct, resumed, or appended
- `worktree_path`: active git worktree if used
- `current_stage`: e.g. `exec`, `verify`, `fix`
- `current_wave`: current execution wave number
- `status`: `active`, `blocked`, `complete`, `cancelled`, `failed`
- `last_handoff`: latest handoff artifact path

### Required behavior tied to this state file

Any OMH execution design should assume the following:
- `omh-start-work` writes or updates execution state BEFORE dispatching workers
- `omh-resume` reads this state to continue the last incomplete task/wave
- `omh-status` reads this state for progress reporting
- workers must treat the plan as read-only; only the Atlas/orchestrator updates execution state
- worktree-aware execution must be reflected in the state file, not inferred ad hoc

### Design implication

This means OMH command design should not be finalized as only a command list. It also needs:
- a canonical execution state file
- explicit lifecycle rules for create/update/clear
- documented ownership boundaries between orchestrator and workers

## `omh-start-work` detailed design (draft)

### Role

`omh-start-work` is the Atlas bootstrap command.

It does **not** create plans and it does **not** directly implement code. Its job is to turn an already-approved canonical OMH plan into an active execution session.

### Command shape

```bash
omh-start-work [plan-name] [--worktree <absolute-path>]
```

- `plan-name` is optional and may be a full or partial stable plan slug/name.
- `--worktree <absolute-path>` is optional and selects the execution worktree.

### Strict precondition

`omh-start-work` requires a canonical OMH plan to exist first.

If no matching canonical plan is available, `omh-start-work` MUST NOT silently create one, MUST NOT fall back into planning mode automatically, and MUST NOT start implementation blindly.

Instead it should fail clearly and direct the user to `omh-plan`.

Recommended failure message shape:

```text
No canonical OMH plan found for this request.
Run `omh-plan` first, then retry `omh-start-work`.
```

### Purpose

`omh-start-work` is responsible for:
- selecting the canonical OMH plan to execute
- deciding whether to resume an existing execution or start a fresh one
- creating/updating `.omh/state/atlas-state.json` before worker dispatch
- resolving worktree context
- reading the **full** canonical plan
- decomposing the plan into execution-ready subtasks
- entering the Atlas execution flow

### Explicit non-goals

`omh-start-work` must not:
- generate a plan
- modify the canonical plan contents during bootstrap
- compute final verification outcomes by itself
- act like a worker executor instead of an orchestrator

### Plan selection rules

When `omh-start-work` runs, it should resolve the execution target in this order:

1. **Explicit `plan-name` provided**
   - Match against canonical OMH plans.
   - If one match exists, use it.
   - If multiple matches exist, ask the user to choose.
   - If no match exists, fail and direct the user to `omh-plan`.

2. **No `plan-name`, but active incomplete execution state exists**
   - Resume the plan referenced by `.omh/state/atlas-state.json`.

3. **No `plan-name`, no active state, exactly one canonical plan exists**
   - Auto-select the single plan.
   - This is the chosen OMH default because ambiguity is effectively zero and the UX is better than forcing redundant plan-name input.

4. **No `plan-name`, no active state, multiple canonical plans exist**
   - Ask the user to choose.

5. **No `plan-name`, no canonical plan exists**
   - Fail and direct the user to `omh-plan`.

### Resume rules

`omh-start-work` should resume instead of creating a new execution when all of the following are true:
- `.omh/state/atlas-state.json` exists
- `status` is `active` or `blocked`
- the referenced `active_plan` is still incomplete
- the selected plan matches the state's `active_plan`

On resume:
- append the current Hermes session ID to `session_ids` if missing
- set `session_origins[session_id] = "appended"`
- preserve `current_stage`, `current_wave`, `task_sessions`, and `last_handoff`
- update `updated_at`

### Fresh-start rules

`omh-start-work` should create a new execution state when:
- no atlas state exists
- the existing state points to a completed plan
- the user explicitly selects a different plan than the currently active one

Minimum initial state:

```json
{
  "version": 1,
  "active_plan": ".omh/plans/<plan>.md",
  "plan_name": "<plan>",
  "started_at": "ISO_TIMESTAMP",
  "updated_at": "ISO_TIMESTAMP",
  "status": "active",
  "current_stage": "bootstrap",
  "current_wave": null,
  "session_ids": ["<session_id>"],
  "session_origins": {"<session_id>": "direct"},
  "worktree_path": null,
  "task_sessions": {},
  "last_handoff": null,
  "notepad_dir": ".omh/notepads/<plan>/"
}
```

### Worktree rules

- If `--worktree` is provided, it must be treated as the explicit execution worktree target.
- `worktree_path` must be written into `atlas-state.json` before worker dispatch begins.
- If no worktree is used, `worktree_path` should be `null`.
- Execution location must come from state, not from ad hoc inference once bootstrapped.

### Bootstrap sequence

`omh-start-work` should follow this order strictly:

1. Resolve plan target
2. Resolve resume vs fresh-start
3. Resolve worktree context
4. Write/update `atlas-state.json`
5. Read the **full** canonical plan
6. Derive execution-ready task breakdown
7. Initialize task/session tracking
8. Transition state from `bootstrap` to `exec`
9. Begin Atlas execution orchestration

### Ownership rules

During and after `omh-start-work` bootstrap:
- the Atlas/orchestrator is the only writer of `atlas-state.json`
- the canonical plan is read-only during execution bootstrap
- workers may append to OMH notepads but may not mutate execution state

### User-facing output

For a fresh start:

```text
Starting OMH work session

Plan: <plan-name>
Session ID: <session-id>
Stage: bootstrap
Worktree: <worktree-path or current project>

Reading canonical plan and preparing execution...
```

For a resume:

```text
Resuming OMH work session

Active Plan: <plan-name>
Progress: <completed>/<total>
Stage: <current-stage>
Wave: <current-wave>
Sessions: <count>
Worktree: <worktree-path>

Continuing from the last incomplete execution state...
```

## `omh-resume` detailed design (draft)

### Role

`omh-resume` is the dedicated continuation entrypoint for OMH execution.

It does not choose a new plan, does not create a new execution by default, and does not replace `omh-start-work`. Its responsibility is to re-attach to an existing resumable Atlas execution state and continue from the last incomplete point.

### Command shape

```bash
omh-resume
```

Initial OMH design keeps this command argument-free on purpose. It should resume the currently active OMH execution for the current project workspace.

Future extensions can add explicit plan/session targeting if needed, but v0 should stay narrow.

### Strict precondition

`omh-resume` requires a resumable OMH execution state to already exist.

If `.omh/state/atlas-state.json` is missing, `omh-resume` must fail clearly and direct the user to `omh-start-work`.

If the state exists but is not resumable, `omh-resume` must fail clearly and explain why.

Recommended failure message shapes:

```text
No resumable OMH execution state was found.
Run `omh-start-work` to begin work from a canonical OMH plan.
```

```text
The last OMH execution is not resumable (status: complete).
Use `omh-start-work` to begin a new execution session.
```

### Resumable state rules

A state is resumable only when all of the following are true:
- `.omh/state/atlas-state.json` exists
- `status` is `active` or `blocked`
- `active_plan` still exists
- `active_plan` progress is not complete

A state is **not** resumable when:
- the file is missing
- `status` is `complete`
- the referenced plan is already complete
- the referenced plan path is missing or invalid

For v0, treat `failed` and `cancelled` as non-resumable terminal states. A later design can add an explicit reopen/recover flow if needed.

### Purpose

`omh-resume` is responsible for:
- reading `.omh/state/atlas-state.json`
- validating that the execution is resumable
- restoring the execution context from state
- appending the current Hermes session to execution state
- restoring the current stage / wave / handoff / worktree context
- continuing the Atlas loop from the last incomplete point

### Explicit non-goals

`omh-resume` must not:
- create a fresh execution when no resumable state exists
- silently pick a different plan than the one in state
- rewrite the canonical plan
- recompute execution strategy from scratch unless required for repair
- act as a substitute for `omh-start-work`

### State update behavior

On successful resume:
- if the current Hermes session ID is not already present, append it to `session_ids`
- set `session_origins[session_id] = "appended"`
- preserve `active_plan`, `plan_name`, `worktree_path`, `current_stage`, `current_wave`, `task_sessions`, and `last_handoff`
- update `updated_at`

`started_at` must remain unchanged on resume.

### Recovery sequence

`omh-resume` should follow this order strictly:

1. Read `.omh/state/atlas-state.json`
2. Validate resumable status and referenced plan
3. Compute current plan progress from `active_plan`
4. Re-attach current session to `session_ids` / `session_origins`
5. Restore worktree context from `worktree_path`
6. Load the latest handoff artifact if `last_handoff` is set
7. Restore task/session tracking from `task_sessions`
8. Continue from the saved `current_stage` and `current_wave`

### Stage-specific continuation rules

- If `current_stage = "exec"`, continue execution from the current incomplete wave/task set.
- If `current_stage = "verify"`, resume verification first before returning to execution.
- If `current_stage = "fix"`, resume the remediation path, then re-enter verification.
- If `current_stage = "bootstrap"`, treat this as an interrupted bootstrap and complete the pending bootstrap steps before execution begins.

### Worktree rules

- `omh-resume` must trust `worktree_path` from state as the authoritative execution location.
- It must not guess a new worktree if one is already recorded.
- If `worktree_path` is recorded but missing on disk, `omh-resume` should fail clearly and report that the execution workspace is broken.

Recommended failure shape:

```text
OMH execution state exists, but the recorded worktree is missing.
Inspect `.omh/state/atlas-state.json` and either restore the worktree or start a new session with `omh-start-work`.
```

### User-facing output

For a normal successful resume:

```text
Resuming OMH work session

Active Plan: <plan-name>
Progress: <completed>/<total>
Stage: <current-stage>
Wave: <current-wave>
Sessions: <count>
Worktree: <worktree-path or current project>

Continuing from the last incomplete execution state...
```

For a blocked-state resume:

```text
Resuming blocked OMH work session

Active Plan: <plan-name>
Stage: blocked
Last Handoff: <handoff-path>
Worktree: <worktree-path>

Re-entering the Atlas flow from the blocked state...
```

## `omh-status` detailed design (draft)

### OMO reference point

From the current OMO/OpenAgent runtime, the effective status model is already visible even without a dedicated user-facing `boulder` command:

- `.sisyphus/boulder.json` is the authoritative execution state artifact
- plan progress is derived live from the referenced plan file rather than trusted as a cached counter
- continuation logic checks whether the tracked plan is incomplete and whether the tracked sessions still belong to the active execution lineage
- the runtime treats missing or malformed state as a real execution-state problem, not as something to hand-wave away

`omh-status` should turn those implicit runtime checks into an explicit Hermes-native read-only inspection command.

### Role

`omh-status` is the dedicated execution inspection entrypoint for OMH.

It reports the current execution posture for the current project workspace by reading `.omh/state/atlas-state.json` and the artifacts referenced by it.

It does **not** resume work, does **not** start work, and does **not** repair state automatically.

### Command shape

```bash
omh-status [--json]
```

Initial OMH design should keep the command narrow, but unlike `omh-resume`, `omh-status` benefits immediately from one machine-readable surface.

For v0:
- default mode is human-readable summary output
- `--json` returns machine-readable status for scripts, hooks, and automation
- both modes inspect the current project workspace only

Future extensions can add `--verbose` or explicit plan/session targeting, but v0 should stop at default text + `--json`.

### Safety and precondition model

Unlike `omh-start-work` and `omh-resume`, `omh-status` should always be safe to run.

It should not require a resumable execution state in order to return useful information.

That means:
- if no OMH state exists, it should report that clearly
- if OMH state exists and is healthy, it should summarize it
- if OMH state exists but is broken or inconsistent, it should report that explicitly

### Purpose

`omh-status` is responsible for:
- reading `.omh/state/atlas-state.json` if present
- normalizing optional state collections such as `session_ids`, `session_origins`, and `task_sessions`
- validating referenced execution artifacts such as `active_plan`, `worktree_path`, and `last_handoff`
- deriving live progress from `active_plan`
- computing a user-facing execution posture summary
- reporting whether the current execution is resumable
- surfacing integrity warnings without mutating execution state

### Explicit non-goals

`omh-status` must not:
- create a new execution state
- resume or continue execution
- silently repair broken state
- rewrite the canonical plan
- update task progress on behalf of workers
- mutate `atlas-state.json` just because it noticed a mismatch

### State loading rules

`omh-status` should load `.omh/state/atlas-state.json` using tolerant read rules inspired by OMO's `boulder.json` handling:

- if the file is missing, treat that as `no active OMH execution state`
- if the file exists but is malformed JSON or not an object, treat that as `broken state`
- if `session_ids` is missing or invalid, normalize it to `[]`
- if `session_origins` is missing or invalid, normalize it to `{}`
- if `task_sessions` is missing or invalid, normalize it to `{}`
- unknown extra fields should be preserved conceptually and ignored by status rendering unless explicitly used

If exactly one session is present and its origin is missing, the status layer may treat it as effectively `direct` for display purposes, matching the spirit of OMO's normalization behavior.

### Artifact validation rules

After the state is read, `omh-status` should validate the execution artifacts in this order:

1. `active_plan`
2. `worktree_path`
3. `last_handoff`
4. `notepad_dir`

Validation rules:
- if `active_plan` is missing from state, the state is **broken**
- if `active_plan` is present but the file does not exist, the state is **broken**
- if `worktree_path` is non-null but missing on disk, the state is **broken**
- if `last_handoff` is set but missing on disk, report a **warning** rather than a fatal error
- if `notepad_dir` is set but missing on disk, report a **warning** rather than a fatal error

This preserves a useful distinction:
- missing authoritative execution anchors are fatal
- missing supplementary artifacts are warnings

### Progress derivation rules

`omh-status` should derive progress from the referenced canonical plan file rather than trusting a cached `progress` field in state.

This is one of the most valuable behaviors to borrow from OMO.

Minimum v0 rule set:
- if the plan file cannot be read, progress is `unknown`
- if the plan file contains structured execution sections, prefer counting execution checkboxes from those sections
- otherwise, fall back to generic checkbox counting across the document

Derived progress fields:
- `total`
- `completed`
- `is_complete`

For v0, OMH should keep the exact parsing rules implementation-defined, but the design requirement is clear: **progress must be computed live from the plan artifact**.

### Derived posture rules

`omh-status` should compute a user-facing posture from both stored state and live artifact validation.

Recommended postures:
- `idle` — no `atlas-state.json` exists
- `active` — state exists, `status = active`, artifacts are valid, plan is incomplete
- `blocked` — state exists, `status = blocked`, artifacts are valid, plan is incomplete
- `complete` — state exists, `status = complete`, and the referenced plan is complete
- `failed` — state exists, `status = failed`
- `cancelled` — state exists, `status = cancelled`
- `stale` — state exists and is readable, authoritative anchors are valid, but stored lifecycle disagrees with live derived facts
- `broken` — state exists but is malformed, schema-invalid in a status-critical way, or references missing authoritative artifacts

Examples of `stale`:
- `status = active` but the plan is already complete
- `status = blocked` but the plan is already complete
- `status = complete` but the plan is still incomplete

Examples of `broken`:
- malformed JSON
- non-object JSON
- missing `active_plan`
- missing plan file
- invalid raw `status` value outside the OMH lifecycle enum
- missing recorded `worktree_path`

Important non-example:
- `status = failed` with an incomplete plan is **not** stale by itself
- `status = cancelled` with an incomplete plan is **not** stale by itself

Terminal lifecycle states may legitimately leave unfinished plan items behind.

### Boundary between `stale` and `broken`

This distinction should be explicit in the spec.

Treat the state as **broken** when `omh-status` cannot establish a trustworthy execution contract.

That includes:
- unreadable or malformed state
- invalid lifecycle enum
- missing authoritative anchor fields
- missing authoritative anchor artifacts on disk

Treat the state as **stale** only when the execution contract is still readable and anchored, but the stored lifecycle no longer matches the live-derived execution facts.

In short:
- **broken = cannot trust the state contract**
- **stale = can read the contract, but it disagrees with reality**

This is the cleanest boundary for both humans and automation.

### Resumability rules

`omh-status` should also compute a `resumable` flag for display.

A state is resumable only when all of the following are true:
- posture is `active` or `blocked`
- `active_plan` exists
- derived plan progress is not complete
- recorded `worktree_path` is either null or valid

Otherwise `resumable = no`.

This keeps `omh-status` aligned with `omh-resume` without letting `omh-status` perform any continuation itself.

### Summary fields to display

For v0, the default human-readable status output should include:
- `Plan`
- `Lifecycle` (raw stored `status` when available)
- `Posture` (derived status summary)
- `Resumable`
- `Progress`
- `Stage`
- `Wave`
- `Sessions`
- `Task Sessions`
- `Active Tasks` (top 1-3 active task slugs when available)
- `Worktree`
- `Last Handoff`
- `Updated`
- `Warnings` (when present)

Recommended session summary behavior:
- show total `session_ids` count
- include a compact origin summary such as direct/appended counts when available
- show `task_sessions` count in default output
- additionally show the top 1-3 active task slugs when they can be derived from `task_sessions`
- do **not** dump the full `task_sessions` mapping in the default text surface

### Machine-readable output (`--json`)

`omh-status --json` should be part of v0.

It should return the same semantic result as the default text mode, but in a stable machine-readable structure.

Recommended top-level fields:
- `state_path`
- `has_state`
- `lifecycle`
- `posture`
- `resumable`
- `plan`
- `progress`
- `stage`
- `wave`
- `sessions`
- `task_sessions`
- `active_task_slugs`
- `worktree`
- `last_handoff`
- `updated_at`
- `warnings`
- `errors`

Recommended shape sketch:

```json
{
  "state_path": ".omh/state/atlas-state.json",
  "has_state": true,
  "lifecycle": "active",
  "posture": "active",
  "resumable": true,
  "plan": {
    "name": "feature-x",
    "path": ".omh/plans/feature-x.md"
  },
  "progress": {
    "total": 8,
    "completed": 3,
    "is_complete": false
  },
  "stage": "exec",
  "wave": 2,
  "sessions": {
    "count": 3,
    "origins": {
      "direct": 1,
      "appended": 2
    }
  },
  "task_sessions": {
    "count": 4
  },
  "active_task_slugs": [
    "auth-middleware",
    "jwt-claims",
    "api-rate-limit"
  ],
  "worktree": {
    "path": "/abs/path/to/worktree",
    "exists": true
  },
  "last_handoff": {
    "path": ".omh/handoffs/verify.md",
    "exists": true
  },
  "updated_at": "ISO_TIMESTAMP",
  "warnings": [],
  "errors": []
}
```

For v0, field names should be treated as part of the contract once published.

That means `--json` should be deliberately small, boring, and stable.

### Read sequence

`omh-status` should follow this order strictly:

1. Look for `.omh/state/atlas-state.json`
2. If the state file is missing, render `idle`
3. If state exists, read and normalize it
4. Validate `active_plan`
5. Derive live plan progress
6. Validate `worktree_path`
7. Check optional artifacts such as `last_handoff` and `notepad_dir`
8. Derive top 1-3 active task slugs from `task_sessions` when possible
9. Compute `posture` and `resumable`
10. Render the user-facing summary or `--json` payload

### Worktree rules

`omh-status` should trust `worktree_path` from state as the authoritative execution location when one is recorded.

It must not guess or invent a different worktree.

If no worktree is recorded, it may display the current project workspace as the execution location summary.

### User-facing output

For no active state:

```text
No active OMH execution state found.

Workspace: <current project>
Next Step: run `omh-plan` to create a canonical plan, or `omh-ulw <intent>` to let OMH route the next step.
```

For a healthy active execution:

```text
OMH Execution Status

Plan: <plan-name>
Lifecycle: active
Posture: active
Resumable: yes
Progress: <completed>/<total>
Stage: <current-stage>
Wave: <current-wave>
Sessions: <count>
Task Sessions: <count>
Active Tasks: <slug-1>, <slug-2>, <slug-3 or none>
Worktree: <worktree-path or current project>
Last Handoff: <handoff-path or none>
Updated: <updated-at>

Execution is in progress.
```

For a blocked execution:

```text
OMH Execution Status

Plan: <plan-name>
Lifecycle: blocked
Posture: blocked
Resumable: yes
Progress: <completed>/<total>
Stage: <current-stage>
Wave: <current-wave>
Active Tasks: <slug-1>, <slug-2>, <slug-3 or none>
Worktree: <worktree-path>
Last Handoff: <handoff-path>
Updated: <updated-at>

Execution is blocked and needs intervention before resume.
```

For a stale execution state:

```text
OMH execution state is stale.

Plan: <plan-name>
Lifecycle: <raw-status>
Posture: stale
Progress: <completed>/<total>
Issue: <lifecycle-progress-mismatch>

Suggested actions:
- inspect why stored lifecycle disagrees with the canonical plan, then
- repair the state intentionally or start a new execution session
```

For a broken execution state:

```text
OMH execution state is broken.

State File: .omh/state/atlas-state.json
Plan: <plan-name or unknown>
Issue: <broken-state-reason>

Suggested actions:
- restore the missing artifact, or
- start a new execution with `omh-start-work`
```

### Exit status guidance

Recommended v0 CLI semantics:
- exit `0` for `idle`, `active`, `blocked`, `complete`, `failed`, and `cancelled`
- exit `1` for `stale`
- exit `1` for `broken`
- exit `1` for unreadable or malformed state

For v0, `stale` should be treated as a failure exit code, not a warning-success hybrid.

Reason:
- humans still get a readable diagnosis
- automation does not silently trust inconsistent execution state
- `stale` now has first-class semantic meaning, so its exit behavior should be first-class too

## `omh-ulw` detailed design (draft)

### OMO reference point

From the upstream OMO repo, `ultrawork` / `ulw` is the lowest-ceremony frontdoor:

- README language is intentionally blunt: *"Install. Type `ultrawork` (or `ulw`). Done."*
- manifesto language is even clearer: *"You provide intent. The agent handles everything."*
- `/ulw-loop` adds the persistence expectation: maximum-intensity execution, parallel agents, background tasks, aggressive exploration, and continuation until the work is actually finished
- runtime `keyword-detector` hook treats ultrawork as a mode injection, not merely a string alias
- model-specific ultrawork prompts still enforce **intent classification before acting**, so ultrawork does **not** mean blind implementation

OMH should preserve this exact philosophy:

**`omh-ulw` is the user-friendly, low-ceremony frontdoor.**

The other commands (`omh-plan`, `omh-start-work`, `omh-resume`, `omh-status`) remain real and explicit, but `omh-ulw` is the command that lets the user say what they want once and then stop babysitting the workflow.

### Role

`omh-ulw` is the convenience orchestration entrypoint for OMH.

It should:
- accept raw user intent
- classify the intent
- choose the correct internal OMH route
- keep the work moving until the routed objective is complete, blocked, or explicitly stopped

It is the closest Hermes-native equivalent to OMO's `ultrawork` experience.

### Command shape

```bash
omh-ulw <intent...>
```

Chat-mode equivalent:
- user message containing `ultrawork`
- user message containing `ulw`

These should be treated as equivalent entry surfaces into the same orchestration mode.

For v0, `omh-ulw` should require an intent payload, whether inline in the command or present in the triggering user message.

### Core philosophy

`omh-ulw` should preserve four OMO behaviors at the UX layer:

1. **Low ceremony**
   - the user should not need to decide first between planning, execution, or resume
2. **Intent-first routing**
   - the system must classify what the user really wants before it acts
3. **Relentless completion pressure**
   - once execution starts, the system should keep going until there is a real terminal condition
4. **Internal explicitness, external simplicity**
   - internals can stay structured (`omh-plan`, `omh-start-work`, `omh-resume`, `omh-status`), while the user gets a single easy frontdoor

### Explicit non-goals

`omh-ulw` must not:
- blindly force implementation for every complex prompt
- replace the internal need for planning or execution state
- skip verification just because it is in "ultrawork mode"
- become a magic alias that hides broken state instead of reporting it
- require OpenCode runtime features that Hermes does not actually have

### Mandatory Intent Gate

This is the most important behavior to preserve from OMO.

Before `omh-ulw` chooses any execution route, it must classify the user intent.

Recommended v0 intent classes:
- `implementation`
- `fix`
- `investigation`
- `research`
- `evaluation`
- `status`
- `open-ended`

Intent Gate rules:
- if the user asked to build or change something concrete, route toward implementation/fix
- if the user asked to inspect, explain, compare, or investigate, route toward research/investigation first
- if the user asked what we think about a design, route toward evaluation, not immediate implementation
- if the user asked about ongoing execution posture, route toward status

This prevents the biggest OMO-class failure mode: **doing a lot of work in the wrong lane**.

### Internal routing contract

`omh-ulw` should choose one of the following routes after intent classification.

#### Route A: status lane

Use when intent is `status`.

Behavior:
- run `omh-status` semantics
- return current execution posture
- do not start or resume execution unless the user explicitly asks for work to continue

#### Route B: research / investigation / evaluation lane

Use when intent is `research`, `investigation`, or `evaluation`.

Behavior:
- spawn Hermes-native support work aggressively where useful (`explore`, `librarian`, `oracle` style subagents)
- gather findings in parallel
- synthesize the answer or recommendation
- stop after the requested answer is delivered
- do **not** start implementation unless the user explicitly asked for it

`omh-ulw` should still feel intense here — fast, parallel, thorough — but it should respect the fact that the user's requested outcome is knowledge, not code.

#### Route C: implementation / fix lane with resumable state

Use when intent is `implementation` or `fix`, and resumable OMH execution state already exists.

Behavior:
- route into `omh-resume` semantics
- restore execution context from `.omh/state/atlas-state.json`
- continue the current stage/wave instead of creating a new execution

This preserves OMO's continuation mindset: active work should be resumed, not casually abandoned.

#### Route D: implementation / fix lane with canonical plan but no active state

Use when intent is `implementation` or `fix`, a canonical plan exists, and there is no active resumable execution state.

Behavior:
- route into `omh-start-work` semantics
- select the canonical plan
- bootstrap execution state
- enter Atlas execution

#### Route E: implementation / fix lane with no canonical plan

Use when intent is `implementation` or `fix`, and no canonical plan exists yet.

Behavior:
- route into `omh-plan` semantics first
- produce or refine the canonical plan
- then immediately continue into `omh-start-work`
- avoid forcing the user to invoke a second command just to begin execution

This is the strongest OMO-style behavior to preserve: **intent in, structured work out**.

### Route summary

Recommended user-invisible routing table:

| Intent | State condition | Route |
| --- | --- | --- |
| `status` | any | `omh-status` |
| `research` / `investigation` / `evaluation` | any | research lane only |
| `implementation` / `fix` | active resumable state exists | `omh-resume` |
| `implementation` / `fix` | no resumable state, canonical plan exists | `omh-start-work` |
| `implementation` / `fix` | no canonical plan exists | `omh-plan -> omh-start-work` |
| `open-ended` | ambiguous | research + intent clarification by findings, not guesswork |

### Continuation semantics

`omh-ulw` should inherit the spirit of OMO's `ultrawork` + `/ulw-loop` + Atlas continuation stack.

That means:
- once Route C, D, or E enters execution, OMH should keep working until execution becomes `complete`, `blocked`, `failed`, `cancelled`, or explicitly stopped
- session-idle continuation reminders should be considered part of the OMH design, not an optional cosmetic extra
- active execution should remain anchored in `.omh/state/atlas-state.json`
- `omh-ulw` should not silently lose momentum just because the immediate response cycle ended

In OMH terms, `omh-ulw` is the **frontdoor**, while Atlas continuation hooks are the **backpressure system** that keeps work moving.

### Specialist usage rules

To stay faithful to OMO, `omh-ulw` should prefer routine specialist support rather than single-threaded orchestration.

Recommended defaults:
- `explore`-style Hermes subagents for codebase reconnaissance
- `librarian`-style Hermes subagents for official docs / upstream references
- `oracle`-style Hermes subagents for skeptical design/debug review
- focused implementation workers only after the route and plan are clear

Important nuance:
- OMH does **not** need to literally recreate OMO's exact agent APIs
- it **does** need to recreate the habit of cheap, parallel specialist assistance

### Planning and execution boundary

Even inside `omh-ulw`, planning and execution should remain distinct internally.

Rules:
- planning artifacts remain canonical and read-only during execution
- workers may write to notepads / handoffs, not to the canonical plan
- Atlas owns execution state
- `omh-ulw` may implicitly invoke planning, but it must not collapse planning and execution into one fuzzy step

### Verification contract

`omh-ulw` must preserve OMO's completion pressure while also preserving Hermes' verification discipline.

That means:
- no completion claim without fresh evidence
- no "mostly done" output for implementation/fix lanes
- if execution enters a real blocker, it should surface a blocked state with evidence rather than pretending the task is finished
- if verification fails, route into a fix loop rather than reporting success

### User-facing output

For an implementation lane with no plan yet:

```text
OMH Ultrawork

Intent: implementation
Route: omh-plan -> omh-start-work
Mode: ultrawork

No canonical plan exists yet.
Creating a plan first, then entering execution automatically...
```

For an implementation lane with active resumable state:

```text
OMH Ultrawork

Intent: implementation
Route: omh-resume
Mode: ultrawork

Active execution state found.
Re-entering the existing OMH work session...
```

For a research lane:

```text
OMH Ultrawork

Intent: investigation
Route: research lane
Mode: ultrawork

Running parallel codebase and reference research before answering...
```

### Design implication

If OMH wants to feel truly OMO-like, users should usually think in this order:

- easiest entry: `omh-ulw`
- explicit planning: `omh-plan`
- explicit execution bootstrap: `omh-start-work`
- explicit continuation: `omh-resume`
- explicit inspection: `omh-status`

So the internal command family stays explicit, but the default user posture becomes:

**"Use `omh-ulw` unless you intentionally want one of the lower-level command surfaces."**

## Future phases

### Phase 2
- Add plugin-provided orchestration helper tool(s)
- Add safer verification prompts per role
- Add repo-aware rule injection based on nearby docs

### Phase 3
- Add optional ACP-backed delegation profile for OpenCode
- Add category-to-runtime routing helpers
- Add richer session summary/continuation cues

### Phase 4
- Evaluate whether any Hermes core extension is actually worth it
- Only consider this if plugin-only limits become painful in real use

## Verification checklist

- `hermes plugins list` shows `oh-my-hermes` as enabled
- Hermes can import the plugin without errors
- the plugin skill is registered successfully
- `omh-ulw <intent>` enters OMH ultrawork mode
- a sample message containing `ultrawork` returns non-empty injected context
- a normal message without trigger keywords produces no injection
- `omh-ulw` trigger path and explicit command path activate the same routing rules
- `omh-ulw` classifies intent before selecting implementation vs research vs status lanes
- `omh-ulw` can route into `omh-plan -> omh-start-work`, `omh-resume`, or `omh-status` semantics as appropriate

## Immediate implementation plan

### Task 1: Create the plugin manifest
Objective: define the plugin identity and hook surface.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/plugin.yaml`

### Task 2: Create the plugin config
Objective: store keyword triggers, role metadata, and routing hints in YAML.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/config.yaml`

### Task 3: Create the initial Python plugin
Objective: implement config loading, trigger detection, orchestration context injection, and skill registration.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/__init__.py`

### Task 4: Create the initial specialist skill
Objective: provide an explicit Sisyphus-style orchestration skill that the plugin can register.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/skills/sisyphus-orchestrator/SKILL.md`

### Task 5: Add plugin README
Objective: document purpose, limits, and future ACP integration.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/README.md`

### Task 6: Verify base plugin loadability
Objective: ensure Hermes sees the plugin and the basic trigger hook behaves as designed.

Run:
- `hermes plugins list`
- import/test plugin module with Hermes python environment
- invoke the trigger handler with a sample `ultrawork` message

Expected:
- plugin loads cleanly
- trigger message yields orchestration context
- non-trigger message yields `None`

### Task 7: Add `omh-ulw` command/router surface
Objective: turn ultrawork from a mere keyword into a real OMH frontdoor.

Files:
- Modify: `~/.hermes/plugins/oh-my-hermes/__init__.py`
- Create: `~/.hermes/plugins/oh-my-hermes/omh_ulw.py`

### Task 8: Add Intent Gate classification
Objective: classify user intent before routing into planning, research, status, or execution lanes.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/intent_gate.py`
- Modify: `~/.hermes/plugins/oh-my-hermes/omh_ulw.py`

### Task 9: Add OMH route resolver
Objective: resolve `omh-ulw` into `omh-plan`, `omh-start-work`, `omh-resume`, `omh-status`, or research lane behavior based on intent and state.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/route_resolver.py`
- Modify: `~/.hermes/plugins/oh-my-hermes/omh_ulw.py`

### Task 10: Add execution-state helpers
Objective: centralize atlas-state read/validate logic so `omh-ulw`, `omh-resume`, and `omh-status` share one contract.

Files:
- Create: `~/.hermes/plugins/oh-my-hermes/atlas_state.py`
- Modify: `~/.hermes/plugins/oh-my-hermes/__init__.py`

### Task 11: Verify OMO-like routing behavior
Objective: ensure the OMH frontdoor behaves like an OMO-style low-ceremony orchestrator rather than a simple keyword injector.

Run:
- `omh-ulw investigate <topic>`
- `omh-ulw <implementation-intent>` in a workspace with no plan
- `omh-ulw <implementation-intent>` in a workspace with resumable state
- `omh-ulw status`

Expected:
- research intent stays in research lane
- implementation intent without plan routes to `omh-plan -> omh-start-work`
- implementation intent with active state routes to `omh-resume`
- status intent routes to `omh-status`
