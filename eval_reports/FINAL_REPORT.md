# Comprehensive Hotel Assistant Evaluation Report
**Generated:** 2026-05-07 10:02:18

## Hardware & Environment
**Processor:** AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD
**CPU Count:** 12
**Memory:** 15.31 GB
**OS:** Windows 10

### Core Dependencies
- `fastapi`: 0.109.0
- `uvicorn`: 0.27.0
- `websockets`: 16.0
- `sentence-transformers`: 5.4.1
- `faiss-cpu`: 1.13.2
- `anthropic`: Not installed

## Executive Summary
| Suite | Tests Run | Pass Rate | Key Metric | Status |
|-------|-----------|-----------|------------|--------|
| Conversational Evals | N/A | N/A | N/A | ✅ PASS |
| RAG Evals | N/A | Faith: 0.750 | N/A | ✅ PASS |
| Tool Evals | 14 | N/A | N/A | ✅ PASS |
| Latency Benchmarks | 30x4 | N/A | Mixed E2E Med: 24.871s | ❌ FAIL/WARN |
| Throughput Concurrency Tests | Multi-N | N/A | N/A | ✅ PASS |

## ⚠️ Issues Found
- **Latency Benchmarks**: Flagged as having failures or warnings. See detail section below.


---

# Detailed Report: Conversational Evals


# Hotel Assistant — Conversational Evaluation Report

**Generated:** 2026-05-07  
**Endpoint:** `ws://localhost:8000/ws/chat`  
**Judge model:** `qwen2.5:3b` (Ollama)  
**Dialogues evaluated:** 10

## Summary Table

| # | Dialogue | Tool | RAG | Task Completion | Policy Adherence | Coherence | Overall |
|---|----------|:----:|:---:|:--------------:|:---------------:|:---------:|:-------:|
| 1 | Check-in Inquiry with CRM Lookup | ✅ | — | 0.35 | 0.90 | 0.45 | **0.57** |
| 2 | Room Cost Calculation | ✅ | — | 0.45 | 0.50 | 0.50 | **0.48** |
| 3 | Weather Inquiry for Hotel Location | ✅ | — | 0.15 | 0.40 | 0.50 | **0.35** |
| 4 | Room Booking via Calendar Tool | ✅ | — | 0.55 | 0.65 | 0.75 | **0.65** |
| 5 | Out-of-Scope Request Refusal | — | — | 0.08 | 0.00 | 0.00 | **0.03** |
| 6 | Guest Phone Number Update | ✅ | — | 0.85 | 1.00 | 1.00 | **0.95** |
| 7 | Multi-turn: Room Type then Price then Book | ✅ | — | 0.54 | 0.60 | 0.57 | **0.57** |
| 8 | Hotel Amenities Inquiry via RAG | — | ✅ | 0.65 | 0.55 | 1.00 | **0.73** |
| 9 | Edge Case: Empty Input | — | ✅ | 0.73 | 0.67 | 0.67 | **0.69** |
| 10 | Conflicting Guest Identity Mid-Session | ✅ | — | 0.30 | 0.67 | 0.33 | **0.43** |

> **Mean overall score across all dialogues: 0.545**

---

## Per-Dialogue Details

### 1. Check-in Inquiry with CRM Lookup

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Hello, my name is John Smith. | Your name has been updated to john smith. | 0.20 | 0.80 | 0.10 |
| 2 | My phone number is +1-555-123-4567. | Your phone number has been updated to +1-555-123-4567. | 0.50 | 1.00 | 0.80 |

**Averages →** Task Completion: `0.350` | Policy Adherence: `0.900` | Coherence: `0.450`

### 2. Room Cost Calculation

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | How much does a Deluxe room cost? | Calculate Deluxe room cost from YYYY-MM-DD to YYYY-MM-DD. | 0.20 | 0.00 | 0.00 |
| 2 | Calculate standard room cost from  2026-06-01 to 2026-06-04 | Your 3-night stay in a Standard room will cost $210.00. | 0.70 | 1.00 | 1.00 |

**Averages →** Task Completion: `0.450` | Policy Adherence: `0.500` | Coherence: `0.500`

