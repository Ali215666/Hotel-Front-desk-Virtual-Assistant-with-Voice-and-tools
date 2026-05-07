import os
import sys
import time
import argparse
import subprocess
import platform
import psutil
from datetime import datetime
from pathlib import Path
import importlib.metadata

def check_server():
    """Check if the backend server is running on localhost:8000."""
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request("http://localhost:8000/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return True
    except Exception:
        # Some servers don't have a /health endpoint, so we fallback to a websocket check
        import asyncio
        import websockets
        
        async def check_ws():
            try:
                async with websockets.connect("ws://localhost:8000/ws/healthcheck", open_timeout=2) as ws:
                    return True
            except websockets.exceptions.InvalidURI:
                return False
            except Exception:
                # Connection refused etc.
                return False
                
        return asyncio.run(check_ws())
    return False

def get_pkg_version(pkg_name):
    try:
        return importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return "Not installed"

def parse_report_metrics(report_path: Path):
    """Attempt to parse basic metrics from a report to populate the summary table."""
    content = report_path.read_text(encoding="utf-8")
    
    # Defaults
    tests_run = "N/A"
    pass_rate = "N/A"
    key_metric = "N/A"
    status = "✅ PASS"
    
    content_lower = content.lower()
    if "failing" in content_lower or "❌" in content_lower:
        status = "❌ FAIL/WARN"
        
    if "conversational" in report_path.name:
        # Example: Dialogues evaluated: 10
        # Avg Overall: 0.85
        import re
        m = re.search(r"Dialogues evaluated:\s*(\d+)", content)
        if m: tests_run = m.group(1)
        m2 = re.search(r"Avg Overall:\s*([\d.]+)", content)
        if m2: key_metric = f"Score {m2.group(1)}/1.0"
        
    elif "rag" in report_path.name:
        import re
        m = re.search(r"Total Queries:\s*(\d+)", content)
        if m: tests_run = m.group(1)
        m2 = re.search(r"MRR:\s*([\d.]+)", content)
        if m2: key_metric = f"MRR {m2.group(1)}"
        m3 = re.search(r"Faithfulness.*?(\d+\.?\d*)", content)
        if m3: pass_rate = f"Faith: {m3.group(1)}"
        
    elif "tool" in report_path.name:
        import re
        m = re.search(r"Correct Tool Rate:\s*([\d.]+%?)", content)
        if m: key_metric = f"Tool Rate: {m.group(1)}"
        
        # Unit tests table count
        tests_run = str(content.count("PASSED") + content.count("FAILED"))
        
    elif "latency" in report_path.name:
        import re
        m = re.search(r"Trials per scenario:\s*(\d+)", content)
        if m: tests_run = m.group(1) + "x4"
        
        # find mixed median e2e
        m2 = re.search(r"mixed\s*\|\s*End-to-End.*?\|\s*[\d.]+\s*\|\s*([\d.]+)", content)
        if m2: key_metric = f"Mixed E2E Med: {m2.group(1)}s"
        
    elif "throughput" in report_path.name:
        import re
        m = re.search(r"Max Sustainable Concurrency:\s*`([^`]+)`", content)
        if m: key_metric = f"Max N: {m.group(1)}"
        tests_run = "Multi-N"
        
    return tests_run, pass_rate, key_metric, status

def run_suite(name, command):
    print(f"\n========================================================")
    print(f"Running Suite: {name}")
    print(f"========================================================")
    
    try:
        # We use subprocess.run and pipe stdout/stderr to screen
        result = subprocess.run(
            command, 
            shell=True, 
            check=False,
            text=True
        )
        if result.returncode != 0:
            print(f"\n⚠️ {name} completed with non-zero exit code ({result.returncode}).")
            return False
        return True
    except Exception as e:
        print(f"\n❌ Exception running {name}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-throughput", action="store_true", help="Skip the slow concurrency tests")
    parser.add_argument("--aggregate-only", action="store_true", help="Do not run any tests, just aggregate existing reports in eval_reports/")
    args = parser.parse_args()
    
    print("Checking backend server status...")
    if not args.aggregate_only and not check_server():
        print("Backend server does not appear to be running on localhost:8000.")
        print("Please start it with: python -m uvicorn main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)
    if not args.aggregate_only:
        print("Server is reachable.\n")
    
    suites = [
        ("Conversational Evals", "pytest tests/test_conversational_evals.py"),
        ("RAG Evals", "pytest tests/test_rag_evals.py"),
        ("Tool Evals", "pytest tests/test_tool_evals.py"),
        ("Latency Benchmarks", "python tests/test_latency_evals.py")
    ]
    
    if not args.skip_throughput:
        suites.append(("Throughput Concurrency Tests", "python tests/test_throughput_evals.py"))
        
    results = {}
    if not args.aggregate_only:
        for name, cmd in suites:
            success = run_suite(name, cmd)
            results[name] = success
        
    print("\n" + "="*60)
    print("AGGREGATING FINAL REPORT")
    print("="*60)
    
    report_dir = Path("eval_reports")
    final_report_path = report_dir / "FINAL_REPORT.md"
    
    hw_info = [
        f"**Processor:** {platform.processor() or 'Unknown'}",
        f"**CPU Count:** {os.cpu_count()}",
        f"**Memory:** {round(psutil.virtual_memory().total / (1024**3), 2)} GB",
        f"**OS:** {platform.system()} {platform.release()}"
    ]
    
    deps = ["fastapi", "uvicorn", "websockets", "sentence-transformers", "faiss-cpu", "anthropic"]
    dep_info = [f"- `{dep}`: {get_pkg_version(dep)}" for dep in deps]
    
    lines = [
        "# Comprehensive Hotel Assistant Evaluation Report",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Hardware & Environment",
        *hw_info,
        "",
        "### Core Dependencies",
        *dep_info,
        "",
        "## Executive Summary",
        "| Suite | Tests Run | Pass Rate | Key Metric | Status |",
        "|-------|-----------|-----------|------------|--------|"
    ]
    
    issues = []
    
    # Parse individual reports
    report_files = [
        ("Conversational Evals", "conversational_report.md"),
        ("RAG Evals", "rag_report.md"),
        ("Tool Evals", "tool_report.md"),
        ("Latency Benchmarks", "latency_report.md"),
    ]
    if not args.skip_throughput:
        report_files.append(("Throughput Concurrency Tests", "throughput_report.md"))
        
    report_contents = []
    
    for suite_name, filename in report_files:
        p = report_dir / filename
        if p.exists():
            tr, pr, km, st = parse_report_metrics(p)
            lines.append(f"| {suite_name} | {tr} | {pr} | {km} | {st} |")
            if "FAIL" in st or "WARN" in st:
                issues.append(f"- **{suite_name}**: Flagged as having failures or warnings. See detail section below.")
                
            report_contents.append(f"\n\n---\n\n# Detailed Report: {suite_name}\n\n")
            report_contents.append(p.read_text(encoding="utf-8"))
        else:
            lines.append(f"| {suite_name} | N/A | N/A | N/A | ⚠️ MISSING |")
            issues.append(f"- **{suite_name}**: Report file `{filename}` was not generated.")

    lines.append("")
    lines.append("## ⚠️ Issues Found")
    if issues:
        lines.extend(issues)
    else:
        lines.append("No critical issues flagged across the generated reports!")
        
    lines.extend(report_contents)
    
    final_report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Final Aggregated Report generated at: {final_report_path}")

if __name__ == "__main__":
    main()
