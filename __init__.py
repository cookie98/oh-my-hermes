from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

import yaml

from .omh_exec import handle_omh_exec_command
from .omh_fix import handle_omh_fix_command
from .omh_plan import handle_omh_plan_command
from .omh_resume import handle_omh_resume_command
from .omh_start_work import handle_omh_start_work_command
from .omh_status import handle_omh_status_command
from .omh_ulw import MODE_MARKER, ULW_MARKER, build_ulw_context, handle_omh_ulw_command, should_activate
from .omh_verify import handle_omh_verify_command

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).parent
_CONFIG_PATH = _PLUGIN_DIR / 'config.yaml'

_DEFAULT_CONFIG: Dict[str, Any] = {
    'enabled': True,
    'enabled_platforms': ['cli', 'telegram', 'slack'],
    'trigger_keywords': ['ultrawork', 'ulw', 'sisyphus', 'orchestrate', 'omh-ulw'],
    'inject_on_first_turn_only': False,
    'max_instruction_chars': 3200,
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
                config = merged
    except Exception as exc:
        logger.warning('oh-my-hermes: failed to load config: %s', exc)
    return config


def _normalize_platform(platform: str) -> str:
    return (platform or '').strip().lower()


def _pre_llm_call(*, user_message: str = '', platform: str = '', is_first_turn: bool = False, **_: Any) -> Dict[str, str] | None:
    config = _load_config()
    if not config.get('enabled', True):
        return None

    enabled_platforms = {_normalize_platform(p) for p in (config.get('enabled_platforms') or [])}
    normalized_platform = _normalize_platform(platform)
    if enabled_platforms and normalized_platform not in enabled_platforms:
        return None

    if config.get('inject_on_first_turn_only') and not is_first_turn:
        return None

    message = user_message or ''
    if MODE_MARKER in message or ULW_MARKER in message:
        return None

    if not should_activate(message, config):
        return None

    return {'context': build_ulw_context(user_message=message, config=config)}


def _on_session_start(*, session_id: str = '', platform: str = '', **_: Any) -> None:
    logger.info('oh-my-hermes session start: session_id=%s platform=%s', session_id, platform)


def _omh_ulw_command_factory(ctx: Any):
    def _handler(raw_args: str) -> str | None:
        return handle_omh_ulw_command(raw_args, ctx=ctx)

    return _handler


def register(ctx: Any) -> None:
    ctx.register_hook('pre_llm_call', _pre_llm_call)
    ctx.register_hook('on_session_start', _on_session_start)
    ctx.register_command('omh-plan', handle_omh_plan_command, description='Create or reuse a canonical OMH plan from raw intent. Supports `--json`.')
    ctx.register_command('omh-resume', handle_omh_resume_command, description='Resume an existing resumable OMH execution state.')
    ctx.register_command('omh-start-work', handle_omh_start_work_command, description='Bootstrap OMH execution from a canonical plan. Supports `--json` and optional `--worktree`.')
    ctx.register_command('omh-ulw', _omh_ulw_command_factory(ctx), description='OMH ultrawork frontdoor: classify intent, route, and continue in Hermes-first mode.')
    ctx.register_command('omh-status', handle_omh_status_command, description='Inspect OMH execution state in text mode or with `--json`.')
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
