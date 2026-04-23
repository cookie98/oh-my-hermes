from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from .atlas_state import get_state_path, get_workspace_root, read_atlas_state, write_json_atomically
except ImportError:  # pragma: no cover
    from atlas_state import get_state_path, get_workspace_root, read_atlas_state, write_json_atomically



def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')



def _completion_root(workspace: Path) -> Path:
    return workspace / '.omh' / 'completed'



def _bundle_dir(workspace: Path, plan_name: str, stamp: str) -> Path:
    slug = str(plan_name or 'omh-plan').strip() or 'omh-plan'
    safe_stamp = stamp.replace(':', '').replace('-', '')
    return _completion_root(workspace) / f'{slug}-{safe_stamp}'



def _lineage_edges(task_sessions: Dict[str, Any]) -> list[str]:
    edges: list[str] = []
    for slug, payload in (task_sessions or {}).items():
        if not isinstance(payload, dict):
            continue
        for child in payload.get('blocks') or []:
            child_slug = str(child).strip()
            if child_slug:
                edges.append(f'{slug} -> {child_slug}')
    return sorted(dict.fromkeys(edges))



def _artifact_paths(task_sessions: Dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for payload in (task_sessions or {}).values():
        if not isinstance(payload, dict):
            continue
        artifacts = payload.get('artifacts') or {}
        artifact_paths = artifacts.get('artifact_paths') or {}
        for value in artifact_paths.values():
            text = str(value).strip()
            if text:
                paths.append(text)
    return sorted(dict.fromkeys(paths))



def _copy_task_artifacts(task_sessions: Dict[str, Any], bundle_dir: Path) -> None:
    target_root = bundle_dir / 'artifacts'
    for slug, payload in (task_sessions or {}).items():
        if not isinstance(payload, dict):
            continue
        artifacts = payload.get('artifacts') or {}
        artifacts_dir = artifacts.get('artifacts_dir')
        if not artifacts_dir:
            continue
        source = Path(str(artifacts_dir)).expanduser()
        if not source.exists() or not source.is_dir():
            continue
        destination = target_root / slug
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)



def _write_summary(bundle_dir: Path, state: Dict[str, Any], *, stamp: str) -> Path:
    task_sessions = state.get('task_sessions') or {}
    total_tasks = len(task_sessions)
    completed_tasks = sum(1 for payload in task_sessions.values() if str((payload or {}).get('status') or '').strip().lower() == 'completed')
    lineage = state.get('lineage') or {}
    waves_executed = int(lineage.get('total_waves') or 0)
    failures = sum(1 for payload in task_sessions.values() if str((payload or {}).get('status') or '').strip().lower() not in {'completed', 'cancelled'})
    artifact_paths = _artifact_paths(task_sessions)
    edges = _lineage_edges(task_sessions)
    started_at = state.get('started_at') or 'unknown'
    lines = [
        '# OMH Completion Summary',
        '',
        f'- Plan: {state.get("plan_name") or "unknown"}',
        f'- Completed At: {stamp}',
        f'- Started At: {started_at}',
        f'- Tasks Done: {completed_tasks}',
        f'- Total Tasks: {total_tasks}',
        f'- Waves Executed: {waves_executed}',
        f'- Failures: {failures}',
        '',
        'Artifacts:',
    ]
    if artifact_paths:
        lines.extend([f'- {path}' for path in artifact_paths])
    else:
        lines.append('- none')
    lines.extend(['', 'Lineage Tree:'])
    if edges:
        lines.extend([f'- {edge}' for edge in edges])
    else:
        lines.append('- none')
    summary_path = bundle_dir / 'summary.md'
    summary_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    return summary_path



def build_complete_payload(raw_args: str = '', *, workspace: Path | None = None) -> Dict[str, Any]:
    root = (workspace or get_workspace_root()).expanduser().resolve()
    snapshot = read_atlas_state(root)
    if not snapshot.has_state or not snapshot.state:
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'No OMH execution state was found to complete. Run `omh-start-work` first.',
        }
    if snapshot.posture != 'complete' or snapshot.lifecycle != 'complete':
        return {
            'mode': 'error',
            'workspace': str(root),
            'reason': 'OMH completion bundle can run only after execution reaches complete posture.',
        }

    stamp = _now_iso()
    state = dict(snapshot.state)
    bundle_dir = _bundle_dir(root, str(state.get('plan_name') or 'omh-plan'), stamp)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(get_state_path(root), bundle_dir / 'atlas-state.json')
    _copy_task_artifacts(state.get('task_sessions') or {}, bundle_dir)
    summary_path = _write_summary(bundle_dir, state, stamp=stamp)

    state['completion'] = {
        'bundle_dir': str(bundle_dir),
        'summary_path': str(summary_path),
        'completed_at': stamp,
    }
    state['plan_locked'] = False
    state['updated_at'] = stamp
    write_json_atomically(get_state_path(root), state)
    return {
        'mode': 'recorded',
        'workspace': str(root),
        'state_path': str(get_state_path(root)),
        'bundle_dir': str(bundle_dir),
        'summary_path': str(summary_path),
        'state': state,
    }



def render_complete_text(payload: Dict[str, Any]) -> str:
    mode = payload.get('mode')
    if mode == 'error':
        return str(payload.get('reason'))
    state = payload.get('state') or {}
    completion = state.get('completion') or {}
    return (
        'Recorded OMH completion bundle\n\n'
        f'Plan: {state.get("plan_name") or "unknown"}\n'
        f'Bundle: {completion.get("bundle_dir") or payload.get("bundle_dir") or "none"}\n'
        f'Summary: {completion.get("summary_path") or payload.get("summary_path") or "none"}'
    )



def handle_omh_complete_command(raw_args: str, *, workspace: Path | None = None) -> str:
    payload = build_complete_payload(raw_args, workspace=workspace)
    if '--json' in (raw_args or '').split() and payload.get('mode') != 'error':
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return render_complete_text(payload)
