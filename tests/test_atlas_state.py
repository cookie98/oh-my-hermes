from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas_state import _check_state_consistency


def test_warns_when_task_completed_but_worker_running():
    state = {
        'task_sessions': {
            'T1': {'status': 'completed', 'session_id': 'sess-1'},
        },
        'worker_orchestration': {
            'worker_sessions': {
                'sess-1': {'status': 'running'},
            },
        },
    }
    warnings = _check_state_consistency(state)
    assert len(warnings) == 1
    assert 'T1' in warnings[0]


def test_warns_when_task_running_but_worker_lost():
    state = {
        'task_sessions': {
            'T1': {'status': 'running', 'session_id': 'sess-1'},
        },
        'worker_orchestration': {
            'worker_sessions': {
                'sess-1': {'status': 'lost'},
            },
        },
    }
    warnings = _check_state_consistency(state)
    assert len(warnings) == 1
    assert 'already lost' in warnings[0]