### 3. Weather Inquiry for Hotel Location

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Tell me the weather there on 2026-05-08? | Forecast for Islamabad on 2026-05-08: clear sky, around 24.5°C with hu | 0.20 | 0.80 | 1.00 |
| 2 | Will it rain tomorrow in Lahore? | I'm sorry, I can only assist with hotel-related inquiries. Please prov | 0.10 | 0.00 | 0.00 |

**Averages →** Task Completion: `0.150` | Policy Adherence: `0.400` | Coherence: `0.500`

### 4. Room Booking via Calendar Tool

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | My name is Alice Johnson. | Your name has been updated to alice johnson. | 0.50 | 0.30 | 0.70 |
| 2 | I want to book a room for 2 nights starting from 2026-06-01. | Your booking has been added to the calendar for 2026-06-01 to 2026-06- | 0.60 | 1.00 | 0.80 |

**Averages →** Task Completion: `0.550` | Policy Adherence: `0.650` | Coherence: `0.750`

### 5. Out-of-Scope Request Refusal

- **Tool required:** False
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Tell me a joke. | I'm sorry, I can only assist with hotel-related inquiries. How may I h | 0.25 | 0.00 | 0.00 |
| 2 | What is the capital of France? | I'm sorry, I can only assist with hotel-related inquiries. | 0.00 | 0.00 | 0.00 |
| 3 | Can you book a hotel room for me instead? | I'm sorry, I can only assist with hotel-related inquiries. Would you l | 0.00 | 0.00 | 0.00 |

**Averages →** Task Completion: `0.083` | Policy Adherence: `0.000` | Coherence: `0.000`

### 6. Guest Phone Number Update

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Hi, I'm Bob Williams. | Hello Bob, it's nice to meet you. How can I assist you today? | 1.00 | 1.00 | 1.00 |
| 2 | My phone number is +44-20-7946-0123. | Your phone number has been updated to +44-20-7946-0123. | 0.70 | 1.00 | 1.00 |

**Averages →** Task Completion: `0.850` | Policy Adherence: `1.000` | Coherence: `1.000`

### 7. Multi-turn: Room Type then Price then Book

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | What room types do you have available? | We offer several room types to suit different preferences. Here they a | 0.80 | 1.00 | 1.00 |
| 2 | How much is a Suite per night? | A Suite at our hotel is priced at $300 per night. Would you like to pr | 0.80 | 1.00 | 1.00 |
| 3 | Great, I want to book a Suite from 2026-05-17 for 4 nights. | I can help with hotel policies. Please ask your question again in plai | 0.00 | 0.00 | 0.00 |
| 4 | My name is Carol Davis. | Your name has been updated to carol davis. | 0.10 | 0.00 | 0.00 |
| 5 | Confirm. | Your booking is confirmed. Thank you for choosing our hotel! | 1.00 | 1.00 | 0.85 |

**Averages →** Task Completion: `0.540` | Policy Adherence: `0.600` | Coherence: `0.570`

### 8. Hotel Amenities Inquiry via RAG

- **Tool required:** False
- **RAG required:** True

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | What amenities does the hotel offer? | The hotel offers several amenities including a restaurant serving brea | 0.30 | 0.10 | 1.00 |
| 2 | Do you have a swimming pool and gym? | Yes, we offer an outdoor swimming pool that's open daily from 07:00 to | 1.00 | 1.00 | 1.00 |

**Averages →** Task Completion: `0.650` | Policy Adherence: `0.550` | Coherence: `1.000`

### 9. Edge Case: Empty Input

- **Tool required:** False
- **RAG required:** True

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Hello. | Hello! How can I assist you today? | 1.00 | 1.00 | 1.00 |
| 2 |     | Could you please let me know your full name, check-in date, check-out  | 1.00 | 1.00 | 1.00 |
| 3 | Sorry, I meant to ask about check-in times. | Sure thing! Could you please let me know your full name, check-in date | 0.20 | 0.00 | 0.00 |

**Averages →** Task Completion: `0.733` | Policy Adherence: `0.667` | Coherence: `0.667`

### 10. Conflicting Guest Identity Mid-Session

