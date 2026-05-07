import asyncio
import json
import time
import uuid
import statistics
import websockets
from pathlib import Path

WS_URL = "ws://localhost:8000/ws/chat"
CONCURRENCY_LEVELS = [1, 2, 5, 10, 15, 20]
TIMEOUT_S = 30.0

MESSAGES = [
    "Hello, I am Nade Ali",
    "What is the late checkout fee?",
    "Tell me the weather there on 2026-05-09?"
]

async def run_single_session(session_id: str) -> dict:
    """Run one complete session (3 turns). Return metrics."""
    metrics = {"ttfts": [], "e2es": [], "errors": 0}
    
    try:
        async with websockets.connect(WS_URL, open_timeout=10.0, close_timeout=5.0) as ws:
            # Handshake
            await ws.send(json.dumps({
                "type": "init",
                "session_id": session_id,
                "user_id": session_id
            }))
            
            for msg in MESSAGES:
                t_send = time.time()
                t_first_token = None
                t_last_token = None
                
                await ws.send(json.dumps({"session_id": session_id, "message": msg}))
                
                # Wait for response with timeout
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_S)
                        t_recv = time.time()
                        
                        try:
                            frame = json.loads(raw)
                            ftype = frame.get("type", "")
                            
                            if ftype == "token":
                                if not t_first_token:
                                    t_first_token = t_recv
                            elif ftype == "done" or ftype == "error":
                                t_last_token = t_recv
                                break
                        except json.JSONDecodeError:
                            if not t_first_token:
                                t_first_token = t_recv
                except asyncio.TimeoutError:
                    metrics["errors"] += 1
                    break  # Abort remaining turns for this session if timeout
                
                if t_last_token:
                    if not t_first_token:
                        t_first_token = t_last_token
                    metrics["ttfts"].append(t_first_token - t_send)
                    metrics["e2es"].append(t_last_token - t_send)
                else:
                    metrics["errors"] += 1
                    break
                    
    except Exception:
        # Connection error
        metrics["errors"] += len(MESSAGES) - len(metrics["ttfts"])
        
    return metrics

async def run_concurrent_batch(n: int):
    """Run N sessions concurrently and aggregate metrics."""
    print(f"\n--- Running Concurrency N={n} ---")
    start_time = time.time()
    
    tasks = []
    for i in range(n):
        session_id = f"thr_{n}_{i}_{uuid.uuid4().hex[:6]}"
        tasks.append(run_single_session(session_id))
        
    results = await asyncio.gather(*tasks)
    total_time = time.time() - start_time
    
    all_ttfts = []
    all_e2es = []
    total_errors = 0
    total_expected_turns = n * 3
    
    for r in results:
        all_ttfts.extend(r["ttfts"])
        all_e2es.extend(r["e2es"])
        total_errors += r["errors"]
        
    median_ttft = statistics.median(all_ttfts) if all_ttfts else float('inf')
    median_e2e = statistics.median(all_e2es) if all_e2es else float('inf')
    error_rate = total_errors / total_expected_turns
    tps = (len(all_ttfts)) / total_time
    
    print(f"Results N={n}: Med TTFT={median_ttft:.2f}s | Med E2E={median_e2e:.2f}s | ErrRate={error_rate:.1%} | TPS={tps:.2f}")
    
    return {
        "n": n,
        "median_ttft": median_ttft,
        "median_e2e": median_e2e,
        "error_rate": error_rate,
        "tps": tps
    }

async def main():
    print("Starting Throughput & Concurrency Tests...")
    
    all_metrics = []
    
    for n in CONCURRENCY_LEVELS:
        metrics = await run_concurrent_batch(n)
        all_metrics.append(metrics)
        # brief pause to let server recover connections
        await asyncio.sleep(2)
        
    # Determine max sustainable
    max_sustainable = None
    for m in reversed(all_metrics):
        if m["median_ttft"] < 15.0 and m["error_rate"] < 0.15:
            max_sustainable = m["n"]
            break
            
    # Determine breakpoint (>50% increase in TTFT)
    breakpoint_n = None
    prev_ttft = None
    for m in all_metrics:
        if prev_ttft and m["median_ttft"] > prev_ttft * 1.5:
            breakpoint_n = m["n"]
            break
        prev_ttft = m["median_ttft"]
        
    # Generate Report
    report_dir = Path("eval_reports")
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "throughput_report.md"
    
    lines = [
        "# WebSocket Concurrency & Throughput Report",
        "",
        "## Key Findings",
        f"- **Max Sustainable Concurrency:** `{max_sustainable or 'None'} users` (Median TTFT < 15s & Error < 15%)",
        f"- **Degradation Breakpoint:** `{breakpoint_n or 'None'} users` (TTFT spikes > 50%)",
        "",
        "## Concurrency vs Latency",
        "| Concurrent Users (N) | Median TTFT (s) | Median E2E (s) | Error Rate | Turns / Sec |",
        "|----------------------|-----------------|----------------|------------|-------------|"
    ]
    
    for m in all_metrics:
        ttft_str = f"{m['median_ttft']:.2f}" if m['median_ttft'] != float('inf') else "N/A"
        e2e_str = f"{m['median_e2e']:.2f}" if m['median_e2e'] != float('inf') else "N/A"
        err_str = f"{m['error_rate']:.1%}"
        tps_str = f"{m['tps']:.2f}"
        lines.append(f"| {m['n']} | {ttft_str} | {e2e_str} | {err_str} | {tps_str} |")
        
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nThroughput report saved to {report_path}")

if __name__ == "__main__":
    asyncio.run(main())
