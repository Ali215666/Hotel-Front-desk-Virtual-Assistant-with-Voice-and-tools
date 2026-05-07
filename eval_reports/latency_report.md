# WebSocket Latency & Performance Report

## Hardware Setup
- **Processor:** AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD
- **CPU Count:** 12
- **Total Memory:** 15.31 GB

## Scenarios Evaluated
- Trials per scenario: 30

## Metrics Summary
| Scenario | Metric | Mean | Median | P90 | P99 | Status |
|----------|--------|------|--------|-----|-----|--------|
| simple | TTFT (s) | 10.377 | 9.947 | 11.076 | 16.589 | ✅ PASS |
| simple | Inter-Token (ms) | 151.281 | 150.534 | 165.256 | 179.666 | ✅ PASS |
| simple | End-to-End (s) | 13.572 | 12.978 | 14.912 | 21.985 | ✅ PASS |
| rag_only | TTFT (s) | 13.223 | 9.336 | 10.732 | 65.292 | ✅ PASS |
| rag_only | Inter-Token (ms) | 156.412 | 150.789 | 189.954 | 242.073 | ✅ PASS |
| rag_only | End-to-End (s) | 23.587 | 19.476 | 25.136 | 76.618 | ✅ PASS |
| tool_only | TTFT (s) | 0.154 | 0.059 | 0.070 | 2.054 | ✅ PASS |
| tool_only | Inter-Token (ms) | 0.000 | 0.000 | 0.000 | 0.000 | ✅ PASS |
| tool_only | End-to-End (s) | 0.154 | 0.060 | 0.070 | 2.054 | ✅ PASS |
| mixed | TTFT (s) | 13.001 | 12.101 | 13.565 | 43.086 | ❌ FAILING threshold |
| mixed | Inter-Token (ms) | 120.196 | 143.496 | 165.187 | 177.404 | ✅ PASS |
| mixed | End-to-End (s) | 23.449 | 24.871 | 27.643 | 56.410 | ❌ FAILING threshold |