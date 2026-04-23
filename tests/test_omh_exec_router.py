from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omh_exec import _classify_task_session


def test_classify_research_task():
    assert _classify_task_session({'label': 'Research async libraries'}) == 'research'


def test_classify_verify_task():
    assert _classify_task_session({'label': 'Verify login flow', 'acceptance': ['test coverage > 80%']}) == 'verify'


def test_classify_implement_task():
    assert _classify_task_session({'label': 'Add JWT middleware', 'files': ['src/auth.py']}) == 'implement'


def test_default_to_implement_when_ambiguous():
    assert _classify_task_session({'label': 'Do something'}) == 'implement'
