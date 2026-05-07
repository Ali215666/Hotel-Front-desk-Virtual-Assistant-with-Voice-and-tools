import asyncio
import json
import time
import uuid
import statistics
import argparse
import platform
import os
import psutil
from pathlib import Path
import websockets

WS_URL = "ws://localhost:8000/ws/chat"

SCENARIOS = {
    "simple": "Hello, I am Nade Ali",
    "rag_only": "What is the pet policy of the hotel?",
    "tool_only": "Tell me the weather there on 2026-05-10?",
    "mixed": "What is the late checkout fee and what's the weather there today?"
}

async def run_trial(scenario_name: str, message: str) -> dict:
    session_id = f"lat_{uuid.uuid4().hex[:8]}"
    
    t_send = None
    t_first_token = None
    t_last_token = None
    token_times = []
    
    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            # Init Handshake
            await ws.send(json.dumps({
                "type": "init",
                "session_id": session_id,
                "user_id": session_id
            }))
            
            # Wait for any status messages before sending our actual payload
            # Actually, the protocol usually just sends status "Connected" or similar, 
            # we can just send the message immediately.
            t_send = time.time()
            await ws.send(json.dumps({
                "session_id": session_id,
                "message": message
            }))
            
            while True:
                raw = await ws.recv()
                t_recv = time.time()
                
                try:
                    frame = json.loads(raw)
                    ftype = frame.get("type", "")
                    if ftype == "token":
                        if t_first_token is None:
                            t_first_token = t_recv
                        token_times.append(t_recv)
                    elif ftype == "done":
                        t_last_token = t_recv
                        break
                    elif ftype == "error":
                        t_last_token = t_recv
                        break
                except json.JSONDecodeError:
                    # Legacy fallback
                    if t_first_token is None:
                        t_first_token = t_recv
                    token_times.append(t_recv)
                    
    except Exception as e:
        print(f"Error during trial for {scenario_name}: {e}")
        
    if not t_send or not t_last_token:
        # Failure
        return None
        
    if not t_first_token:
        # No tokens were sent, maybe direct response
        t_first_token = t_last_token
        
    ttft = t_first_token - t_send
    end_to_end = t_last_token - t_send
    
    if len(token_times) > 1:
        inter_token_intervals = [token_times[i] - token_times[i-1] for i in range(1, len(token_times))]
        inter_token_latency = sum(inter_token_intervals) / len(inter_token_intervals)
    else:
        inter_token_latency = 0.0
        
    return {
        "scenario": scenario_name,
        "ttft_s": ttft,
        "itl_ms": inter_token_latency * 1000,
        "e2e_s": end_to_end
    }

def compute_percentile(data, p):
    if not data:
        return 0.0
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * p
    f = int(k)
    c = f + 1
    if f == c or c >= len(data_sorted):
        return data_sorted[f]
    return data_sorted[f] + (k - f) * (data_sorted[c] - data_sorted[f])

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run 5 trials instead of 30")
    args = parser.parse_args()
    
    trials_per_scenario = 5 if args.quick else 30
    
    print(f"Starting Latency Evaluation (Trials per scenario: {trials_per_scenario})...")
    
    results = []
    
    for scenario_name, message in SCENARIOS.items():
        print(f"\nRunning scenario: {scenario_name}")
        for i in range(trials_per_scenario):
            print(f"  Trial {i+1}/{trials_per_scenario}...", end="", flush=True)
            res = await run_trial(scenario_name, message)
            if res:
                results.append(res)
                print(f" TTFT: {res['ttft_s']:.2f}s | E2E: {res['e2e_s']:.2f}s")
            else:
                print(" FAILED")
                
    # Process metrics
    import csv
    
    report_dir = Path("eval_reports")
    report_dir.mkdir(exist_ok=True)
    
    csv_path = report_dir / "latency_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario", "ttft_s", "itl_ms", "e2e_s"])
        writer.writeheader()
        for r in results:
            writer.writerow(r)
            
    print(f"\nRaw results saved to {csv_path}")
    
    # Markdown Report
    hw_info = [
        f"- **Processor:** {platform.processor() or 'Unknown'}",
        f"- **CPU Count:** {os.cpu_count()}",
        f"- **Total Memory:** {round(psutil.virtual_memory().total / (1024**3), 2)} GB"
    ]
    
    md_lines = [
        "# WebSocket Latency & Performance Report",
        "",
        "## Hardware Setup",
        *hw_info,
        "",
        "## Scenarios Evaluated",
        f"- Trials per scenario: {trials_per_scenario}",
    ]
    
    md_lines.extend([
        "",
        "## Metrics Summary",
        "| Scenario | Metric | Mean | Median | P90 | P99 | Status |",
        "|----------|--------|------|--------|-----|-----|--------|"
    ])
    
    for scenario_name in SCENARIOS.keys():
        scenario_results = [r for r in results if r["scenario"] == scenario_name]
        if not scenario_results:
            continue
            
        ttfts = [r["ttft_s"] for r in scenario_results]
        itls = [r["itl_ms"] for r in scenario_results]
        e2es = [r["e2e_s"] for r in scenario_results]
        
        metrics = [
            ("TTFT (s)", ttfts, 10.0),
            ("Inter-Token (ms)", itls, None),
            ("End-to-End (s)", e2es, 20.0)
        ]
        
        for metric_name, data, threshold in metrics:
            mean_val = statistics.mean(data)
            median_val = statistics.median(data)
            p90_val = compute_percentile(data, 0.90)
            p99_val = compute_percentile(data, 0.99)
            
            status = "✅ PASS"
            if threshold and median_val > threshold:
                status = "❌ FAILING threshold"
                
            md_lines.append(f"| {scenario_name} | {metric_name} | {mean_val:.3f} | {median_val:.3f} | {p90_val:.3f} | {p99_val:.3f} | {status} |")
            
    md_path = report_dir / "latency_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown report saved to {md_path}")

if __name__ == "__main__":
    asyncio.run(main())
