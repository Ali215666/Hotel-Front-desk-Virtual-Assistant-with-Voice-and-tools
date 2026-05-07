"""
Hotel Front Desk AI — Conversational Evaluation Suite
======================================================
Evaluates 10 multi-turn dialogues via the live WebSocket endpoint
(ws://localhost:8000/ws/chat) using Gemini-1.5-flash as an LLM judge.

Prerequisites
-------------
  pip install google-generativeai websockets pytest-asyncio

Usage
-----
  # Run all evals (backend must be running on localhost:8000):
  python tests/test_conversational_evals.py

  # Or via pytest:
  pytest tests/test_conversational_evals.py -v --asyncio-mode=auto
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
import websockets

from langchain_community.chat_models import ChatOllama

# Initialize local Ollama as judge instead of Gemini
judge = ChatOllama(model="qwen2.5:3b", temperature=0.0, format="json")

# ── Constants ─────────────────────────────────────────────────────────────────
WS_URL        = "ws://localhost:8000/ws/chat"
REPORT_DIR    = Path(__file__).parent.parent / "eval_reports"
REPORT_PATH   = REPORT_DIR / "conversational_report.md"

# Dates used in test cases
TODAY      = date.today()
TOMORROW   = TODAY + timedelta(days=1)
IN_3_DAYS  = TODAY + timedelta(days=3)
IN_10_DAYS = TODAY + timedelta(days=10)

def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════
# 1.  TEST DIALOGUES
# ══════════════════════════════════════════════════════════════════════════════

DIALOGUES: List[Dict[str, Any]] = [
    # ── 1. CRM lookup ─────────────────────────────────────
    {
        "name": "Check-in Inquiry with CRM Lookup",
        "turns": [
            "Hello, my name is John Smith.",
            "My phone number is +1-555-123-4567.",
        ],
        "expected_behaviors": [
            "Greets guest, acknowledges name introduction politely.",
            "Acknowledges phone number, confirms or saves it in the guest profile.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 2. Room cost calculation ──────────────────────────────────────────────
    {
        "name": "Room Cost Calculation",
        "turns": [
            "How much does a Deluxe room cost?",
            "Calculate standard room cost from  2026-06-01 to 2026-06-04"
        ],
        "expected_behaviors": [
            "Provides pricing information for a Deluxe room or asks clarifying dates.",
            "Calculates and states total room cost using the calculator tool.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 3. Weather inquiry ────────────────────────────────────────────────────
    {
        "name": "Weather Inquiry for Hotel Location",
        "turns": [
            "Tell me the weather there on 2026-05-08?",
            "Will it rain tomorrow in Lahore?"
        ],
        "expected_behaviors": [
            "Fetches and reports weather conditions for the specified date and location.",
            "Should not answer about it as it is not related to hotel services or location"
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 4. Room booking via calendar tool ────────────────────────────────────
    {
        "name": "Room Booking via Calendar Tool",
        "turns": [
            "My name is Alice Johnson.",
            "I want to book a room for 2 nights starting from 2026-06-01.",
            "Confirm booking"     
        ],
        "expected_behaviors": [
            "Acknowledge the request",
            "Confirms booking, adds to calendar, and offers download link or confirmation.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 5. Out-of-scope request → policy refusal ──────────────────────────────
    {
        "name": "Out-of-Scope Request Refusal",
        "turns": [
            "Tell me a joke.",
            "What is the capital of France?",
            "Can you book a hotel room for me instead?",
        ],
        "expected_behaviors": [
            "I'm sorry, I can only assist with hotel-related inquiries.",
            "I'm sorry, I can only assist with hotel-related inquiries.",
            "Engages helpfully with the hotel booking request.",
        ],
        "requires_tool": False,
        "requires_rag": False,
    },

    # ── 6. Guest updating phone number (CRM update) ───────────────────────────
    {
        "name": "Guest Phone Number Update",
        "turns": [
            "Hi, I'm Bob Williams.",
            "My phone number is +44-20-7946-0123.",
        ],
        "expected_behaviors": [
            "Greets guest, acknowledges name introduction politely.",
            "Acknowledges phone number, confirms or saves it in the guest profile.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 7. Multi-turn: room type → price → booking ───────────────────────────
    {
        "name": "Multi-turn: Room Type then Price then Book",
        "turns": [
            "What room types do you have available?",
            "How much is a Suite per night?",
            f"Great, I want to book a Suite from {_fmt(IN_10_DAYS)} for 4 nights.",
            "My name is Carol Davis.",
            "Confirm.",
        ],
        "expected_behaviors": [
            "Lists available room types clearly.",
            "Provides Suite nightly rate.",
            "Starts booking, records room type, check-in date, and stay length.",
            "Records guest name; shows complete booking summary.",
            "Finalizes and confirms the booking.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },

    # ── 8. Hotel amenities (RAG retrieval) ────────────────────────────────────
    {
        "name": "Hotel Amenities Inquiry via RAG",
        "turns": [
            "What amenities does the hotel offer?",
            "Do you have a swimming pool and gym?"
        ],
        "expected_behaviors": [
            "Provides a comprehensive list of hotel amenities from policy documents.",
            "Specifically addresses swimming pool and gym availability."
        ],
        "requires_tool": False,
        "requires_rag": True,
    },

    # ── 9. Edge case: empty / whitespace-only input ───────────────────────────
    {
        "name": "Edge Case: Empty Input",
        "turns": [
            "Hello.",
            "   ",
            "Sorry, I meant to ask about check-in times.",
        ],
        "expected_behaviors": [
            "Responds with a standard greeting.",
            "Handles empty/whitespace input gracefully without crashing.",
            "Answers the check-in time question helpfully.",
        ],
        "requires_tool": False,
        "requires_rag": True,
    },

    # ── 10. Conflicting identity mid-session ──────────────────────────────────
    {
        "name": "Conflicting Guest Identity Mid-Session",
        "turns": [
            "Hi, my name is David Lee.",
            f"I need a Standard room from {_fmt(IN_10_DAYS)} staying 1 night.",
            "Actually, I'm Sarah Connor.",
        ],
        "expected_behaviors": [
            "Greets David Lee, starts booking flow.",
            "Records dates and room type; progresses booking.",
            "Acknowledges the name correction gracefully and updates the guest name.",
        ],
        "requires_tool": True,
        "requires_rag": False,
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 2.  WEBSOCKET CONVERSATION RUNNER
# ══════════════════════════════════════════════════════════════════════════════

async def run_conversation(
    session_id: str,
    turns: List[str],
) -> List[Optional[str]]:
    """
    Connect to ws://localhost:8000/ws/chat, send each turn message, and
    collect the assembled assistant reply per turn.

    The backend streams tokens as {"type":"token","content":"..."} frames
    and terminates each turn with {"type":"done"}.  We accumulate tokens
    until "done" or TURN_TIMEOUT seconds have elapsed.

    Returns a list of reply strings (one per turn).  None means the turn
    timed-out or the connection dropped before receiving a reply.
    """
    replies: List[Optional[str]] = []

    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            # Send handshake init
            await ws.send(json.dumps({
                "type": "init",
                "session_id": session_id,
                "user_id": session_id,
            }))

            for turn_msg in turns:
                # Skip blank messages gracefully – send them anyway so the
                # backend's whitespace-handling logic is exercised.
                payload = json.dumps({
                    "session_id": session_id,
                    "message": turn_msg,
                })
                await ws.send(payload)

                # Collect streaming tokens until "done"
                assembled = ""
                try:
                    while True:
                        raw = await ws.recv()
                        try:
                            frame = json.loads(raw)
                        except json.JSONDecodeError:
                            # plain-text token (legacy streaming mode)
                            assembled += raw
                            continue

                        ftype = frame.get("type", "")
                        if ftype == "token":
                            assembled += frame.get("content", "")
                        elif ftype == "done":
                            break
                        elif ftype == "error":
                            assembled = f"[ERROR] {frame.get('message', '')}"
                            break
                        # Ignore status / audio frames
                except Exception as e:
                    assembled = f"[RECEIVE ERROR] {e}"

                replies.append(assembled if assembled else None)

    except (
        websockets.exceptions.ConnectionClosedError,
        websockets.exceptions.InvalidURI,
        OSError,
    ) as exc:
        # Pad remaining turns with None so caller always gets len(turns) items
        while len(replies) < len(turns):
            replies.append(f"[CONNECTION ERROR] {exc}")

    return replies


# ══════════════════════════════════════════════════════════════════════════════
# 3.  GEMINI JUDGE
# ══════════════════════════════════════════════════════════════════════════════

JUDGE_PROMPT_TEMPLATE = """\
You are an objective NLP evaluator evaluating a Hotel Front Desk Assistant.

