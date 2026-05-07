import os
import shutil
import tempfile
import pytest
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@pytest.fixture
def temp_crm_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_crm.db")
    
    # Copy existing if needed, but here we just create a fresh DB Path for testing
    original_db = Path("data/crm.db")
    if original_db.exists():
        shutil.copy2(original_db, db_path)
    
    yield db_path
    
    shutil.rmtree(temp_dir, ignore_errors=True)

_test_results = []

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and "test_tool_evals.py" in item.nodeid:
        _test_results.append({
            "name": item.name,
            "outcome": rep.outcome.upper(),
            "duration": rep.duration
        })

def pytest_sessionfinish(session, exitstatus):
    report_dir = Path("eval_reports")
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "tool_report.md"
    
    unit_tests = [tr for tr in _test_results if tr["name"] != "test_llm_tool_invocation_accuracy"]
    
    if not unit_tests:
        return
        
    lines = [
        "",
        "## Backend Unit Test Results",
        "| Test Name | Outcome | Duration (s) |",
        "|-----------|---------|--------------|"
    ]
    for tr in unit_tests:
        icon = "✅" if tr["outcome"] == "PASSED" else "❌" if tr["outcome"] == "FAILED" else "⚠️"
        lines.append(f"| `{tr['name']}` | {icon} {tr['outcome']} | {tr['duration']:.3f} |")
        
    # Append to the file (it should have been created by test_llm_tool_invocation_accuracy)
    mode = "a" if report_path.exists() else "w"
    with open(report_path, mode, encoding="utf-8") as f:
        f.write("\n" + "\n".join(lines) + "\n")