- **Tool required:** True
- **RAG required:** False

| Turn | User Message | Response (truncated) | TC | PA | COH |
|------|-------------|----------------------|:--:|:--:|:---:|
| 1 | Hi, my name is David Lee. | Your name has been updated to david lee. | 0.20 | 0.00 | 0.00 |
| 2 | I need a Standard room from 2026-05-17 staying 1 night. | Your booking is confirmed. Thank you for choosing our hotel! | 0.50 | 1.00 | 1.00 |
| 3 | Actually, I'm Sarah Connor. | Your booking is confirmed. Thank you for choosing our hotel! | 0.20 | 1.00 | 0.00 |

**Averages →** Task Completion: `0.300` | Policy Adherence: `0.667` | Coherence: `0.333`



---

# Detailed Report: RAG Evals


# Hotel RAG Evaluation Report

**Queries evaluated:** 22  
**Retriever:** FAISS IndexFlatIP + all-MiniLM-L6-v2  
**Generator:** Ollama `qwen2.5:3b`  
**k (top-k):** 3  

## Aggregate Metrics

| Metric | Score |
|--------|------:|
| Average Precision@3  | 0.455 |
| Average Recall@3     | 0.985 |
| Average MRR               | 0.977 |
| Average Faithfulness      | 0.750 |

---

## Per-Query Metrics

> ⚠️ **AT RISK** = faithfulness < 0.6

| # | Query | P@3 | R@3 | MRR | Faithfulness | Flag |
|---|-------|:-----:|:-----:|:---:|:------------:|------|
| 01 | What time is check-out? | 0.67 | 0.67 | 1.00 | — | ✅ OK |
| 02 | Do you have a swimming pool? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 03 | What is the cancellation policy? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 04 | Is breakfast included in the room rate? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 05 | What room types are available? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 06 | Is parking available at the hotel? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 07 | Are pets allowed at the hotel? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 08 | What are the gym opening hours? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 09 | How do I connect to the hotel Wi-Fi? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 10 | Can I check in early? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 11 | Is late check-out available? | 0.67 | 1.00 | 1.00 | — | ✅ OK |
| 12 | Do you offer an airport shuttle service? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 13 | What is the smoking policy? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 14 | What are the restaurant opening hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 15 | Do you provide laundry or dry-cleaning services? | 0.33 | 1.00 | 0.50 | — | ✅ OK |
| 16 | Is room service available and what are the hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 17 | How can I book a conference room? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 18 | What are the swimming pool opening hours? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 19 | What is the policy for children staying at the hotel? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 20 | What are the quiet hours at the hotel? | 0.33 | 1.00 | 1.00 | 0.75 | ✅ OK |
| 21 | Are there minibar charges if I use it? | 0.33 | 1.00 | 1.00 | — | ✅ OK |
| 22 | What payment methods does the hotel accept? | 0.33 | 1.00 | 1.00 | — | ✅ OK |

---

## Retrieved Chunk IDs per Query

| # | Query | Retrieved IDs | Relevant IDs |
|---|-------|:-------------:|:------------:|
| 01 | What time is check-out? | 21, 22, 20 | 21, 22, 49 |
| 02 | Do you have a swimming pool? | 37, 36, 46 | 37 |
| 03 | What is the cancellation policy? | 0, 43, 19 | 0, 43 |
| 04 | Is breakfast included in the room rate? | 40, 46, 38 | 40 |
| 05 | What room types are available? | 27, 38, 35 | 27 |
| 06 | Is parking available at the hotel? | 39, 41, 46 | 39, 41 |
| 07 | Are pets allowed at the hotel? | 3, 42, 5 | 3, 42 |
| 08 | What are the gym opening hours? | 47, 36, 46 | 36, 47 |
| 09 | How do I connect to the hotel Wi-Fi? | 48, 35, 46 | 35, 48 |
| 10 | Can I check in early? | 45, 23, 20 | 23, 45 |
| 11 | Is late check-out available? | 22, 49, 45 | 22, 49 |
| 12 | Do you offer an airport shuttle service? | 44, 35, 41 | 44 |
| 13 | What is the smoking policy? | 4, 9, 14 | 4 |
| 14 | What are the restaurant opening hours? | 46, 47, 21 | 46 |
| 15 | Do you provide laundry or dry-cleaning services? | 36, 31, 9 | 31 |
| 16 | Is room service available and what are the hours? | 38, 35, 27 | 38 |
| 17 | How can I book a conference room? | 14, 27, 35 | 14 |
| 18 | What are the swimming pool opening hours? | 37, 47, 46 | 37 |
| 19 | What is the policy for children staying at the hotel? | 9, 5, 3 | 9 |
| 20 | What are the quiet hours at the hotel? | 7, 46, 6 | 7 |
| 21 | Are there minibar charges if I use it? | 31, 41, 39 | 31 |
| 22 | What payment methods does the hotel accept? | 28, 32, 29 | 28 |


