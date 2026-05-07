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
