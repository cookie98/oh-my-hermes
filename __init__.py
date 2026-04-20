from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

import yaml

from .atlas_state import get_workspace_root, read_atlas_state
from .continuation_enforcement import build_idle_continuation_pressure
from .continuation_hooks import (
    build_continuation_context,
    should_inject_continuation_context,
    should_inject_idle_continuation_context,
)
from .omh_exec import handle_omh_exec_command
from .omh_fix import handle_omh_fix_command
from .omh_plan import handle_omh_plan_command
from .omh_resume import handle_omh_resume_command
from .omh_start_work import handle_omh_start_work_command
from .omh_status import handle_omh_status_command
from .omh_ulw import MODE_MARKER, ULW_MARKER, build_ulw_context, handle_omh_ulw_command, should_activate
from .omh_verify import handle_omh_verify_command
from .supervision_refresh import refresh_detached_worker_supervision

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).parent
_CONFIG_PATH = _PLUGIN_DIR / 'config.yaml'

_DEFAULT_CONFIG: Dict[str, Any] = {
    'enabled': True,
    'enabled_platforms': ['cli', 'telegram', 'slack'],
    'trigger_keywords': ['ultrawork', 'ulw', 'sisyphus', 'orchestrate', 'omh-ulw'],
    'inject_on_first_turn_only': False,
    'max_instruction_chars': 3200,
    'idle_continuation': {
        'enabled': True,
        'soft_threshold_minutes': 60,
        'strict_threshold_minutes': 15,
        'cooldown_minutes': 30,
    },
    'agents': {},
    'categories': {},
    'delegate_runtime': {'preferred': 'hermes-native'},
    'planning_backend': {
        'preferred': 'hermes-native',
        'optional_claude_code': True,
        'optional_omc': True,
    },
}


def _load_config() -> Dict[str, Any]:
    config = dict(_DEFAULT_CONFIG)
    try:
        if _CONFIG_PATH.exists():
            loaded = yaml.safe_load(_CONFIG_PATH.read_text(encoding='utf-8')) or {}
            if isinstance(loaded, dict):
                merged = dict(config)
                merged.update(loaded)
                idle_defaults = dict(_DEFAULT_CONFIG.get('idle_continuation') or {})
                loaded_idle = loaded.get('idle_continuation') if isinstance(loaded.get('idle_continuation'), dict) else {}
                merged['idle_continuation'] = {**idle_defaults, **loaded_idle}
                config = merged
    except Exception as exc:
        logger.warning('oh-my-hermes: failed to load config: %s', exc)
    return config


def _normalize_platform(platform: str) -> str:
    return (platform or '').strip().lower()


def _resolve_process_poller(ctx: Any | None):
    candidate = getattr(ctx, 'poll_background_process', None) if ctx is not None else None
    return candidate if callable(candidate) else None


def _state_file(workspace: Path) -> Path:
    return workspace / '.omh' / 'state' / 'atlas-state.json'


def _write_idle_continuation_nudge(workspace: Path, *, timestamp: str) -> None:
    state_path = _state_file(workspace)
    if not state_path.exists():
        return
    try:
        raw = json.loads(state_path.read_text(encoding='utf-8'))
    except Exception:
        return
    if not isinstance(raw, dict):
        return

    continuation = raw.get('continuation_enforcement') if isinstance(raw.get('continuation_enforcement'), dict) else {}
    idle = continuation.get('idle') if isinstance(continuation.get('idle'), dict) else {}
    next_idle = dict(idle)
    next_idle['last_nudged_at'] = timestamp
    next_idle['nudge_count'] = int(next_idle.get('nudge_count') or 0) + 1
    continuation = dict(continuation)
    continuation['idle'] = next_idle
    raw['continuation_enforcement'] = continuation
    state_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')



