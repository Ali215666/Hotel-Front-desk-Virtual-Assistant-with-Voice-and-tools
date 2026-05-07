# WebSocket Concurrency & Throughput Report

## Key Findings
- **Max Sustainable Concurrency:** `2 users` (Median TTFT < 15s & Error < 15%)
- **Degradation Breakpoint:** `2 users` (TTFT spikes > 50%)

## Concurrency vs Latency
| Concurrent Users (N) | Median TTFT (s) | Median E2E (s) | Error Rate | Turns / Sec |
|----------------------|-----------------|----------------|------------|-------------|
| 1 | 4.93 | 10.43 | 0.0% | 0.09 |
| 2 | 8.35 | 10.65 | 0.0% | 0.11 |
| 5 | 16.84 | 19.11 | 33.3% | 0.06 |
| 10 | 19.83 | 22.19 | 33.3% | 0.05 |
| 15 | N/A | N/A | 33.3% | 0.00 |
| 20 | N/A | N/A | 33.3% | 0.00 |