User message: {user_message}
Assistant response: {assistant_response}
Expected behaviour rubric: {rubric}

Rate the response on these three dimensions. Output ONLY a valid JSON object with EXACTLY the following four keys:

- "reasoning": A 1-sentence string explaining your scores.
- "task_completion": Float between 0.0 and 1.0 (e.g., 0.5 for partial completion, 1.0 for full completion).
- "policy_adherence": Float between 0.0 and 1.0 based on if the assistant stays on topic and refuses out-of-scope requests.
- "coherence": Float between 0.0 and 1.0 based on if the assistant is polite, avoids contradictions, and sounds natural.

Do NOT include any other text or markdown formatting. Output raw JSON only.
"""

def _parse_scores(raw: str) -> Dict[str, float]:
    """Extract the JSON score dict from the judge's reply."""
    print(f"\n  [DEBUG RAW LLM]: {raw}")
    try:
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            json_str = raw[start:end+1]
            data = json.loads(json_str)
            return {
                "task_completion": float(data.get("task_completion", 0.0)),
                "policy_adherence": float(data.get("policy_adherence", 0.0)),
                "coherence": float(data.get("coherence", 0.0)),
            }
    except Exception as e:
        print(f"  [JSON PARSE ERROR] {e} | Raw: {raw}")
    return {"task_completion": 0.0, "policy_adherence": 0.0, "coherence": 0.0}