def _pre_llm_call_impl(
    *,
    process_poller: Any = None,
    user_message: str = '',
    platform: str = '',
    is_first_turn: bool = False,
    now: str | None = None,
    **_: Any,
) -> Dict[str, str] | None:
    config = _load_config()
    if not config.get('enabled', True):
        return None

    enabled_platforms = {_normalize_platform(p) for p in (config.get('enabled_platforms') or [])}
    normalized_platform = _normalize_platform(platform)
    if enabled_platforms and normalized_platform not in enabled_platforms:
        return None

    message = user_message or ''
    if MODE_MARKER in message or ULW_MARKER in message:
        return None

    snapshot = read_atlas_state()
    should_refresh = should_inject_continuation_context(user_message=message, is_first_turn=is_first_turn, resumable=snapshot.resumable)
    idle_settings = config.get('idle_continuation') if isinstance(config.get('idle_continuation'), dict) else {}
    idle_pressure = build_idle_continuation_pressure(snapshot, now=now, config=idle_settings)
    should_force_idle = bool(idle_settings.get('enabled', True)) and should_inject_idle_continuation_context(
        user_message=message,
        is_first_turn=is_first_turn,
        idle_pressure=idle_pressure,
    )

    if (should_refresh or should_force_idle) and process_poller:
        snapshot = refresh_detached_worker_supervision(get_workspace_root(), process_poller=process_poller)
        idle_pressure = build_idle_continuation_pressure(snapshot, now=now, config=idle_settings)
        should_force_idle = bool(idle_settings.get('enabled', True)) and should_inject_idle_continuation_context(
            user_message=message,
            is_first_turn=is_first_turn,
            idle_pressure=idle_pressure,
        )

    if should_inject_continuation_context(user_message=message, is_first_turn=is_first_turn, resumable=snapshot.resumable):
        return {'context': build_continuation_context(snapshot, now=now, config=idle_settings)}

    if should_force_idle:
        if now:
            _write_idle_continuation_nudge(get_workspace_root(), timestamp=now)
        return {'context': build_continuation_context(snapshot, now=now, config=idle_settings)}

    if config.get('inject_on_first_turn_only') and not is_first_turn:
        return None

    if not should_activate(message, config):
        return None

    return {'context': build_ulw_context(user_message=message, config=config)}


def _pre_llm_call(*, user_message: str = '', platform: str = '', is_first_turn: bool = False, **kwargs: Any) -> Dict[str, str] | None:
    return _pre_llm_call_impl(user_message=user_message, platform=platform, is_first_turn=is_first_turn, **kwargs)


def _pre_llm_call_factory(ctx: Any):
    def _handler(*, user_message: str = '', platform: str = '', is_first_turn: bool = False, **kwargs: Any) -> Dict[str, str] | None:
        return _pre_llm_call_impl(process_poller=_resolve_process_poller(ctx), user_message=user_message, platform=platform, is_first_turn=is_first_turn, **kwargs)

    return _handler


def _on_session_start(*, session_id: str = '', platform: str = '', **_: Any) -> None:
    logger.info('oh-my-hermes session start: session_id=%s platform=%s', session_id, platform)


def _omh_ulw_command_factory(ctx: Any):
    def _handler(raw_args: str) -> str | None:
        return handle_omh_ulw_command(raw_args, ctx=ctx)

    return _handler


def _omh_status_command_factory(ctx: Any):
    def _handler(raw_args: str) -> str:
        return handle_omh_status_command(raw_args, process_poller=_resolve_process_poller(ctx))

    return _handler


def _omh_resume_command_factory(ctx: Any):
    def _handler(raw_args: str) -> str:
        return handle_omh_resume_command(raw_args, process_poller=_resolve_process_poller(ctx))

    return _handler


def register(ctx: Any) -> None:
    ctx.register_hook('pre_llm_call', _pre_llm_call_factory(ctx))
    ctx.register_hook('on_session_start', _on_session_start)
    ctx.register_command('omh-plan', handle_omh_plan_command, description='Create or reuse a canonical OMH plan from raw intent. Supports `--json`.')
    ctx.register_command('omh-resume', _omh_resume_command_factory(ctx), description='Resume an existing resumable OMH execution state.')
    ctx.register_command('omh-start-work', handle_omh_start_work_command, description='Bootstrap OMH execution from a canonical plan. Supports `--json` and optional `--worktree`.')
    ctx.register_command('omh-ulw', _omh_ulw_command_factory(ctx), description='OMH ultrawork frontdoor: classify intent, route, and continue in Hermes-first mode.')
    ctx.register_command('omh-status', _omh_status_command_factory(ctx), description='Inspect OMH execution state in text mode or with `--json`.')
    ctx.register_command('omh-exec', handle_omh_exec_command, description='Internal OMH exec driver: continue the current stage and route through resume/verify/fix surfaces.')
    ctx.register_command('omh-verify', handle_omh_verify_command, description='Record an internal OMH verification result via `omh-verify <pass|fail> [summary...]`.')
    ctx.register_command('omh-fix', handle_omh_fix_command, description='Record an internal OMH remediation result and re-enter verify stage.')

    skill_path = _PLUGIN_DIR / 'skills' / 'sisyphus-orchestrator' / 'SKILL.md'
    if skill_path.exists():
        ctx.register_skill(
            'sisyphus-orchestrator',
            skill_path,
            'Hermes-native orchestration guide inspired by oh-my-opencode.',
        )
