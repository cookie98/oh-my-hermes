import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omh_start_work import _extract_execution_tasks


def test_extracts_acceptance_and_files():
    md = '''\n### Task 1: Add auth\n\n**Files:**\n- Modify: src/auth.py\n- Test: tests/test_auth.py\n\n- [ ] Step 1: Write the failing test\n  - AC: login returns 401 without token\n- [ ] Step 2: Implement minimal code\n  - AC: login returns 200 with valid token\n'''
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'plan.md'
        p.write_text(md, encoding='utf-8')
        tasks = _extract_execution_tasks(p)
    assert len(tasks) == 2
    assert tasks['T1']['files'] == ['src/auth.py']
    assert tasks['T1']['tests'] == ['tests/test_auth.py']
    assert tasks['T1']['acceptance'] == ['login returns 401 without token']
    assert tasks['T2']['acceptance'] == ['login returns 200 with valid token']
