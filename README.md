
# Hotel-Front-desk-Virtual-Assistant-with-Voice

A domain-restricted, conversational AI system for hotel front-desk operations.  
Guests interact through a real-time chat interface powered by a locally running LLM (Qwen 2.5-3B via Ollama), now with **voice support** (Moonshine ASR for speech-to-text, Piper TTS for text-to-speech).

---

## Table of Contents

1. [Architecture Diagram](#architecture-diagram)
2. [System Overview](#system-overview)
3. [Core Data Flow](#core-data-flow)
4. [Key Components](#key-components)
5. [Setup Instructions](#setup-instructions)
6. [Model Selection](#model-selection)
7. [Tool System](#tool-system)
8. [RAG & Knowledge Base](#rag--knowledge-base)
9. [CRM & Guest Personalization](#crm--guest-personalization)
10. [Performance Benchmarks](#performance-benchmarks)
11. [Running the Benchmark Tests](#running-the-benchmark-tests)
12. [Known Limitations](#known-limitations)
13. [Voice Features & Troubleshooting](#voice-features--troubleshooting)

---

## Architecture Diagram

<img width="923" height="181" alt="image" src="https://github.com/user-attachments/assets/b9897937-f12c-49c4-b579-e28e764becd1" />




## System Overview

The Hotel-Front-desk-Virtual-Assistant-with-Voice is a **fully local, domain-restricted conversational AI system** for hotel front-desk operations. It combines:
- **Speech Recognition**: Moonshine ASR for audio-to-text (runs locally, no cloud dependencies)
- **Language Model**: Qwen 2.5-3B via Ollama for domain-restricted responses
- **Retrieval-Augmented Generation**: FAISS vector store + sentence-transformers for hotel knowledge lookup
- **Tool Execution**: Automated booking, calendar, weather, CRM, and cost calculator integrations
- **Text-to-Speech**: Piper TTS for voice responses
- **Session Persistence**: In-memory + SQLite storage for multi-turn conversations and guest profiles

All components run **100% locally** with no external API dependencies (except optional OpenWeather API for weather forecasts).

---

## Core Data Flow

### Single Turn (Text Input)

```
User submits text message
  │
  ▼
Backend Input Validation (Pydantic + Custom Checks)
  ├─ Check session exists (create if needed)
  ├─ Validate message length, format
  └─ Check domain guardrail (hotel-related?)
      └─ If not: Return immediate refusal
  │
  ▼
Retrieval-Augmented Generation (RAG)
  ├─ Embed user query with sentence-transformers (384-dim vectors)
  ├─ Search FAISS vector index for top-2 hotel knowledge chunks
  ├─ Chunks cached (LRU cache, max 128 entries) to avoid re-embedding
  └─ Retrieve chunks truncated to 300 characters max
  │
  ▼
Memory Retrieval
  ├─ Get full conversation history for session
  ├─ Filter to last 6 turns (12 messages) to fit token budget
  ├─ Auto-extract booking slots (dates, room type, guest name, count)
  └─ Extract guest email/phone for CRM (if present)
  │
  ▼
Prompt Assembly (prompt_builder.py)
  ├─ System prompt + domain guardrails
  ├─ Inject RAG chunks as "RETRIEVED HOTEL KNOWLEDGE" section
  ├─ Add conversation banner (NEW vs. IN PROGRESS)
  ├─ Append filtered history + current user message
  ├─ Inject CRM context if repeat guest (name, preferences, past interactions)
  └─ Inject tool schemas (JSON) for model to use if needed
  │
  ▼
LLM Inference (Ollama + Qwen 2.5-3B)
  ├─ Stream tokens incrementally to frontend
  ├─ Settings: temp=0.35, num_predict=90 (concise responses)
  └─ Timeout: 300s (CPU-only inference)
  │
  ▼
Tool Execution (Tool Orchestrator)
  ├─ Parse streamed response for tool calls (JSON regex extraction)
  ├─ Validate tool is appropriate for user context
  ├─ Route to correct tool handler:
  │  ├─ calculator.py → Room cost calculation
  │  ├─ calendar_tool.py → Add booking to .ics file
  │  ├─ weather.py → OpenWeather API (cached 10 min)
  │  ├─ crm.py → Get/store/update guest profile
  │  └─ (More tools can be added)
  └─ Replace JSON output with human-friendly narration
  │
  ▼
Memory Persistence
  ├─ Store user message in session history (in-memory)
  ├─ Store assistant response in session history
  ├─ Update CRM with extracted guest info (SQLite)
  └─ Append interaction to CRM history log
  │
  ▼
WebSocket Response
  ├─ Stream tokens to frontend with ~12ms word-by-word delay
  └─ Return final response + session metadata

```

### Voice Input (ASR → LLM → TTS)

```
User clicks "Record" → speaks
  │
  ▼
Browser captures audio (MediaRecorder API) → WebM/Opus format
  │
  ▼
Frontend sends binary audio to /ws/voice_chat WebSocket
  │
  ▼
Backend AudioConverter (audio_pipeline.py)
  ├─ FFmpeg: Convert WebM/Opus → WAV 16kHz mono PCM
  ├─ Non-blocking (thread pool executor)
  └─ Throw error if ffmpeg not installed
  │
  ▼
Moonshine ASR (audio_pipeline.py)
  ├─ Load model from HuggingFace (lazy init)
  ├─ Thread-safe (max 4 concurrent transcriptions)
  ├─ Transcribe WAV → text transcript
  └─ Return as user message
  │
  ▼
(Standard LLM pipeline above, same as text)
  │
  ▼
Piper TTS (audio_pipeline.py)
  ├─ Load .onnx model from $PIPER_MODEL_PATH
  ├─ Synthesize response text → audio WAV
  ├─ Split into 24KB base64-encoded chunks
  └─ Stream over WebSocket with sequence numbers
  │
  ▼
Frontend Audio Playback
  ├─ Buffer incoming chunks (handle out-of-order arrival)
  ├─ Queue chunks by sequence number
  ├─ Play continuously as chunks arrive
  └─ Show "playing" indicator
```

---


## Installation

### Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Python | 3.8+ | Backend runtime |
| Node.js | 16+ | Frontend build tool (Vite) |
| Ollama | Latest | Local LLM host |
| ffmpeg | Latest | Audio processing |
| Piper TTS | .onnx model | Local text-to-speech |

---

### 1. Install Ollama

- Download and install from [https://ollama.com](https://ollama.com)
- Verify it is running:
  ```bash
  ollama list
  ```

### 2. Create the custom model

- From the project root (where `Modelfile` lives):
  ```bash
  ollama create hotel-qwen -f Modelfile
  ollama list  # Should show: hotel-qwen
  ```

### 3. Backend Setup

- Install Python dependencies:
  ```bash
  cd backend
  pip install -r requirements.txt
  ```
- (Optional, for voice) Set Piper TTS model path (Windows example):
  ```powershell
  $env:PIPER_MODEL_PATH = "C:\\models\\en_US-lessac-medium.onnx"
  ```

### 4. Frontend Setup

- Install Node.js dependencies:
  ```bash
  cd frontend
  npm install
  ```

### 5. Additional Tools

- Ensure ffmpeg is installed and available in your PATH.
- Download a Piper TTS .onnx model and set the environment variable as above.

---

## Usage

### Start Backend
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Verify:
- REST health: [http://localhost:8000/health](http://localhost:8000/health)
- WebSocket endpoint: `ws://localhost:8000/ws/chat`
- Voice WebSocket endpoint: `ws://localhost:8000/ws/voice_chat`

### Start Frontend
```bash
cd frontend
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser. You should see a green **Connected** status badge and voice controls (Record/Upload Audio).

### (Optional) CLI testing
```bash
# From project root
python main.py
```
This runs a terminal-based conversation loop against the same backend modules — useful for model/prompt debugging without starting the web stack.

### Docker (alternative)
```bash
cd backend
docker-compose up --build
```
See [backend/DOCKER_README.md](backend/DOCKER_README.md) for details.

---

## Model Selection

### Why Qwen 2.5-3B?

| Consideration | Detail |
|---------------|--------|
| **Size** | 3 billion parameters — runnable on a mid-range laptop CPU with 8 GB RAM |
| **Language quality** | Strong instruction-following with coherent multi-turn dialogue |
| **Latency** | 1–5 s per response on CPU after the model is loaded (GPU is faster) |
| **Domain restriction** | Responds well to a hard system-prompt boundary; refuses off-topic queries reliably |
| **Local / offline** | No API keys, no data sent to the cloud — suitable for assignment/demo use |

### Alternatives considered

| Model | Parameters | Trade-off |
|-------|-----------|-----------|
| `llama3.2:1b` | 1B | Faster but weaker instruction-following |
| `mistral:7b` | 7B | Better quality, but requires ≥16 GB RAM |
| `qwen2.5:7b` | 7B | Better quality, higher hardware requirement |
| OpenAI GPT-4o | — | Best quality, but requires internet & paid API key |

`qwen2.5:3b` is the best balance of **quality, speed, and hardware accessibility** for a course assignment running on commodity hardware.

### Modelfile parameters explained

```
FROM qwen2.5:3b        # base checkpoint

PARAMETER num_ctx      1300   # max tokens in context window
PARAMETER num_predict   90   # max new tokens per response (keeps answers concise)
PARAMETER temperature   0.35   # higher = more varied, lower = more deterministic
PARAMETER top_p         0.82   # nucleus sampling threshold
PARAMETER num_thread      0   # 0 = use all available CPU threads
```

---

## Tool System

The backend includes an automated **Tool Orchestrator** that detects hotel-related intents and executes appropriate tools.

### Available Tools

#### 1. Room Cost Calculator
**Triggered when:** Message contains date + room type + cost keywords  
**Function:** `tools/calculator.py::calculate_room_cost()`
- Inputs: room_type ("Standard", "Deluxe", "Suite"), check-in/out dates, guest count
- Pricing: Standard=$70, Deluxe=$150, Suite=$300 per night
- Logic: Base = price × nights; Add 15% surcharge if Suite + 3+ guests
- Output: JSON with cost breakdown

#### 2. Booking Calendar
**Triggered when:** Message has booking keywords + dates  
**Function:** `tools/calendar_tool.py::add_booking_to_calendar()`
- Creates .ics iCalendar file per booking (compatible with Outlook/Google Calendar)
- Persists booking record in `/calendars/bookings.json` (survives backend restart)
- Stores: event_id (UUID), guest_name, check-in/out dates, room_type

#### 3. Hotel Weather Forecast
**Triggered when:** Message has weather keywords + optional dates  
**Function:** `tools/weather.py::get_hotel_weather()`
- Calls OpenWeather API (requires `$OPENWEATHER_API_KEY`)
- Results cached 10 minutes to avoid redundant API calls
- Returns guest-friendly summary (e.g., "Clear skies, great for outdoor activities")
- Default location: Islamabad

#### 4. CRM (Guest Profiles)
**Triggered when:** Message asks about guest info or new booking  
**Function:** `tools/crm.py` (SQLite-backed)
- Stores: user_id, name, email, phone, preferences (JSON), interaction_history (list)
- Methods: `get_user_info()`, `store_user_info()`, `update_user_info()`, `append_interaction()`
- Auto-extracts: Emails, phone numbers, names from user messages (regex)
- Persists to `/data/crm.db` across backend restarts
- Repeat guests get personalized system prompt injection

### Tool Execution Flow

1. **Intent Detection**: `ToolOrchestrator.infer_relevant_tools()` scans message for keywords
2. **Model Generation**: LLM streams response with embedded JSON tool calls
3. **Parsing**: `ToolOrchestrator.execute_tool_calls()` extracts JSON from streamed text (regex with nested brace handling)
4. **Execution**: Routes to correct tool handler
5. **Narration**: Replaces raw JSON output with human-friendly summary (e.g., "Your booking has been added to calendar. Download: path/to/file.ics")

Tools are **automatically discovered and executed** without explicit user prompting — the system infers intent from conversation context.

---

## RAG & Knowledge Base

The system includes **Retrieval-Augmented Generation** to ground responses in hotel policies and procedures.

### Knowledge Base

**50 Auto-Generated Hotel Documents** covering:
- **Hotel Policies** (10): Cancellation, no-show, refund, pet, smoking, conduct, visitor, noise, damage, children
- **Booking Rules** (10): Reservation process, modifications, peak season, early booking, group rates, terms, waitlist, promotions, packages, payment
- **Check-in/Out** (8): Early check-in, late checkout, express check-in, bell desk, baggage, key card, room assignment, payment
- **Payment Rules** (7): Methods, currency, taxes, deposits, late fees, refunds
- **Amenities** (5): Pool/fitness, restaurant, WiFi, business center, parking
- **FAQs** (10): General, emergencies, local area, complaints, feedback

### RAG Pipeline

1. **Chunking**: Documents split into 500-character chunks with 80-character overlap (preserves context at boundaries)
2. **Embedding**: Chunks embedded with `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional vectors)
3. **Indexing**: FAISS IndexFlatIP stores embeddings; supports fast cosine similarity search
4. **Persistence**: Index saved to `/data/index/` (faiss.index, chunks.json, metadata.json)
5. **Caching**: Query results cached in LRU cache (128 entries, keyed by query hash + top_k)

### Retrieval

**`retriever.py::retrieve(query, top_k=2)`**
- Embeds user query (first embedding load: ~500ms; cached after)
- Searches FAISS index for top-2 most similar chunks
- Truncates chunks to 300 characters max
- Returns {chunk_text, doc_id, similarity_score}

**Caching Benefits:**
- Repeated queries ("What's your cancellation policy?") return instantly from cache
- Max 128 cached queries per session
- Lookup: O(1)

### Prompt Integration

RAG chunks injected into `system_prompt` as:
```
RETRIEVED HOTEL KNOWLEDGE:
---
[Chunk 1]: {text}
[Chunk 2]: {text}
---
Refer to the knowledge above first for policies and procedures.
```

---

## CRM & Guest Personalization

The system includes a **Customer Relationship Management** system to track guests, preferences, and booking history.

### Guest Profile Storage

**Database**: SQLite at `/data/crm.db`

**Schema:**
```sql
users(
  user_id TEXT PRIMARY KEY,
  name TEXT,
  email TEXT,
  phone TEXT,
  preferences TEXT,        -- JSON: {room_preference, dietary, accessibility, etc.}
  interaction_history TEXT, -- JSON array: [turn1_text, turn2_text, ...]
  created_at TEXT,         -- ISO 8601 timestamp
  updated_at TEXT          -- ISO 8601 timestamp
)
```

### Auto-Capture Features

**Booking Slot Extraction** (`memory_manager.py`)
- Automatically scans user messages for:
  - Guest name (regex: proper nouns, "I'm", "My name is")
  - Arrival/checkout dates (regex: date patterns)
  - Guest count (numbers, "for 2 people", etc.)
  - Room preference ("deluxe", "suite", "standard")
  - Special requests (regex: "I need", "I would like", etc.)
- Persists in `_session_booking_slots` dict per session
- Available for tool execution without explicit form submission

**Email/Phone/Name Extraction** (`routes.py`)
- Regex patterns extract emails, phone numbers, names from any user utterance
- Auto-updates CRM asynchronously (doesn't block response)
- Enables repeat-guest personalization on next visit

### CRM Methods

| Method | Purpose |
|--------|----------|
| `get_user_info(user_id)` | Fetch guest profile |
| `store_user_info(user_id, ...)` | Create new profile |
| `update_user_info(user_id, field, value)` | Update single field |
| `append_interaction(user_id, text)` | Add message to interaction history |
| `get_system_prompt_with_context(user_id, base_prompt)` | Inject CRM data into system prompt |

### Repeat Guest Personalization

When returning guest is detected (by user_id):
1. Fetch profile from CRM
2. Extract past preferences and interaction highlights
3. Inject into system prompt as context
4. Model responds with awareness of guest history

Example:
```
SYSTEM PROMPT:
[...domain restrictions...]

GUEST CONTEXT:
This is a returning guest: John Smith
Past preferences: Prefers Deluxe rooms, early check-in, no housekeeping on Sundays
Past interactions: Requested breakfast recommendations, inquired about spa services
Last visit: April 15-18 (3 days)
```

---

## Performance Benchmarks

The following results were measured on a **mid-range laptop (CPU-only inference)** running the full stack locally.

### Latency (5 sequential requests, single session)

| Metric | Value |
|--------|-------|
| Requests sent | 5 |
| Successes | 4 |
| Failures | 1 (cold-start timeout) |
| Min latency | 15 160 ms |
| Max latency | 64 172 ms |
| Mean latency | 27 931 ms |
| Std deviation | 20 375 ms |

> The first request timed out because Ollama was loading the model weights into RAM — this is a **one-time cold-start cost**. Requests 2–5 succeeded in 15–20 s each, which is typical for CPU-only qwen2.5:3b inference.

### Stress test (concurrent users)

| Concurrent users | Successes | Failures | Mean latency | Max latency | Min latency |
|-----------------|----------|---------|-------------|------------|------------|
| 2  | 2  | 0 | 14 207 ms | 18 028 ms | 10 387 ms |
| 4  | 4  | 0 | 21 582 ms | 35 156 ms |  8 657 ms |
| 6  | 6  | 0 | 33 238 ms | 55 611 ms |  9 587 ms |
| 8  | 8  | 0 | 36 834 ms | 66 883 ms |  8 128 ms |
| 10 | 10 | 0 | 48 568 ms | 89 120 ms |  8 617 ms |

> The system handled all 10 concurrent requests without a single failure. Mean latency grows linearly with concurrency — expected because Ollama serialises requests behind a single CPU inference thread. No crashes or dropped connections were observed at any level.

### Failure handling

| Edge case | Expected HTTP | Actual HTTP | Result |
|-----------|--------------|------------|--------|
| Empty message string | 422 | 422 | ✔ Pass |
| Whitespace-only message | 400 | 400 | ✔ Pass |
| Missing `message` field | 422 | 422 | ✔ Pass |
| Missing `session_id` field | 422 | 422 | ✔ Pass |
| Empty `session_id` | 422 | 400 | ✘ Minor mismatch — custom validator fires before Pydantic |
| Oversized message (10 001 chars) | 200 | 200 | ✔ Pass |
| SQL injection in message | 200 | 200 | ✔ Treated as plain text |
| JSON injection in `session_id` | 200 | 200 | ✔ Stored as plain string |
| GET on non-existent route | 404 | 404 | ✔ Pass |
| GET /health | 200 | 200 | ✔ Pass |
| GET /api/chat (wrong method) | 405 | 405 | ✔ Pass |
| Malformed JSON body | 422 | 422 | ✔ Pass |

> 11 of 12 tests passed. The one mismatch (empty `session_id` returning 400 instead of 422) is a minor ordering difference between the custom validator and Pydantic — the request is still correctly rejected.

---

## Running the Benchmark Tests

A self-contained test script is provided at [tests/benchmark_tests.py](tests/benchmark_tests.py).

### Install test dependencies

```bash
pip install requests httpx
```

### Run all three suites

```bash
# Backend must be running first
python tests/benchmark_tests.py
```

### Run individual suites

```bash
# Latency only (10 sequential messages)
python tests/benchmark_tests.py --latency --requests 10

# Stress test only (ramp to 20 concurrent users, step 4)
python tests/benchmark_tests.py --stress --max-users 20 --step 4

# Failure-handling only
python tests/benchmark_tests.py --failure
```

### What each suite measures

#### 1 · Latency Benchmarking
Sends `--requests` sequential messages to `/api/chat` using a single session  
and reports **min / max / mean / std-dev** response time in milliseconds.

```
  Metric                    Value
  ──────────────────────────────────
  Requests sent                 5
  Successes                     5
  Failures                      0
  Min latency (ms)           1823
  Max latency (ms)           4201
  Mean latency (ms)          2640
  Std dev (ms)                901
```

#### 2 · Stress Testing
Fires `N` simultaneous async requests at each concurrency level and prints  
a table of success count, failure count, mean/max/min latency.

```
  Users    Success    Fail   Mean(ms)     Max(ms)    Min(ms)
  ────────────────────────────────────────────────────────────
  2        ✔ 2        0      3012         3891       2133
  4        ✔ 4        0      6890         9203       4411
  6        ⚠ 5        1      13204        18902      5021
  10       ✘ 8        2      25103        42011      6301
```

#### 3 · Failure Handling
Sends 12 intentionally malformed requests and checks each returns the  
expected HTTP status code, verifying the API is hardened against bad input.

```
  Empty message string                          HTTP 422 (expected 422)  ✔
  Whitespace-only message                       HTTP 400 (expected 400)  ✔
  Missing 'message' field                       HTTP 422 (expected 422)  ✔
  ...
  Result: 12/12 failure-handling tests passed.
```

---



## Known Limitations

1. **Single-threaded LLM inference:** Ollama runs one request at a time on CPU. All concurrent requests queue behind each other, causing latency to grow linearly with the number of simultaneous users. Typical response time: 15–30 seconds per turn on mid-range CPU.

2. **In-memory conversation history:** Session conversation history is stored in process memory and is lost when the backend restarts. **However**: Guest CRM profiles and booking calendar records persist in SQLite, so returning guests' info is preserved.

3. **Domain restriction is prompt-only:** The hotel-only restriction is enforced through the system prompt + regex guardrail. A sophisticated prompt injection could theoretically bypass it; there is no secondary classifier or LLM-based safety module.

4. **RAG knowledge is static:** The 50 hotel documents are generated once at startup. Real-time policy updates require restarting the backend to re-index.

5. **No multi-language support:** System prompt and tools assume English input/output. Non-English queries may be rejected or produce low-quality responses.

6. **Moonshine ASR accuracy:** Moonshine is lightweight but less accurate than commercial ASR (Whisper, Google Cloud Speech). Accented speech or background noise may reduce transcription quality.

7. **No persistent vector cache:** FAISS index is loaded into memory at startup. Very large hotel document sets (1000+ docs) could exceed memory; a persistent vector database (Pinecone, Weaviate) would scale better.

---

## Voice Features & Troubleshooting

### Voice Setup (Fully Local, No API Services)

The backend runs Moonshine ASR and Piper TTS locally. **No external cloud APIs or microservices are needed.**

#### Prerequisites

1. **FFmpeg** (required for audio conversion)
   ```bash
   # Windows: Download from https://ffmpeg.org or use chocolatey
   choco install ffmpeg
   
   # macOS
   brew install ffmpeg
   
   # Linux (Ubuntu/Debian)
   sudo apt-get install ffmpeg
   ```

2. **Piper TTS Model** (.onnx file)
   - Download from [Piper releases](https://github.com/rhasspy/piper/releases)
   - Save to a local directory (e.g., `C:\models\en_US-lessac-medium.onnx`)
   - Set environment variable (see below)

#### Installation

**Install backend dependencies (including Moonshine/Piper):**

```bash
cd backend
pip install -r requirements.txt
```

**Set Piper environment variable:**

*Windows (PowerShell):*
```powershell
$env:PIPER_MODEL_PATH = "C:\models\en_US-lessac-medium.onnx"
```

*macOS/Linux (Bash):*
```bash
export PIPER_MODEL_PATH="/path/to/en_US-lessac-medium.onnx"
```

**Verify setup:**
```bash
# Test Moonshine loads
python -c "from moonshine_speech import transcriber; print('Moonshine OK')"

# Test Piper loads
python -c "from piper import PiperTTS; print('Piper OK')"
```

#### Voice Test Flow

1. Click **Record** button, speak clearly, then click **Stop**.
2. Browser captures audio (MediaRecorder) → sends to backend as WebM
3. Backend converts WebM → WAV 16kHz via FFmpeg
4. Moonshine ASR transcribes WAV → text
5. LLM generates response (same as text pipeline)
6. Piper TTS synthesizes response → audio WAV chunks
7. Audio streams back to browser in 24KB base64-encoded chunks
8. Frontend buffers and plays audio with sequence-number ordering
9. Use **Upload Audio** to test with .wav/.mp3 files (browser converts to WebM)

#### Audio Details

- **Input format:** Browser captures audio as WebM/Opus (automatic from MediaRecorder)
- **Conversion:** FFmpeg converts to 16kHz mono WAV (Moonshine requirement)
- **Processing:** Non-blocking (thread pool executor to avoid blocking async event loop)
- **Output format:** Piper synthesizes WAV → 24KB chunks → base64-encoded JSON over WebSocket
- **Playback:** Frontend queues chunks by sequence number, plays continuously

### Troubleshooting

**"Not Connected" Error:**
- Wait 2-3 seconds after page load
- Refresh the page
- Check backend is running: http://localhost:8000/health
- Check browser console (F12) for errors

**"Connection Lost" Error:**
- Click the **Reconnect** button
- Check if backend is still running
- Restart the backend server if needed

**No Response from Assistant:**
- Check Ollama is running: `ollama list`
- Check backend logs for errors about Ollama connection
- Test Ollama directly: `ollama run hotel-qwen "Hello, how are you?"`
- First response is slow (model loading)
- Check backend terminal for errors

**Slow First Response:**
- This is normal! The first message loads the model into memory (10-30 seconds). Subsequent messages are fast (1-3 seconds).

**Port Already in Use:**
- Free port 8000 or 3000 using `netstat` and `taskkill` (Windows) or `lsof` (Linux/Mac)

### Status Indicators

- 🟢 **Green dot + "Connected"** = All good!
- 🔴 **Red dot + "Disconnected"** = Backend not reachable
- **Typing...** = Assistant is generating response
- **Blinking cursor (▊)** = Response streaming in real-time
- **Timestamp** = Message completed

---

## Evaluation Suite

The evaluation suite comprehensively measures the quality, accuracy, latency, and scalability of the virtual assistant using rigorous automated benchmarks.

### Setup Steps
1. Ensure the backend server is running: `python -m uvicorn main:app --host 0.0.0.0 --port 8000`
2. Ensure Ollama is running locally with the target models (e.g., `qwen2.5:3b`).
3. Ensure required API keys (e.g., `OPENWEATHER_API_KEY`) are exported in your environment.
4. Install all dependencies: `pip install pytest pytest-asyncio websockets httpx faiss-cpu sentence-transformers langchain-community`

### How to Run
We provide a master evaluation runner that sequentially executes all suites and aggregates the results into a single report.

```bash
# Run all tests (Warning: Concurrency tests may be slow)
python run_evals.py

# Run all tests but skip the slow throughput concurrency tests
python run_evals.py --skip-throughput
```

### What Each Metric Means
The `FINAL_REPORT.md` will compile the following metrics:

1. **Conversational Evals (Task Completion, Policy Adherence, Coherence)**
   - Measured by a Judge LLM (Ollama). 
   - **Good:** > 0.85 indicates the assistant reliably answers questions, follows guidelines, and sounds natural.
   
2. **RAG Evals (MRR, Precision@3, Faithfulness)**
   - Evaluates the vector DB retrieval quality.
   - **Good:** MRR > 0.8 means the correct hotel policy chunk is almost always returned first. Faithfulness > 0.8 means the assistant doesn't hallucinate.

3. **Tool Evals (Correct Tool Rate, Correct Args Rate)**
   - Evaluates if the LLM correctly parses the user's intent to trigger CRM/Calendar/Calculator tools.
   - **Good:** 100% correct tool execution ensures zero false-positive tool calls (no mistaken database entries).

4. **Latency Benchmarks (TTFT, End-to-End Latency)**
   - **TTFT (Time To First Token):** The time between the user speaking/typing and the AI starting its response.
   - **End-to-End Latency:** The time until the entire response finishes generating.
   - **Good:** `TTFT < 6s` is excellent for a front-desk scenario where guests expect near-instant replies. Slower times indicate the LLM or GPU/CPU is overwhelmed.

5. **Throughput / Concurrency Evals (Max Sustainable Concurrency)**
   - Pushes N parallel sessions against the WebSocket server.
   - **Good:** Being able to handle 10+ concurrent sessions with `< 15% error rate` and `TTFT < 15s` means your local server is robust enough for typical hotel lobby traffic. A sharp degradation in latency marks the hardware breakpoint.

**Video Demo:** https://www.loom.com/share/fb3e8f64d1f84ce59773214dac1bc98a