---

# Detailed Report: Tool Evals


# Tool Invocation Evaluation Report

## Metrics
- **Correct Tool Rate:** 100.00%
- **Correct Args Rate:** 100.00%
- **False Positive Rate:** 0.00%

## Utterance Details
| Utterance | Expected Tool | Success | Response Snapshot |
|-----------|---------------|---------|-------------------|
| My phone number is 0300-1234567. | update_user_info | ✅ | Your phone number has been updated to 0300-1234567.... |
| Update my email to ahmed@example.com | update_user_info | ✅ | Your email address has been updated to ahmed@example.com.... |
| What is my phone number? | get_user_info | ✅ | I don't have a phone number for you.... |
| How much for a standard room from 2026-06-01 to 2026-06-04? | calculate_room_cost | ✅ | Your 3-night stay in a Standard room will cost $210.00.... |
| Cost of suite for 7 nights starting 2026-06-01 to 2026-06-08? | calculate_room_cost | ✅ | Your 7-night stay in a Suite room will cost $2100.00.... |
| Book me a standard room from 2026-06-01 to 2026-06-05 | add_booking_to_calendar | ✅ | Your booking has been added to the calendar for 2026-06-01 t... |
| I want to reserve a deluxe room starting 2026-10-10 until 2026-10-12 | add_booking_to_calendar | ✅ | Your booking has been added to the calendar for 2026-10-10 t... |
| What's the weather like in Islamabad on 2026-05-07? | get_hotel_weather | ✅ | Forecast for Islamabad on 2026-05-07: clear sky, around 23.6... |
| Will it rain tomorrow in Lahore on 2026-05-08? | get_hotel_weather | ✅ | Forecast for Islamabad on 2026-05-08: clear sky, around 24.8... |
| Hi, how are you? | None | ✅ | Hi there! How can I assist you today?... |
| What are the hotel policies? | None | ✅ | Sure, here are some of our key policies:  1. **Room Assignme... |
| Is the swimming pool open? | None | ✅ | The outdoor pool is open daily from 07:00 to 21:00. Would yo... |

## Backend Unit Test Results
| Test Name | Outcome | Duration (s) |
|-----------|---------|--------------|
| `test_create_guest` | ✅ PASSED | 0.038 |
| `test_read_guest` | ✅ PASSED | 0.031 |
| `test_update_guest` | ✅ PASSED | 0.043 |
| `test_delete_or_overwrite` | ✅ PASSED | 0.030 |
| `test_crm_with_invalid_id` | ✅ PASSED | 0.001 |
| `test_single_room_cost` | ✅ PASSED | 0.005 |
| `test_suite_cost` | ✅ PASSED | 0.001 |
| `test_invalid_room_type` | ✅ PASSED | 0.001 |
| `test_zero_nights` | ✅ PASSED | 0.001 |
| `test_create_booking` | ✅ PASSED | 0.034 |
| `test_booking_content` | ✅ PASSED | 0.039 |
| `test_duplicate_booking` | ✅ PASSED | 0.047 |
| `test_weather_valid_location` | ✅ PASSED | 2.274 |
| `test_weather_invalid_location` | ✅ PASSED | 1.072 |



---

# Detailed Report: Latency Benchmarks


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


---

# Detailed Report: Throughput Concurrency Tests


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