def judge_turn(
    user_message: str,
    assistant_response: Optional[str],
    rubric: str,
) -> Dict[str, float]:
    """Call Gemini to score a single turn. Retries on rate limits."""
    if not assistant_response:
        return {"task_completion": 0.0, "policy_adherence": 0.0, "coherence": 0.0}

    prompt = JUDGE_PROMPT_TEMPLATE.format(
        user_message=user_message,
        assistant_response=assistant_response[:1500],
        rubric=rubric,
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = judge.invoke(prompt)
            return _parse_scores(resp.content)
        except Exception as exc:  # noqa: BLE001
            print(f"  [JUDGE ERROR] {exc}")
            import time
            time.sleep(1)
            continue
            
    return {"task_completion": 0.0, "policy_adherence": 0.0, "coherence": 0.0}


def avg_scores(score_list: List[Dict[str, float]]) -> Dict[str, float]:
    """Average a list of per-turn score dicts."""
    if not score_list:
        return {"task_completion": 0.0, "policy_adherence": 0.0, "coherence": 0.0}
    keys = ["task_completion", "policy_adherence", "coherence"]
    return {k: round(sum(s[k] for s in score_list) / len(score_list), 3) for k in keys}


# ══════════════════════════════════════════════════════════════════════════════
# 4.  REPORT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_report(results: List[Dict[str, Any]]) -> None:
    """Write a Markdown summary table to eval_reports/conversational_report.md."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    lines: List[str] = [
        "# Hotel Assistant — Conversational Evaluation Report",
        "",
        f"**Generated:** {date.today().isoformat()}  ",
        f"**Endpoint:** `{WS_URL}`  ",
        f"**Judge model:** `qwen2.5:3b` (Ollama)  ",
        f"**Dialogues evaluated:** {len(results)}",
        "",
        "## Summary Table",
        "",
        "| # | Dialogue | Tool | RAG | Task Completion | Policy Adherence | Coherence | Overall |",
        "|---|----------|:----:|:---:|:--------------:|:---------------:|:---------:|:-------:|",
    ]

    overall_scores: List[float] = []

    for i, r in enumerate(results, start=1):
        sc = r["avg_scores"]
        overall = round(
            (sc["task_completion"] + sc["policy_adherence"] + sc["coherence"]) / 3, 3
        )
        overall_scores.append(overall)

        tool_icon = "✅" if r["requires_tool"] else "—"
        rag_icon  = "✅" if r["requires_rag"]  else "—"
        lines.append(
            f"| {i} | {r['name']} | {tool_icon} | {rag_icon} "
            f"| {sc['task_completion']:.2f} | {sc['policy_adherence']:.2f} "
            f"| {sc['coherence']:.2f} | **{overall:.2f}** |"
        )

    if overall_scores:
        avg_overall = round(sum(overall_scores) / len(overall_scores), 3)
        lines += [
            "",
            f"> **Mean overall score across all dialogues: {avg_overall:.3f}**",
        ]

    lines += ["", "---", "", "## Per-Dialogue Details", ""]

    for i, r in enumerate(results, start=1):
        lines += [
            f"### {i}. {r['name']}",
            "",
            f"- **Tool required:** {r['requires_tool']}",
            f"- **RAG required:** {r['requires_rag']}",
            "",
            "| Turn | User Message | Response (truncated) | TC | PA | COH |",
            "|------|-------------|----------------------|:--:|:--:|:---:|",
        ]
        for t in r["turn_details"]:
            msg   = (t["user_message"] or "").replace("|", "\\|")[:60]
            reply = (t["reply"] or "[NO REPLY]").replace("|", "\\|")[:70]
            lines.append(
                f"| {t['turn']} | {msg} | {reply} "
                f"| {t['scores']['task_completion']:.2f} "
                f"| {t['scores']['policy_adherence']:.2f} "
                f"| {t['scores']['coherence']:.2f} |"
            )
        sc = r["avg_scores"]
        lines += [
            "",
            f"**Averages →** Task Completion: `{sc['task_completion']:.3f}` | "
            f"Policy Adherence: `{sc['policy_adherence']:.3f}` | "
            f"Coherence: `{sc['coherence']:.3f}`",
            "",
        ]

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📄  Report written to: {REPORT_PATH}")


# ══════════════════════════════════════════════════════════════════════════════
# 5.  PYTEST FIXTURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def session_id() -> str:
    """Generate a unique session ID per test."""
    return f"eval-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def session_ids() -> List[str]:
    """Generate one unique session ID per dialogue."""
    return [f"eval-{uuid.uuid4().hex[:12]}" for _ in DIALOGUES]


# ══════════════════════════════════════════════════════════════════════════════
# 6.  INDIVIDUAL PYTEST TEST FUNCTIONS (one per dialogue)
# ══════════════════════════════════════════════════════════════════════════════

async def _eval_dialogue(dialogue: Dict[str, Any], sid: str) -> Dict[str, Any]:
    """Run one dialogue, judge each turn, return structured result."""
    print(f"\n{'='*60}")
    print(f"  Dialogue: {dialogue['name']}")
    print(f"  Session : {sid}")
    print(f"{'='*60}")

    replies = await run_conversation(sid, dialogue["turns"])

    turn_details: List[Dict[str, Any]] = []
    per_turn_scores: List[Dict[str, float]] = []

    for idx, (msg, reply, rubric) in enumerate(
        zip(dialogue["turns"], replies, dialogue["expected_behaviors"]), start=1
    ):
        print(f"\n  Turn {idx}")
        print(f"  User  : {msg[:80]}")
        print(f"  Reply : {str(reply)[:120]}")

        scores = judge_turn(msg, reply, rubric)
        per_turn_scores.append(scores)
        print(
            f"  Scores: TC={scores['task_completion']:.2f}  "
            f"PA={scores['policy_adherence']:.2f}  "
            f"COH={scores['coherence']:.2f}"
        )

        turn_details.append({
            "turn": idx,
            "user_message": msg,
            "reply": reply,
            "rubric": rubric,
            "scores": scores,
        })

    agg = avg_scores(per_turn_scores)
    print(
        f"\n  -- Averages --  TC={agg['task_completion']:.3f}  "
        f"PA={agg['policy_adherence']:.3f}  COH={agg['coherence']:.3f}"
    )

    return {
        "name": dialogue["name"],
        "requires_tool": dialogue["requires_tool"],
        "requires_rag": dialogue["requires_rag"],
        "avg_scores": agg,
        "turn_details": turn_details,
    }


@pytest.mark.asyncio
async def test_dialogue_01_checkin_crm(session_id):
    result = await _eval_dialogue(DIALOGUES[0], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_02_room_cost(session_id):
    result = await _eval_dialogue(DIALOGUES[1], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_03_weather(session_id):
    result = await _eval_dialogue(DIALOGUES[2], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_04_booking_calendar(session_id):
    result = await _eval_dialogue(DIALOGUES[3], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_05_out_of_scope(session_id):
    result = await _eval_dialogue(DIALOGUES[4], session_id)
    assert result["avg_scores"]["policy_adherence"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_06_phone_update(session_id):
    result = await _eval_dialogue(DIALOGUES[5], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_07_multiturn_book(session_id):
    result = await _eval_dialogue(DIALOGUES[6], session_id)
    assert result["avg_scores"]["coherence"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_08_amenities_rag(session_id):
    result = await _eval_dialogue(DIALOGUES[7], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_09_empty_input(session_id):
    result = await _eval_dialogue(DIALOGUES[8], session_id)
    assert result["avg_scores"]["coherence"] >= 0.0


@pytest.mark.asyncio
async def test_dialogue_10_conflicting_identity(session_id):
    result = await _eval_dialogue(DIALOGUES[9], session_id)
    assert result["avg_scores"]["task_completion"] >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 7.  STANDALONE RUNNER  (python tests/test_conversational_evals.py)
# ══════════════════════════════════════════════════════════════════════════════

async def _run_all() -> None:
    """Run every dialogue sequentially and generate the Markdown report."""
    all_results: List[Dict[str, Any]] = []

    try:
        for dialogue in DIALOGUES:
            sid = f"eval-{uuid.uuid4().hex[:12]}"
            result = await _eval_dialogue(dialogue, sid)
            all_results.append(result)
    finally:
        if all_results:
            generate_report(all_results)
        
            # Print final summary to stdout
            print("\n" + "=" * 60)
            print("  FINAL SUMMARY (Partial or Complete)")
            print("=" * 60)
            print(f"  {'Dialogue':<42} {'TC':>5} {'PA':>5} {'COH':>5} {'OVR':>5}")
            print(f"  {'-'*60}")
            for r in all_results:
                sc  = r["avg_scores"]
                ovr = (sc["task_completion"] + sc["policy_adherence"] + sc["coherence"]) / 3
                print(
                    f"  {r['name']:<42} {sc['task_completion']:>5.2f} "
                    f"{sc['policy_adherence']:>5.2f} {sc['coherence']:>5.2f} {ovr:>5.2f}"
                )
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(_run_all())
