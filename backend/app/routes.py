"""
API routes for Hotel Front Desk conversational AI system.

Step 7 — RAG integration:
  Before each LLM call the retriever is invoked to fetch relevant hotel
  knowledge chunks.  These are passed to prompt_builder.build_prompt()
  as the optional *rag_chunks* argument.  The call runs in a thread-pool
  executor so it never blocks the asyncio event loop.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import asyncio
import json
import logging
import re
from datetime import datetime, date, timedelta

from .websocket_manager import WebSocketManager
from .dependencies import (
    get_websocket_manager,
    get_session_manager,
    get_ollama_client,
    get_memory_manager,
    get_prompt_builder,
    get_audio_converter,
    get_moonshine_asr,
    get_piper_tts,
    get_crm_tool,
    get_tool_orchestrator,
)

# ── RAG retriever (Step 7) ────────────────────────────────────────
try:
    from rag.retriever import retrieve as _rag_retrieve
    _RAG_ENABLED = True
except ImportError:
    _RAG_ENABLED = False
    _rag_retrieve = None  # type: ignore[assignment]


async def _retrieve_rag_context(query: str, top_k: int = 2) -> List[str]:
    """
    Asynchronous wrapper around retrieve().

    Runs the synchronous embedding + FAISS search in a thread-pool executor
    to avoid blocking the asyncio event loop.  Returns an empty list if RAG
    is disabled or an error occurs.

    Performance target: < 800 ms end-to-end (first call may be slower due to
    model load; subsequent calls hit the in-process cache and are fast).

    Each returned chunk is capped at 300 characters to keep the overall
    prompt well within the 4096-token context window.
    """
    if not _RAG_ENABLED or not query or not query.strip():
        return []
    try:
        chunks: List[str] = await asyncio.to_thread(_rag_retrieve, query, top_k)
        # Truncate each chunk so the prompt stays within token budget.
        MAX_CHUNK_CHARS = 300
        chunks = [c[:MAX_CHUNK_CHARS] for c in chunks]
        return chunks
    except Exception as rag_err:  # noqa: BLE001
        logger.warning("RAG retrieval failed (non-fatal): %s", rag_err)
        return []


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUT_OF_DOMAIN_REFUSAL = "I'm sorry, I can only assist with hotel-related inquiries."
IN_DOMAIN_RECOVERY_PROMPT = "I'd be happy to help with your reservation."


def _format_tool_narration(executed_tools: List[Dict[str, Any]]) -> str:
    messages: List[str] = []
    for item in executed_tools:
        tool_name = str(item.get("tool_name", "tool"))
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        ok = bool(item.get("ok")) and bool(result.get("ok", True))
        if not ok:
            msg = str(
                result.get("message")
                or result.get("error")
                or f"I could not complete {tool_name} right now."
            )
            messages.append(msg)
            continue

        if tool_name == "calculate_room_cost":
            messages.append(str(result.get("message") or "Your room cost has been calculated."))
        elif tool_name == "add_booking_to_calendar":
            booking_msg = str(result.get("message") or "Your booking has been added to the calendar.")
            download_path = str(result.get("download_path") or "").strip()
            if download_path:
                booking_msg += f" Download Calendar Event: {download_path}"
            messages.append(booking_msg)
        elif tool_name == "get_hotel_weather":
            messages.append(str(result.get("message") or "Here is the weather update for your stay."))
        else:
            messages.append(str(result.get("message") or f"{tool_name} completed successfully."))

    return " ".join(m for m in messages if m).strip()


def _looks_like_tool_json_only(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    return stripped.startswith("{") and '"tool"' in stripped and stripped.endswith("}")


def _extract_email(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\b([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\b", text, flags=re.IGNORECASE)
    return m.group(1) if m else None


def _extract_phone(text: str) -> Optional[str]:
    if not text:
        return None
    # Simple international/PK-friendly capture (best effort)
    m = re.search(r"\b(\+?\d[\d\s\-()]{6,}\d)\b", text)
    if not m:
        return None
    phone = re.sub(r"\s+", " ", m.group(1)).strip()
    return phone[:32]


def _extract_name(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(
        r"\b(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z\-']*(?:\s+[A-Za-z][A-Za-z\-']*)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return None


def _is_identity_question(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(
        re.search(r"\b(who am i|what(?:'s| is) my name|do you know my name)\b", t)
        or re.fullmatch(r"who am i\??", t)
    )


async def _auto_capture_crm_profile(crm_tool, user_id: str, user_message: str) -> None:
    """
    Best-effort CRM capture so profiles persist across backend restarts even if
    the LLM doesn't emit a tool call.
    """
    try:
        if not user_id or not user_message:
            return

        email = _extract_email(user_message)
        phone = _extract_phone(user_message)
        name = _extract_name(user_message)

        if not any([email, phone, name]):
            return

        current = await crm_tool.get_user_info(user_id)
        if isinstance(current, dict) and current.get("ok") and current.get("message") == "not found":
            # Only create when we have at least a name or email/phone.
            await crm_tool.store_user_info(
                user_id,
                name=name or "",
                email=email or "",
                phone=phone or "",
                preferences={},
            )
            return

        user = (current.get("user") if isinstance(current, dict) else None) or {}
        if not isinstance(user, dict):
            user = {}

        current_name = (user.get("name") or "").strip()
        current_email = (user.get("email") or "").strip()
        current_phone = (user.get("phone") or "").strip()

        # Keep CRM aligned with the latest user-provided profile data.
        # Previously these fields were write-once, which caused stale values
        # (e.g. an old name) to persist across backend restarts.
        if name and name.strip().lower() != current_name.lower():
            await crm_tool.update_user_info(user_id, "name", name)
        if email and email.strip().lower() != current_email.lower():
            await crm_tool.update_user_info(user_id, "email", email)
        if phone and phone.strip() != current_phone:
            await crm_tool.update_user_info(user_id, "phone", phone)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CRM auto-capture failed (non-fatal): %s", exc)


def is_hotel_related_request(user_message: str, history: Optional[List[dict]] = None) -> bool:
    """
    Fast pre-check for obviously hotel-related or non-hotel patterns.
    Returns True to allow LLM to decide, False only for explicit non-hotel topics.
    """
    if not user_message or not user_message.strip():
        return True

    text = user_message.strip().lower()

    # Always allow greetings, pleasantries, and simple responses
    simple_responses = {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "thanks", "thank you", "yes", "yeah", "yep", "ok", "okay", "sure",
        "no", "nope",
    }
    if text in simple_responses:
        return True

    # Allow name introductions
    if re.search(r"\b(my name is|i am|i'm)\b", text, re.IGNORECASE):
        return True
    # Allow identity/CRM questions
    if _is_identity_question(text):
        return True

    # Explicit non-hotel topics - clear deny patterns
    deny_patterns = [
        r"^\s*\d+(?:\s*[+\-*/x÷]\s*\d+)+\s*(?:=|\?)?\s*$",  # Pure math: "5+3=?"
        r"\bwhat\s+is\s+\d+\s*[+\-*/x÷]\s*\d+\b",  # Natural math form: "what is 2+2"
        r"\b(write|create|generate|show me)\s+(code|program|script|function|python|java|javascript)",  # Coding requests
        r"\bcapital\s+of\b",  # Trivia prompt
        r"\b(president|prime minister|olympics|stock market)\b",  # Clearly non-hotel small talk topics
    ]
    
    for pattern in deny_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    # If it mentions hotel terms, definitely allow
    hotel_terms = (
        "hotel", "room", "reservation", "book", "booking", "check in", "check-in",
        "check out", "check-out", "stay", "night", "nights", "wifi", "parking",
        "breakfast", "amenity", "suite", "king", "queen", "deluxe", "weather", "forecast",
    )
    
    if any(term in text for term in hotel_terms):
        return True

    # If in booking conversation, allow follow-ups
    if history:
        recent = " ".join((m.get("content", "") or "").lower() for m in history[-6:])
        if any(term in recent for term in ["room", "reservation", "book", "check in", "stay"]):
            return True

    # Default: let LLM decide (return True to allow)
    return True


def is_greeting_only(user_message: str) -> bool:
    """Check if message is purely a greeting without booking intent."""
    if not user_message:
        return False
    text = re.sub(r"[^a-z\s]", "", user_message.lower()).strip()
    
    greeting_terms = {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    }
    if text in greeting_terms:
        return True
    
    # Greeting with name introduction
    if re.search(r"\b(hi|hello|hey)\b", text) and re.search(r"\b(my name is|i am|im)\b", text):
        booking_words = ["room", "book", "reservation", "check", "stay", "night"]
        if not any(word in text for word in booking_words):
            return True
    
    return False


def greeting_response(has_history: bool, guest_name: str = None) -> str:
    """Return appropriate greeting response."""
    if guest_name:
        return f"Hello {guest_name}! How can I assist you with your stay today?"
    if has_history:
        return "Happy to help. What can I do for you?"
    return "Hello! Welcome to the front desk. How can I assist you with your stay today?"


def _word_to_number(token: str) -> Optional[int]:
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    return words.get(token.lower())


def _parse_relative_date(text: str, today: date) -> Optional[date]:
    lowered = text.lower()
    if "day after tomorrow" in lowered:
        return today + timedelta(days=2)
    if "today" in lowered or "tonight" in lowered:
        return today
    if (
        re.search(r"\btom+or+row\b", lowered)
        or "tommorrow" in lowered
        or "tomorow" in lowered
        or "tomorrow" in lowered
    ):
        return today + timedelta(days=1)
    return None


def _parse_explicit_date(text: str, today: date) -> Optional[date]:
    lowered = text.lower()
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    dm_match = re.search(
        r"\b(\d{1,2})\s+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
        lowered,
    )
    if dm_match:
        day = int(dm_match.group(1))
        month = month_map[dm_match.group(2)]
        year = today.year
        try:
            parsed = date(year, month, day)
            if parsed < today:
                parsed = date(year + 1, month, day)
            return parsed
        except ValueError:
            return None

    slash_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lowered)
    if slash_match:
        d1 = int(slash_match.group(1))
        d2 = int(slash_match.group(2))
        year_raw = slash_match.group(3)
        year = today.year if not year_raw else int(year_raw) + (2000 if len(year_raw) == 2 else 0)
        # Interpret as day/month for this hotel context.
        day, month = d1, d2
        try:
            parsed = date(year, month, day)
            if parsed < today and not year_raw:
                parsed = date(year + 1, month, day)
            return parsed
        except ValueError:
            return None

    return None


def extract_booking_state(history: List[dict], current_message: str) -> Dict[str, Any]:
    today = date.today()
    user_texts = [m.get("content", "") for m in history if m.get("role") == "user"]
    if current_message:
        user_texts.append(current_message)

    state: Dict[str, Any] = {
        "guest_name": None,
        "check_in_date": None,
        "stay_nights": None,
        "room_type": None,
        "requested_services": [],
    }

    room_types = ["standard", "king", "queen", "deluxe", "suite", "double", "single", "twin"]
    recent_assistant_text = " ".join(
        (m.get("content", "") or "").lower()
        for m in history[-8:]
        if m.get("role") == "assistant"
    )
    asked_for_nights_recently = any(
        phrase in recent_assistant_text
        for phrase in ["how many nights", "length of stay", "stay for", "night(s)"]
    )

    for text in user_texts:
        if not text:
            continue

        name_match = re.search(r"\b(my name is|i am|i'm)\s+([A-Za-z][A-Za-z\-']*(?:\s+[A-Za-z][A-Za-z\-']*)?)", text, flags=re.IGNORECASE)
        if name_match:
            state["guest_name"] = name_match.group(2).strip()
        elif re.fullmatch(r"\s*[A-Za-z][A-Za-z\-']{1,30}\s*", text):
            candidate = text.strip()
            non_name_tokens = {
                "yes", "yeah", "yep", "ok", "okay", "sure", "confirm",
                "proceed", "tomorrow", "today", "standard", "king", "queen",
                "deluxe", "suite", "double", "single", "twin",
                "tommorrow", "tomorow", "arrival", "hi", "hello", "hey",
                "january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december",
            }
            if candidate.lower() not in non_name_tokens:
                state["guest_name"] = candidate

        nights_match = re.search(r"\b(\d{1,2})\s*(?:day|days|night|nights)\b", text, flags=re.IGNORECASE)
        if nights_match:
            state["stay_nights"] = int(nights_match.group(1))
        else:
            # Handle compact replies such as "7" after asking for stay length.
            bare_number = re.fullmatch(r"\s*(\d{1,2})\s*", text)
            if bare_number and asked_for_nights_recently:
                nights_value = int(bare_number.group(1))
                if 1 <= nights_value <= 30:
                    state["stay_nights"] = nights_value

            word_nights = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:day|days|night|nights)\b", text, flags=re.IGNORECASE)
            if word_nights:
                parsed_n = _word_to_number(word_nights.group(1))
                if parsed_n:
                    state["stay_nights"] = parsed_n

        lowered = text.lower()
        for rt in room_types:
            if re.search(rf"\b{rt}\b", lowered):
                state["room_type"] = rt.capitalize() + (" room" if rt != "suite" else "")

        rel_date = _parse_relative_date(text, today)
        explicit_date = _parse_explicit_date(text, today)
        if explicit_date is not None:
            state["check_in_date"] = explicit_date
        elif rel_date is not None:
            state["check_in_date"] = rel_date

        if "wake" in lowered and "call" in lowered and "Wake-up call" not in state["requested_services"]:
            state["requested_services"].append("Wake-up call")

    if state["check_in_date"] and state["stay_nights"]:
        state["check_out_date"] = state["check_in_date"] + timedelta(days=state["stay_nights"])
    else:
        state["check_out_date"] = None

    missing = []
    if not state["check_in_date"]:
        missing.append("check-in date")
    if not state["stay_nights"]:
        missing.append("length of stay")
    if not state["room_type"]:
        missing.append("room type")
    if not state["guest_name"]:
        missing.append("guest name")
    state["missing_fields"] = missing
    return state

def is_booking_summary_question(user_message: str) -> bool:
    text = (user_message or "").lower()
    patterns = [
        r"which\s+room\s+have\s+i\s+booked",
        r"what\s+room\s+(did\s+i\s+book|have\s+i\s+booked)",
        r"what\s+room\s+(did\s+i\s+choose|have\s+i\s+chosen)",
        r"which\s+room\s+did\s+i\s+choose",
        r"my\s+booking\s+details",
        r"what\s+have\s+i\s+booked",
    ]
    return any(re.search(p, text) for p in patterns)


def has_booking_context(history: List[dict]) -> bool:
    if not history:
        return False
    joined = " ".join((m.get("content", "") or "").lower() for m in history[-10:])
    return any(term in joined for term in ["room", "reservation", "book", "check in", "check-in", "arrival", "stay"])


def is_date_update_message(user_message: str) -> bool:
    text = (user_message or "").lower()
    if re.search(r"\b(arrival|arrive|check\s*in|checkin|tom+or+row|today|tonight)\b", text):
        return True
    if re.search(r"\b\d{1,2}\s+(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b", text):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text):
        return True
    return False


def is_room_type_update_message(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(rt in text for rt in ["standard", "king", "queen", "deluxe", "suite", "double", "single", "twin"])


def is_stay_length_update_message(user_message: str) -> bool:
    text = (user_message or "").lower()
    if re.search(r"\b\d{1,2}\s*(day|days|night|nights)\b", text):
        return True
    if re.fullmatch(r"\s*\d{1,2}\s*", text):
        return True
    return bool(re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*(day|days|night|nights)\b", text))


def _strip_leading_booking_prefix(text: str) -> str:
    prefix = "I'd be happy to help with your reservation. "
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def build_date_acknowledgement(booking_state: Dict[str, Any], raw_message: str = "") -> str:
    check_in = booking_state.get("check_in_date")
    if check_in is None:
        raw = (raw_message or "").lower()
        if any(token in raw for token in ["tomorrow", "tommorrow", "tomorow"]):
            check_in = date.today() + timedelta(days=1)
            booking_state = dict(booking_state)
            booking_state["check_in_date"] = check_in
            booking_state["missing_fields"] = [f for f in booking_state.get("missing_fields", []) if f != "check-in date"]

    if check_in is None:
        return build_progressive_booking_followup(booking_state)

    next_question = _strip_leading_booking_prefix(build_progressive_booking_followup(booking_state))
    return f"Noted. Your check-in date is {format_hotel_date(check_in)}. {next_question}"


def build_room_type_acknowledgement(booking_state: Dict[str, Any]) -> str:
    room_type = booking_state.get("room_type") or "selected room"
    check_in = booking_state.get("check_in_date")
    check_out = booking_state.get("check_out_date")
    nights = booking_state.get("stay_nights")

    if check_in and check_out and nights:
        lead = (
            f"Great choice. I noted a {room_type} from {format_hotel_date(check_in)} "
            f"to {format_hotel_date(check_out)} for {nights} night(s). "
        )
    else:
        lead = f"Great choice. I noted a {room_type}. "

    if not booking_state.get("guest_name"):
        return lead + "May I have the guest name for the reservation, please?"

    next_question = _strip_leading_booking_prefix(build_progressive_booking_followup(booking_state))
    return lead + next_question


def build_stay_length_acknowledgement(booking_state: Dict[str, Any]) -> str:
    nights = booking_state.get("stay_nights")
    check_in = booking_state.get("check_in_date")
    if nights and check_in:
        lead = (
            f"Understood. You will be checking in on {format_hotel_date(check_in)} "
            f"and your length of stay is {nights} night(s). "
        )
    elif nights:
        lead = f"Understood. I noted your stay length as {nights} night(s). "
    else:
        return build_progressive_booking_followup(booking_state)

    next_question = _strip_leading_booking_prefix(build_progressive_booking_followup(booking_state))
    return lead + next_question


def with_injected_guest_name(booking_state: Dict[str, Any], guest_name: str) -> Dict[str, Any]:
    updated = dict(booking_state)
    updated["guest_name"] = guest_name.strip()
    updated["missing_fields"] = [f for f in updated.get("missing_fields", []) if f != "guest name"]
    return updated


def is_booking_confirmation_message(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    return text in {"yes", "yeah", "yep", "confirm", "proceed", "book it", "go ahead", "okay", "ok"}


def is_booking_intent_message(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(
        phrase in text
        for phrase in [
            "need a room",
            "need room",
            "book a room",
            "book room",
            "reservation",
            "i need a reservation",
            "want to stay",
        ]
    )


def is_probable_name_reply(user_message: str, booking_state: Dict[str, Any], history: List[dict]) -> bool:
    if not has_booking_context(history):
        return False
    if "guest name" not in booking_state.get("missing_fields", []):
        return False

    text = (user_message or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z\-']{1,30}(?:\s+[A-Za-z][A-Za-z\-']{1,30})?", text):
        return False

    non_name_tokens = {
        "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "proceed",
        "tomorrow", "today", "standard", "king", "queen", "deluxe", "suite",
    }
    return text.lower() not in non_name_tokens


def is_name_declaration_message(user_message: str) -> bool:
    text = (user_message or "").strip()
    if not text:
        return False
    return bool(
        re.search(
            r"\b(my name is|i am|i'm)\s+[A-Za-z][A-Za-z\-']*(?:\s+[A-Za-z][A-Za-z\-']*)?",
            text,
            flags=re.IGNORECASE,
        )
    )


def is_stay_length_question(user_message: str) -> bool:
    text = (user_message or "").lower()
    return bool(
        re.search(r"\b(how many nights|stay length|length of stay|how long am i staying)\b", text)
    )


def is_checkout_date_question(user_message: str) -> bool:
    text = (user_message or "").lower()
    return bool(re.search(r"\b(check\s*-?out|checkout)\b", text))


def is_checkin_date_question(user_message: str) -> bool:
    text = (user_message or "").lower()
    return bool(
        re.search(
            r"\b(check\s*-?in|checkin|arrival)\b",
            text,
        )
    ) and bool(re.search(r"\b(when|what|date|which|my)\b", text))


def build_stay_length_response(booking_state: Dict[str, Any]) -> str:
    nights = booking_state.get("stay_nights")
    if nights:
        return f"Your stay length is {nights} night(s)."
    return "I can confirm that once you share how many nights you plan to stay."


def build_checkout_date_response(booking_state: Dict[str, Any]) -> str:
    check_out = booking_state.get("check_out_date")
    if check_out:
        return f"Your check-out date is {format_hotel_date(check_out)}."
    if booking_state.get("check_in_date") and not booking_state.get("stay_nights"):
        return "I have your check-in date. Please share the number of nights so I can confirm check-out."
    return "Please share your check-in date and stay length so I can provide the check-out date."


def should_enforce_booking_order(user_message: str) -> bool:
    """Enforce strict field order only on explicit booking progression turns."""
    message = user_message or ""
    if is_booking_summary_question(message) or is_checkin_date_question(message) or is_checkout_date_question(message) or is_stay_length_question(message):
        return False
    if "?" in message:
        return False
    return any([
        is_booking_intent_message(message),
        is_date_update_message(message),
        is_stay_length_update_message(message),
        is_room_type_update_message(message),
        is_booking_confirmation_message(message),
        is_name_declaration_message(message),
    ])


def build_checkin_date_response(booking_state: Dict[str, Any]) -> str:
    check_in = booking_state.get("check_in_date")
    if check_in:
        return f"Your check-in date is {format_hotel_date(check_in)}."
    return "I can confirm that once you share your check-in date."


def get_deterministic_booking_response(
    user_message: str,
    active_context: List[dict],
    prompt_builder: Any,
) -> Optional[str]:
    """Handle structured booking turns without another model call."""
    if not prompt_builder or not hasattr(prompt_builder, "get_booking_state"):
        return None

    try:
        booking_state = prompt_builder.get_booking_state(active_context or [], user_message)
    except (TypeError, ValueError, AttributeError):
        return None

    if is_booking_summary_question(user_message):
        return build_booking_summary_response(booking_state)

    if is_checkin_date_question(user_message):
        return build_checkin_date_response(booking_state)

    if is_checkout_date_question(user_message):
        return build_checkout_date_response(booking_state)

    if is_stay_length_question(user_message):
        return build_stay_length_response(booking_state)

    if is_booking_confirmation_message(user_message):
        return build_booking_confirmation_response(booking_state)

    if is_booking_intent_message(user_message):
        return build_progressive_booking_followup(booking_state)

    if has_booking_context(active_context):
        if is_date_update_message(user_message):
            return build_date_acknowledgement(booking_state, user_message)
        if is_stay_length_update_message(user_message):
            return build_stay_length_acknowledgement(booking_state)
        if is_room_type_update_message(user_message):
            return build_room_type_acknowledgement(booking_state)

        if is_probable_name_reply(user_message, booking_state, active_context):
            updated_state = with_injected_guest_name(booking_state, user_message)
            return build_name_acknowledgement_response(updated_state)

        if is_name_declaration_message(user_message):
            return build_name_acknowledgement_response(booking_state)

    return None


def format_hotel_date(d: Optional[date]) -> str:
    if not d:
        return "Unknown"
    return d.strftime("%d %B %Y")


def _repair_orphan_month_suffix(response: str, booking_state: Dict[str, Any]) -> str:
    """Fix malformed dates like 'March th' using parsed booking state dates."""
    if not response:
        return response

    check_in = booking_state.get("check_in_date") if booking_state else None
    if not check_in:
        return response

    day_month = check_in.strftime("%d %B")
    day_month_no_zero = f"{check_in.day} {check_in.strftime('%B')}"

    repaired = response
    # Example: "March th" -> "12 March"
    repaired = re.sub(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(st|nd|rd|th)\b",
        day_month_no_zero,
        repaired,
        flags=re.IGNORECASE,
    )
    # Example: "the th of March" -> "12 March"
    repaired = re.sub(
        r"\bthe\s+(st|nd|rd|th)\s+of\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b",
        day_month_no_zero,
        repaired,
        flags=re.IGNORECASE,
    )

    # Keep a consistent spacing style if model produced odd punctuation.
    repaired = repaired.replace(" ,", ",")
    repaired = re.sub(r"\s{2,}", " ", repaired).strip()
    if not repaired:
        return day_month
    return repaired


def sanitize_model_response_text(response: str) -> str:
    if not response:
        return response

    cleaned = response.strip()
    # Normalize awkward first-person phrasing from some model outputs.
    cleaned = re.sub(r"\bstaying\s+with\s+me\b", "staying", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bstay\s+with\s+me\b", "stay", cleaned, flags=re.IGNORECASE)
    # Drop accidental in-response transcript role labels.
    cleaned = re.sub(r"\bGuest:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAssistant:\s*", "", cleaned, flags=re.IGNORECASE)

    # If the model starts with "Assistant:", keep only the assistant content.
    cleaned = re.sub(r"^\s*assistant\s*:\s*", "", cleaned, flags=re.IGNORECASE)

    # Drop any leaked multi-turn transcript continuation.
    transcript_markers = ["\nGuest:", "\nUser:", "\nAssistant:", " Guest:", " User:"]
    split_idx = len(cleaned)
    for marker in transcript_markers:
        idx = cleaned.find(marker)
        if idx != -1 and idx < split_idx:
            split_idx = idx
    cleaned = cleaned[:split_idx]

    # Remove standalone roleplay lines if present.
    cleaned = re.sub(r"(?im)^\s*(guest|user)\s*:\s*.*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*assistant\s*:\s*", "", cleaned)

    # Remove leaked reasoning-style scaffolding.
    if cleaned.lower().startswith("the user mentioned"):
        parts = cleaned.split("\n\n", 1)
        if len(parts) == 2:
            cleaned = parts[1].strip()
    cleaned = re.sub(r"today is\s*--", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bCurrent guest request\b:.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\bKnown booking state\b:.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\bMissing required booking fields\b:.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.replace("March ,", "March")
    cleaned = cleaned.replace("April ,", "April")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _is_confirmation_like_message(user_message: str) -> bool:
    text = (user_message or "").strip().lower()
    return text in {
        "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "proceed",
        "go ahead", "book it", "no changes needed", "no change needed",
        "no changes", "no change", "no changed needed", "proceed with it",
    }


def _strip_roleplay_artifacts(text: str) -> str:
    if not text:
        return text
    cleaned = text
    cleaned = re.sub(r"\bGuest:\s*.*?(?=\bAssistant:\b|$)", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\bAssistant:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _format_final_booking_confirmation(booking_state: Dict[str, Any]) -> str:
    return (
        "Great. Your booking is confirmed with the following details:\n"
        f"- Guest Name: {booking_state.get('guest_name')}\n"
        f"- Check-in Date: {format_hotel_date(booking_state.get('check_in_date'))}\n"
        f"- Check-out Date: {format_hotel_date(booking_state.get('check_out_date'))}\n"
        f"- Nights: {booking_state.get('stay_nights')}\n"
        f"- Room Type: {booking_state.get('room_type')}\n\n"
        "If you need anything else for your stay, I can help."
    )


def _format_booking_ready_to_confirm(booking_state: Dict[str, Any]) -> str:
    return (
        "I have all required booking details:\n"
        f"- Guest Name: {booking_state.get('guest_name')}\n"
        f"- Check-in Date: {format_hotel_date(booking_state.get('check_in_date'))}\n"
        f"- Check-out Date: {format_hotel_date(booking_state.get('check_out_date'))}\n"
        f"- Nights: {booking_state.get('stay_nights')}\n"
        f"- Room Type: {booking_state.get('room_type')}\n\n"
        "Please reply 'confirm' to finalize your reservation."
    )


def _is_room_type_availability_question(user_message: str) -> bool:
    text = (user_message or "").lower()
    return bool(
        re.search(r"\b(which|what)\b.*\b(room\s*types?|types?\s+of\s+rooms?)\b", text)
        or re.search(r"\broom\s*types?\s+(available|there)\b", text)
        or re.search(r"\btypes?\s+are\s+available\b", text)
    )


def apply_fast_response_fixes(
    user_message: str,
    model_response: str,
    filtered_history: Optional[List[dict]],
    prompt_builder: Any,
) -> str:
    """Apply low-latency guardrails without extra model calls."""
    response = _strip_roleplay_artifacts(sanitize_model_response_text(model_response or ""))
    if not response:
        return response

    user_lower = (user_message or "").lower()
    refusal_marker = "i can only assist with hotel-related inquiries"
    is_in_domain = is_hotel_related_request(user_message, filtered_history)
    if refusal_marker in response.lower() and not is_in_domain:
        return OUT_OF_DOMAIN_REFUSAL

    if not prompt_builder or not hasattr(prompt_builder, "get_booking_state"):
        return response

    try:
        booking_state = prompt_builder.get_booking_state(filtered_history or [], user_message)
    except (RuntimeError, ValueError, TypeError, AttributeError):
        return response

    response = _repair_orphan_month_suffix(response, booking_state)

    missing_fields = booking_state.get("missing_fields", [])
    has_all_fields = not missing_fields
    asks_name = bool(re.search(r"\b(full\s+name|last\s+name|first\s+name|guest\s+name|name)\b", response.lower()))
    asks_room_type = bool(re.search(r"\b(room type|king|queen|deluxe|suite|twin|double|single|standard)\b", response.lower()))

    # Recover from mistaken in-domain refusal without another model call.
    if refusal_marker in response.lower() and is_in_domain:
        if _is_room_type_availability_question(user_message):
            return "We currently offer Standard, King, Queen, Deluxe, and Suite room types. Which one would you like to book?"
        if "parking" in user_lower:
            return "I can help with parking details. Are you asking about parking availability, location, or charges?"
        if is_booking_summary_question(user_message):
            if has_all_fields:
                return _format_booking_ready_to_confirm(booking_state)
            return f"For your reservation, I still need: {', '.join(missing_fields)}."
        if has_booking_context(filtered_history or []):
            return build_progressive_booking_followup(booking_state)
        return "I can help with hotel requests like booking, rooms, parking, and amenities. How can I assist you with your stay?"

    # Answer room-type availability questions directly.
    if _is_room_type_availability_question(user_message):
        return "We currently offer Standard, King, Queen, Deluxe, and Suite room types. Which one would you like to book?"

    # Avoid re-asking room type once it is already captured.
    if booking_state.get("room_type") and asks_room_type and "room type" not in missing_fields:
        if "guest name" in missing_fields:
            return "May I have the guest name for the reservation, please?"
        if "length of stay" in missing_fields:
            return "Great, and how many nights will you be staying?"
        if "check-in date" in missing_fields:
            return "I'd be happy to help with your reservation. Could you share your check-in date?"

    # Avoid re-asking name once already captured.
    if booking_state.get("guest_name") and asks_name and "guest name" not in missing_fields:
        if has_all_fields:
            return _format_booking_ready_to_confirm(booking_state)
        if "room type" in missing_fields:
            return "What room type would you prefer (for example Standard, King, Queen, Deluxe, or Suite)?"
        if "length of stay" in missing_fields:
            return "Great, and how many nights will you be staying?"
        if "check-in date" in missing_fields:
            return "I'd be happy to help with your reservation. Could you share your check-in date?"

    # For repeated confirmation turns, return a final confirmed response once.
    if has_all_fields and _is_confirmation_like_message(user_message):
        return _format_final_booking_confirmation(booking_state)

    # Keep booking summary format consistent and include nights + question on a new line.
    if has_all_fields and re.search(r"booking (details|has been confirmed|is confirmed)", response, flags=re.IGNORECASE):
        question_text = "Would you like to proceed with this booking or make any adjustments?"
        body = response
        has_question = question_text.lower() in response.lower()

        if has_question:
            body = re.sub(r"\s*would you like to proceed with this booking or make any adjustments\?", "", body, flags=re.IGNORECASE).strip()

        if not re.search(r"-\s*Nights:\s*", body, flags=re.IGNORECASE):
            body += f"\n- Nights: {booking_state.get('stay_nights')}"

        if has_question:
            body = body.rstrip() + f"\n\n{question_text}"

        return body

    return response


def enforce_response_constraints(
    user_message: str,
    model_response: str,
    filtered_history: Optional[List[dict]],
    prompt_builder: Any,
    ollama_client: Any,
) -> str:
    """
    Enforce output constraints via post-processing and targeted model rewrites.

    This does not replace model reasoning; it only corrects invalid outputs that
    violate hard response rules (e.g., non-hotel refusal and booking completion).
    """
    if not model_response:
        return model_response

    response = model_response.strip()
    lower_resp = response.lower()
    asks_booking_field = bool(
        re.search(
            r"\b(check[\s-]?in|arrival|night|nights|room type|king|queen|deluxe|suite|guest name|full name)\b",
            lower_resp,
        )
    )

    lowered_user = (user_message or "").lower()
    looks_booking_like = any(
        term in lowered_user
        for term in [
            "room",
            "book",
            "reservation",
            "check in",
            "check-in",
            "stay",
            "night",
            "arrival",
            "guest",
            "name",
            "king",
            "queen",
            "deluxe",
            "suite",
            "double",
            "single",
            "twin",
        ]
    ) or is_booking_confirmation_message(user_message) or is_name_declaration_message(user_message)

    # If assistant tried to continue booking for a potentially non-hotel query,
    # use model classification to enforce exact refusal.
    if asks_booking_field and not looks_booking_like and not llm_domain_allows_response(user_message, filtered_history, ollama_client):
        return OUT_OF_DOMAIN_REFUSAL

    # Fix malformed nights phrasing like "for or nights".
    if re.search(r"\bfor\s+(?:or|and)?\s*nights?\b", lower_resp):
        rewrite_prompt = (
            "System:\n"
            "Rewrite the assistant draft into a grammatically correct hotel reply.\n"
            "Keep meaning the same, concise, 1 sentence.\n"
            "Return only the corrected assistant response.\n\n"
            f"User: {user_message}\n"
            f"Draft: {response}\n"
            "Assistant:"
        )
        repaired = ollama_client.generate(rewrite_prompt)
        if repaired and not repaired.startswith("Error:"):
            response = repaired.strip()

    # If all booking details are already present, do not ask for missing fields again.
    if prompt_builder and hasattr(prompt_builder, "get_booking_state"):
        try:
            booking_state = prompt_builder.get_booking_state(filtered_history or [], user_message)
            # For a new booking intent, ensure we start by collecting check-in date.
            new_booking_intent = is_booking_intent_message(user_message) and not any([
                booking_state.get("check_in_date"),
                booking_state.get("stay_nights"),
                booking_state.get("room_type"),
                booking_state.get("guest_name"),
            ])
            if new_booking_intent and asks_booking_field:
                asks_name = bool(re.search(r"\b(name|full name|guest name)\b", lower_resp))
                asks_room = bool(re.search(r"\b(room type|king|queen|deluxe|suite|twin|double|single)\b", lower_resp))
                asks_nights = bool(re.search(r"\b(night|nights|length of stay)\b", lower_resp))
                asks_checkin = bool(re.search(r"\b(check[\s-]?in|arrival date|arrive)\b", lower_resp))
                if asks_name or asks_room or asks_nights or not asks_checkin:
                    return build_progressive_booking_followup(booking_state)

            has_all_fields = not booking_state.get("missing_fields")
            should_finalize = has_all_fields and (
                is_booking_confirmation_message(user_message)
                or is_name_declaration_message(user_message)
                or is_probable_name_reply(user_message, booking_state, filtered_history or [])
            )

            if should_finalize and asks_booking_field:
                summary_prompt = (
                    "System:\n"
                    "Rewrite as a final reservation confirmation.\n"
                    "Do not ask any follow-up question.\n"
                    "Keep it concise and warm (1-2 sentences).\n\n"
                    f"Guest name: {booking_state.get('guest_name')}\n"
                    f"Room type: {booking_state.get('room_type')}\n"
                    f"Check-in: {format_hotel_date(booking_state.get('check_in_date'))}\n"
                    f"Check-out: {format_hotel_date(booking_state.get('check_out_date'))}\n"
                    f"Nights: {booking_state.get('stay_nights')}\n"
                    f"User message: {user_message}\n"
                    f"Draft response: {response}\n"
                    "Assistant:"
                )
                repaired = ollama_client.generate(summary_prompt)
                if repaired and not repaired.startswith("Error:"):
                    response = repaired.strip()
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError):
            pass

    return response


def llm_domain_allows_response(
    user_message: str,
    filtered_history: Optional[List[dict]],
    ollama_client: Any,
) -> bool:
    """
    Use the LLM to classify if the message is hotel-related.
    Optimized prompt for better classification with 3B models.
    Returns True if hotel-related, False otherwise.
    """
    # Build context from recent history
    context_lines = []
    for item in (filtered_history or [])[-4:]:
        role = item.get("role", "user")
        label = "Guest" if role == "user" else "Assistant"
        context_lines.append(f"{label}: {item.get('content', '')}")
    context_block = "\n".join(context_lines) if context_lines else "(new conversation)"

    decision_prompt = f"""You are classifying if a guest's message is hotel-related.

HOTEL-RELATED (say ALLOW):
✓ Greetings: "Hi", "Hello", "Good morning"
✓ Introductions: "My name is John", "I'm Sarah"
✓ Bookings: "I need a room", "Book for tomorrow"
✓ Amenities: "Do you have wifi?", "Is parking free?", "Breakfast included?"
✓ Services: "Wake-up call", "Airport transfer", "Room service"
✓ Policies: "Cancellation policy", "Late checkout"
✓ Guest help: "Restaurants nearby?", "Things to do?", "Taxi service?"
✓ Follow-ups: dates, numbers, room types, names (when in booking conversation)

NON-HOTEL (say REFUSE):
✗ Math: "What is 5+3?", "Calculate 10*20"
✗ Coding: "Write Python code", "Create a function"
✗ Trivia: "Who won Olympics?", "Capital of France?"
✗ Weather: "What's the weather?"
✗ News/Politics: "Current events?", "Who is president?"

Recent conversation:
{context_block}

Latest guest message: "{user_message}"

Is this hotel-related?
Respond with ONLY one word: ALLOW or REFUSE

Answer:"""

    try:
        decision = (ollama_client.generate(decision_prompt) or "").strip().upper()
        # Look for ALLOW or REFUSE in the response
        if "REFUSE" in decision:
            return False
        if "ALLOW" in decision:
            return True
        # If unclear, default to allowing (fail-open)
        return True
    except (RuntimeError, ValueError, TypeError, OSError):
        # On error, allow the message through (fail-open)
        return True


def repair_in_domain_refusal_with_llm(
    user_message: str,
    model_response: str,
    filtered_history: Optional[List[dict]],
    ollama_client: Any,
) -> str:
    """If the model refuses an in-domain request, ask the model to repair its own draft."""
    if not model_response:
        return model_response

    refusal_marker = "i can only assist with hotel-related inquiries"
    if refusal_marker not in model_response.lower():
        return model_response

    history_lines = []
    for item in (filtered_history or [])[-6:]:
        role = item.get("role", "user")
        content = item.get("content", "")
        label = "User" if role == "user" else "Assistant"
        history_lines.append(f"{label}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(no prior turns)"

    rewrite_prompt = (
        "System:\n"
        "You are rewriting a hotel front desk assistant response.\n"
        "The user request is in hotel domain.\n"
        "Return only the corrected assistant reply.\n"
        "Do not include any refusal text.\n"
        "Be concise, warm, and ask only the next useful booking question if details are missing.\n\n"
        f"Recent context:\n{history_block}\n\n"
        f"User: {user_message}\n"
        f"Draft assistant reply: {model_response}\n"
        "Assistant:"
    )

    try:
        repaired = ollama_client.generate(rewrite_prompt)
        return repaired if repaired and not repaired.startswith("Error:") else model_response
    except (RuntimeError, ValueError, TypeError, OSError):
        return model_response


def repair_next_field_order_with_llm(
    user_message: str,
    model_response: str,
    filtered_history: Optional[List[dict]],
    prompt_builder: Any,
    ollama_client: Any,
) -> str:
    """Rewrite responses that ask for a later booking field before the next required one."""
    if not model_response:
        return model_response

    lowered_message = (user_message or "").lower()
    has_booking_hint = any(
        token in lowered_message
        for token in ["room", "book", "reservation", "check in", "check-in", "stay", "night", "nights"]
    )
    if is_greeting_only(user_message) and not has_booking_hint:
        return model_response

    try:
        booking_state = prompt_builder.get_booking_state(filtered_history or [], user_message)
    except (RuntimeError, ValueError, TypeError, AttributeError):
        return model_response

    next_required = "none"
    if not booking_state.get("check_in_date"):
        next_required = "check-in date"
    elif not booking_state.get("stay_nights"):
        next_required = "length of stay"
    elif not booking_state.get("room_type"):
        next_required = "room type"
    elif not booking_state.get("guest_name"):
        next_required = "guest name"

    text = model_response.lower()
    asks_name = bool(re.search(r"\b(name|full name|guest name)\b", text))
    asks_room = bool(re.search(r"\b(room type|king|queen|deluxe|suite|twin|double|single)\b", text))
    asks_nights = bool(re.search(r"\b(night|nights|length of stay)\b", text))
    asks_checkin = bool(re.search(r"\b(check[\s-]?in|arrival date|arrive)\b", text))

    wrong_order = (
        (next_required == "check-in date" and (asks_name or asks_room or asks_nights))
        or (next_required == "length of stay" and (asks_name or asks_room))
        or (next_required == "room type" and asks_name)
        or (next_required == "guest name" and (asks_room or asks_nights or asks_checkin))
    )

    if not wrong_order:
        return model_response

    rewrite_prompt = (
        "System:\n"
        "Rewrite the draft hotel front desk response to ask only for the correct next required field.\n"
        "Keep the same meaning and tone, concise and natural, max two short sentences.\n"
        "Do not include internal notes.\n\n"
        f"Next required field: {next_required}\n"
        f"User message: {user_message}\n"
        f"Draft response: {model_response}\n"
        "Assistant:"
    )

    try:
        repaired = ollama_client.generate(rewrite_prompt)
        if repaired and not repaired.startswith("Error:"):
            candidate = repaired.lower()
            candidate_asks_name = bool(re.search(r"\b(name|full name|guest name)\b", candidate))
            candidate_asks_room = bool(re.search(r"\b(room type|king|queen|deluxe|suite|twin|double|single)\b", candidate))
            candidate_asks_nights = bool(re.search(r"\b(night|nights|length of stay)\b", candidate))
            candidate_asks_checkin = bool(re.search(r"\b(check[\s-]?in|arrival date|arrive)\b", candidate))

            candidate_wrong_order = (
                (next_required == "check-in date" and (candidate_asks_name or candidate_asks_room or candidate_asks_nights))
                or (next_required == "length of stay" and (candidate_asks_name or candidate_asks_room))
                or (next_required == "room type" and candidate_asks_name)
                or (next_required == "guest name" and (candidate_asks_room or candidate_asks_nights or candidate_asks_checkin))
            )
            if not candidate_wrong_order:
                return repaired
        return build_progressive_booking_followup(booking_state)
    except (RuntimeError, ValueError, TypeError, OSError):
        return build_progressive_booking_followup(booking_state)


def repair_greeting_opener_with_llm(user_message: str, model_response: str, ollama_client: Any) -> str:
    """For greeting/introduction turns, keep reply as welcome + open-ended help question."""
    if not model_response:
        return model_response

    normalized = re.sub(r"[^a-z\s]", "", (user_message or "").lower()).strip()
    intro_like = bool(re.search(r"\b(hi|hello|hey)\b", normalized)) and bool(
        re.search(r"\b(my name is|i am|im|i'm)\b", normalized)
    )
    pure_greeting = normalized in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
    if not (intro_like or pure_greeting):
        return model_response

    if not re.search(r"\b(check[\s-]?in|arrival|night|nights|room type|guest name|full name)\b", model_response.lower()):
        return model_response

    rewrite_prompt = (
        "System:\n"
        "Rewrite the draft as a natural hotel welcome message.\n"
        "Do not ask for booking details yet.\n"
        "Acknowledge the name if present, then ask one open-ended help question.\n"
        "Max 2 short sentences.\n\n"
        f"User: {user_message}\n"
        f"Draft response: {model_response}\n"
        "Assistant:"
    )

    try:
        repaired = ollama_client.generate(rewrite_prompt)
        return repaired if repaired and not repaired.startswith("Error:") else model_response
    except (RuntimeError, ValueError, TypeError, OSError):
        return model_response


def build_progressive_booking_followup(booking_state: Dict[str, Any]) -> str:
    """Create a natural one-step follow-up question based on missing details."""
    missing = booking_state.get("missing_fields", []) if booking_state else []

    if "check-in date" in missing:
        return "I'd be happy to help with your reservation. Could you share your check-in date?"
    if "length of stay" in missing:
        return "Great, and how many nights will you be staying?"
    if "room type" in missing:
        return "What room type would you prefer (for example King, Queen, or Deluxe)?"
    if "guest name" in missing:
        return "May I have the guest name for the reservation, please?"

    return "Thanks. Would you like me to summarize your booking details before confirmation?"


def build_booking_summary_response(booking_state: Dict[str, Any]) -> str:
    if booking_state.get("room_type"):
        check_in = format_hotel_date(booking_state.get("check_in_date"))
        check_out = format_hotel_date(booking_state.get("check_out_date"))
        nights = booking_state.get("stay_nights") or "Unknown"
        return (
            f"You currently have a {booking_state['room_type']} booked. "
            f"Check-in: {check_in}. Check-out: {check_out}. Stay length: {nights} night(s)."
        )
    return "I can help with that. I still need your room type to confirm what is booked."


def build_booking_confirmation_response(booking_state: Dict[str, Any]) -> str:
    if booking_state.get("missing_fields"):
        return build_progressive_booking_followup(booking_state)
    return (
        "Wonderful. I have your reservation details as: "
        f"Guest: {booking_state.get('guest_name')}, "
        f"Room: {booking_state.get('room_type')}, "
        f"Check-in: {format_hotel_date(booking_state.get('check_in_date'))}, "
        f"Check-out: {format_hotel_date(booking_state.get('check_out_date'))}."
    )


def build_name_acknowledgement_response(booking_state: Dict[str, Any]) -> str:
    if booking_state.get("missing_fields"):
        return build_progressive_booking_followup(booking_state)
    return (
        f"Thank you, {booking_state.get('guest_name')}. "
        f"Here is your booking summary: {booking_state.get('room_type')} from "
        f"{format_hotel_date(booking_state.get('check_in_date'))} to "
        f"{format_hotel_date(booking_state.get('check_out_date'))} for "
        f"{booking_state.get('stay_nights')} night(s). "
        "Reply 'confirm' to finalize your reservation."
    )


def recover_if_misrefused(
    user_message: str,
    model_response: str,
    filtered_history: Optional[List[dict]] = None,
    prompt_builder: Any = None,
) -> str:
    """Recover when the model refuses despite an in-domain request."""
    if not model_response:
        return model_response
    normalized = model_response.strip().lower()
    refusal_marker = "i can only assist with hotel-related inquiries"
    if refusal_marker in normalized:
        if prompt_builder and hasattr(prompt_builder, "get_booking_state"):
            try:
                history = filtered_history or []
                # Only recover refusals when we are clearly inside an active booking
                # and the latest message looks like a booking continuation.
                if not has_booking_context(history):
                    return model_response

                state = prompt_builder.get_booking_state(history, user_message)
                continuation_like = any([
                    is_date_update_message(user_message),
                    is_stay_length_update_message(user_message),
                    is_room_type_update_message(user_message),
                    is_booking_confirmation_message(user_message),
                    is_name_declaration_message(user_message),
                    is_probable_name_reply(user_message, state, history),
                ])

                if not continuation_like:
                    return model_response

                recovered = get_deterministic_booking_response(user_message, history, prompt_builder)
                if recovered:
                    return recovered
                return build_progressive_booking_followup(state)
            except (TypeError, ValueError, AttributeError):
                return IN_DOMAIN_RECOVERY_PROMPT
        return IN_DOMAIN_RECOVERY_PROMPT
    return model_response


def clean_greeting_from_response(response: str, has_history: bool) -> str:
    """
    Remove greeting patterns from assistant responses if conversation history exists.
    
    Args:
        response: The assistant's response text
        has_history: Whether conversation history exists
        
    Returns:
        Cleaned response text
    """
    if not has_history or not response:
        return response
    
    # Remove one leading greeting phrase only; keep boundaries strict to avoid
    # mangling normal words (e.g., "High", "Heyday").
    greeting_patterns = [
        r"^\s*(?:hello|hi|hey)\b(?:\s+[A-Za-z][A-Za-z'\-]*)?[,!\.\s]+",
    ]
    
    cleaned = response
    for pattern in greeting_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Remove leading whitespace after cleaning
    cleaned = cleaned.lstrip()
    
    return cleaned


def sanitize_stream_prefix(prefix: str, has_history: bool) -> str:
    """
    Sanitize only the leading prefix for streaming consistency.

    For ongoing conversations, this strips an initial greeting so users do not
    see greeting tokens that are later removed in stored memory.
    """
    if not has_history:
        return prefix
    return clean_greeting_from_response(prefix, has_history=True)


router = APIRouter()


# Pydantic models for request/response validation
class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    session_id: str = Field(..., description="Unique session identifier")
    message: str = Field(..., min_length=1, description="User message")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    reply: str = Field(..., description="Assistant's response")


@router.post("/sessions")
async def create_session(
    session_manager=Depends(get_session_manager),
    memory_manager=Depends(get_memory_manager),
) -> Dict[str, Any]:
    """
    Create a new conversation session.
    
    Returns:
        Dict containing session_id and metadata
    """
    session_id = session_manager.create_session()
    memory_manager.create_session(session_id)
    session_info = session_manager.get_session(session_id)
    return {
        "session_id": session_id,
        "created_at": str(session_info.get("created_at")),
        "last_active": str(session_info.get("last_active")),
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """
    Retrieve session information.
    
    Args:
        session_id: Unique session identifier
        
    Returns:
        Dict containing session data
    """
    session_manager = get_session_manager()
    memory_manager = get_memory_manager()
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "created_at": str(session.get("created_at")),
        "last_active": str(session.get("last_active")),
        "message_count": memory_manager.get_message_count(session_id),
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> Dict[str, str]:
    """
    Delete a session and its history.
    
    Args:
        session_id: Unique session identifier
        
    Returns:
        Dict with deletion confirmation
    """
    session_manager = get_session_manager()
    deleted = session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str) -> Dict[str, Any]:
    """
    Retrieve conversation history for a session.
    
    Args:
        session_id: Unique session identifier
        
    Returns:
        Dict containing conversation history
    """
    session_manager = get_session_manager()
    memory_manager = get_memory_manager()
    if not session_manager.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    history = memory_manager.get_history(session_id)
    return {
        "session_id": session_id,
        "message_count": len(history),
        "history": history,
    }


@router.post("/api/chat")
async def chat_endpoint(
    request: ChatRequest,
    session_manager=Depends(get_session_manager),
    memory_manager=Depends(get_memory_manager),
    prompt_builder=Depends(get_prompt_builder),
    ollama_client=Depends(get_ollama_client)
) -> ChatResponse:
    """
    REST endpoint for synchronous chat interaction.
    
    Accepts POST requests with JSON payload:
    {
        "session_id": "string",
        "message": "string"
    }
    
    Returns JSON response:
    {
        "reply": "string"
    }
    
    Args:
        request: ChatRequest containing session_id and message
        session_manager: Session manager dependency
        memory_manager: Memory manager dependency
        prompt_builder: Prompt builder dependency
        ollama_client: Ollama client dependency
        
    Returns:
        ChatResponse containing the assistant's reply
        
    Raises:
        HTTPException: 400 for invalid requests, 500 for server errors
    """
    try:
        session_id = request.session_id
        user_message = request.message
        
        # Validate inputs
        if not session_id or not session_id.strip():
            raise HTTPException(
                status_code=400,
                detail="Invalid session_id: must be a non-empty string"
            )
        
        if not user_message or not user_message.strip():
            raise HTTPException(
                status_code=400,
                detail="Invalid message: must be a non-empty string"
            )

        logger.info("REST API: Processing message for session %s: %s...", session_id, user_message[:50])
        
        # Ensure session exists in session manager
        if not session_manager.get_session(session_id):
            session_manager.create_session()
            session_manager.sessions[session_id] = {
                'created_at': datetime.now(),
                'last_active': datetime.now()
            }
            logger.info("Created new session: %s", session_id)
        
        # Ensure memory session exists
        if not memory_manager.session_exists(session_id):
            memory_manager.create_session(session_id)
            logger.info("Created new memory session: %s", session_id)
        
        # Get conversation history
        history = memory_manager.get_history(session_id)
        active_context = memory_manager.get_active_context(history, session_id=session_id)

        # Handle explicit non-hotel turns with a strict deterministic refusal.
        if not is_hotel_related_request(user_message, active_context):
            response = OUT_OF_DOMAIN_REFUSAL
        else:
            # ── RAG: retrieve relevant hotel knowledge ─────────────────
            rag_chunks = await _retrieve_rag_context(user_message, top_k=2)

            # Build prompt with context and RAG chunks
            prompt = prompt_builder.build_prompt(active_context, user_message, rag_chunks=rag_chunks)

            # Generate response from LLM
            logger.info("Generating LLM response for session %s", session_id)
            response = ollama_client.generate(prompt)
        
        # Check if response is an error message
        if response.startswith("Error:"):
            logger.error("LLM error for session %s: %s", session_id, response)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate response: {response}"
            )
        
        # Sanitize response (remove leaked prompt fragments)
        response = sanitize_model_response_text(response)

        # Apply lightweight local fixes only (no extra LLM rewrite calls).
        response = apply_fast_response_fixes(
            user_message=user_message,
            model_response=response,
            filtered_history=active_context,
            prompt_builder=prompt_builder,
        )

        # Clean greeting from response if conversation history exists
        cleaned_response = clean_greeting_from_response(response, len(active_context) > 0)
        
        # Store conversation in memory
        memory_manager.add_message(session_id, "user", user_message)
        memory_manager.add_message(session_id, "assistant", cleaned_response)
        
        logger.info("REST API: Response generated for session %s", session_id)
        
        return ChatResponse(reply=cleaned_response)
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    
    except ValueError as ve:
        logger.error("Validation error in chat endpoint: %s", ve)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {str(ve)}"
        ) from ve
    
    except Exception as e:
        logger.error("Unexpected error in chat endpoint: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        ) from e


async def _stream_text_word_by_word(websocket: WebSocket, text: str, delay_seconds: float = 0.012) -> None:
    """Send text incrementally so the frontend renders a word-by-word effect."""
    if not text:
        return

    chunks = re.findall(r"\S+\s*", text)
    if not chunks:
        await websocket.send_text(text)
        return

    for chunk in chunks:
        await websocket.send_text(chunk)
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)


@router.websocket("/ws/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    WebSocket endpoint for real-time hotel assistant conversation.
    
    Accepts JSON messages with format:
    {
        "session_id": "string",
        "message": "string"
    }
    
    Args:
        websocket: WebSocket connection
        ws_manager: WebSocket connection manager
    """
    session_manager = get_session_manager()
    ollama_client = get_ollama_client()
    memory_manager = get_memory_manager()
    prompt_builder = get_prompt_builder()
    crm_tool = get_crm_tool()
    tool_orchestrator = get_tool_orchestrator()
    
    # Initially accept the connection without session_id
    await websocket.accept()
    logger.info("WebSocket connection accepted, awaiting session_id")
    
    current_session_id = None
    current_user_id = None
    system_prompt_override = None
    
    try:
        while True:
            # Receive message from client
            try:
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # Validate message format
                if not isinstance(message_data, dict):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid message format. Expected JSON object."
                    })
                    continue
                
                session_id = message_data.get("session_id")
                user_message = message_data.get("message")
                msg_type = message_data.get("type")
                provided_user_id = message_data.get("user_id")
                
                # Validate required fields
                if not session_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Missing required field: 'session_id'"
                    })
                    continue

                # Determine stable user id (frontend reconnect sends this first)
                user_id = str(provided_user_id or session_id)

                # Register connection with session_id if first message or session changed
                if current_session_id != session_id:
                    # Use manager methods instead of touching protected lock.
                    if current_session_id and current_session_id in ws_manager.active_connections:
                        ws_manager.active_connections.pop(current_session_id, None)
                        logger.info("Removed old session tracking: %s", current_session_id)

                    await ws_manager.connect(session_id, websocket)
                    
                    # Update current session ID
                    current_session_id = session_id
                    logger.info("WebSocket session updated to: %s", session_id)
                
                # Ensure session exists in session manager
                if not session_manager.get_session(session_id):
                    session_manager.create_session()
                    session_manager.sessions[session_id] = {
                        'created_at': session_manager.sessions.get(session_id, {}).get('created_at'),
                        'last_active': session_manager.sessions.get(session_id, {}).get('last_active')
                    }
                
                # Ensure memory session exists
                if not memory_manager.session_exists(session_id):
                    memory_manager.create_session(session_id)
                
                # Handle init/handshake messages - just acknowledge, don't process
                if (user_message == "__INIT__") or (msg_type == "init"):
                    logger.info("Received init handshake for session %s", session_id)
                    current_user_id = user_id
                    try:
                        system_prompt_override = await crm_tool.get_system_prompt_with_context(
                            current_user_id,
                            base_system_prompt=prompt_builder.system_prompt,
                        )
                    except Exception as crm_prompt_err:  # noqa: BLE001
                        logger.warning("Failed building CRM system prompt (non-fatal): %s", crm_prompt_err)
                        system_prompt_override = None

                    await websocket.send_json({
                        "type": "status",
                        "message": "Session registered"
                    })
                    continue

                # For normal messages, require message content
                if not user_message:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Missing required field: 'message'"
                    })
                    continue
                
                logger.info("Processing message for session %s: %s...", session_id, user_message[:50])
                
                # Send acknowledgment
                await websocket.send_json({
                    "type": "status",
                    "message": "Processing your request..."
                })
                
                # Get conversation history
                history = memory_manager.get_history(session_id)
                active_context = memory_manager.get_active_context(history, session_id=session_id)

                try:
                    current_user_id = current_user_id or user_id
                    await _auto_capture_crm_profile(crm_tool, current_user_id, user_message)

                    memory_manager.add_message(session_id, "user", user_message)
                    current_user_id = current_user_id or user_id
                    await crm_tool.append_interaction(current_user_id, user_message)
                    
                    has_history = len(active_context) > 0
                    if not is_hotel_related_request(user_message, active_context):
                        full_response = OUT_OF_DOMAIN_REFUSAL
                        await websocket.send_json({"type": "token", "content": full_response})
                    else:
                        # ── RAG: retrieve relevant hotel knowledge ───────
                        rag_chunks = await _retrieve_rag_context(user_message, top_k=2)

                        # ── CRM: fetch user info ──────────────────────────
                        crm_result = await crm_tool.get_user_info(current_user_id)
                        user_info = crm_result.get("user") if isinstance(crm_result, dict) else None
                        
                        tools_enabled = tool_orchestrator.should_enable_tools(user_message)
                        prompt = prompt_builder.build_prompt(
                            active_context, 
                            user_message, 
                            rag_chunks=rag_chunks,
                            user_info=user_info,
                            tool_instructions=tool_orchestrator.get_tool_system_prompt() if tools_enabled else None,
                            system_prompt_override=system_prompt_override,
                        )

                        # For normal Q&A: stream immediately for low TTFT.
                        # For tool-intent turns: capture output first, execute tool, then narrate.
                        full_response = ""
                        if not tools_enabled:
                            async for token in ollama_client.generate_stream(prompt):
                                if not token:
                                    continue
                                if token.startswith("Error:"):
                                    raise RuntimeError(token)
                                full_response += token
                                await websocket.send_json({"type": "token", "content": token})
                        else:
                            async for token in ollama_client.generate_stream(prompt):
                                if not token:
                                    continue
                                if token.startswith("Error:"):
                                    raise RuntimeError(token)
                                full_response += token

                            executed_tools = await tool_orchestrator.execute_tool_calls(full_response, user_message=user_message)
                            if executed_tools:
                                logger.info("Tool results detected, using deterministic narration")
                                full_response = _format_tool_narration(executed_tools)
                                await websocket.send_json({"type": "token", "content": full_response})
                            elif _looks_like_tool_json_only(full_response):
                                full_response = "I can help with hotel policies. Please ask your question again in plain text."
                                await websocket.send_json({"type": "token", "content": full_response})
                            else:
                                await websocket.send_json({"type": "token", "content": full_response})

                    if not full_response:
                        raise RuntimeError("Empty response from model")

                    full_response = sanitize_model_response_text(full_response)
                    full_response = apply_fast_response_fixes(
                        user_message=user_message,
                        model_response=full_response,
                        filtered_history=active_context,
                        prompt_builder=prompt_builder,
                    )
                    cleaned_response = clean_greeting_from_response(full_response, has_history)

                    await websocket.send_json({"type": "done", "message": "Response complete"})

                    memory_manager.add_message(session_id, "assistant", cleaned_response)
                    logger.info("Response completed for session %s", session_id)

                except (RuntimeError, ValueError, TypeError, OSError) as stream_error:
                    logger.error("Error during response generation: %s", stream_error)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Error generating response: {str(stream_error)}"
                    })
            
            except json.JSONDecodeError as json_error:
                logger.error("JSON decode error: %s", json_error)
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
                continue
            
            except (RuntimeError, ValueError, TypeError, KeyError, OSError) as msg_error:
                logger.error("Error processing message: %s", msg_error)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error processing message: {str(msg_error)}"
                })
                continue
    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session: %s", current_session_id)
        if current_session_id:
            await ws_manager.disconnect(current_session_id)
    
    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.error("Unexpected error in WebSocket endpoint: %s", e)
        if current_session_id:
            await ws_manager.disconnect(current_session_id)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Unexpected error: {str(e)}"
            })
        except RuntimeError:
            pass


async def _stream_tts_for_text(
    websocket: WebSocket,
    piper_tts,
    fragment: str,
    sequence_start: int
) -> int:
    """
    Stream synthesized audio chunks for a single text fragment.

    Returns:
        int: Next sequence id after the streamed chunks.
    """
    seq = sequence_start
    async for audio_chunk_b64 in piper_tts.synthesize_chunked_b64(fragment):
        await websocket.send_json({
            "type": "audio_chunk",
            "audio": audio_chunk_b64,
            "format": "wav",
            "sequence": seq,
        })
        seq += 1
    return seq


@router.websocket("/ws/voice_chat")
async def websocket_voice_chat_endpoint(
    websocket: WebSocket,
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    WebSocket endpoint for voice-first conversational interaction.

    Pipeline:
    Audio input -> Mooshine ASR -> Conversation manager/prompt -> LLM stream
    -> sentence-buffered Piper TTS -> audio chunks back to browser.

    Message contract:
    - JSON init: {"type":"init","session_id":"..."}
    - Binary frames: microphone/uploaded audio chunks
    - JSON control: {"type":"audio_end","session_id":"...","mime_type":"audio/webm"}

    Outbound events:
    - transcript, token, done, audio_chunk, audio_done, status, error.
    """
    # Core dependencies are the same as /ws/chat to preserve existing
    # conversation state, history memory, and prompt orchestration behavior.
    session_manager = get_session_manager()
    ollama_client = get_ollama_client()
    memory_manager = get_memory_manager()
    prompt_builder = get_prompt_builder()
    crm_tool = get_crm_tool()
    tool_orchestrator = get_tool_orchestrator()
    audio_converter = get_audio_converter()
    moonshine_asr = get_moonshine_asr()
    piper_tts = get_piper_tts()

    await websocket.accept()
    current_session_id = None
    current_connection_key = None
    current_user_id = None
    system_prompt_override = None
    buffered_audio = bytearray()
    current_mime_type = "audio/webm"

    logger.info("Voice WebSocket accepted, waiting for init")

    async def register_session_if_needed(new_session_id: str):
        nonlocal current_session_id, current_connection_key
        new_connection_key = f"voice:{new_session_id}"

        if current_session_id == new_session_id:
            return

        # Voice and text sockets share the same manager instance, so we
        # namespace voice keys to avoid closing `/ws/chat` connections.
        if current_connection_key in ws_manager.active_connections:
            ws_manager.active_connections.pop(current_connection_key, None)

        await ws_manager.connect(new_connection_key, websocket)

        current_session_id = new_session_id
        current_connection_key = new_connection_key
        logger.info("Voice session updated to: %s", current_session_id)

    async def ensure_state_for_session(session_id: str):
        # Keep session manager behavior aligned with existing websocket text flow.
        if not session_manager.get_session(session_id):
            session_manager.create_session()
            session_manager.sessions[session_id] = {
                'created_at': session_manager.sessions.get(session_id, {}).get('created_at'),
                'last_active': session_manager.sessions.get(session_id, {}).get('last_active')
            }

        if not memory_manager.session_exists(session_id):
            memory_manager.create_session(session_id)

    async def process_audio_turn(session_id: str, audio_bytes: bytes, mime_type: str):
        if not audio_bytes:
            await websocket.send_json({
                "type": "error",
                "message": "No audio data received"
            })
            return

        await websocket.send_json({
            "type": "status",
            "message": "Transcribing audio..."
        })

        source_ext = (mime_type.split("/")[-1] if mime_type and "/" in mime_type else "webm").split(";")[0]
        wav_audio = await audio_converter.to_wav_16k(audio_bytes, source_ext)
        transcript = await moonshine_asr.transcribe(wav_audio)

        if not transcript:
            await websocket.send_json({
                "type": "error",
                "message": "ASR produced empty transcription"
            })
            return

        await websocket.send_json({
            "type": "transcript",
            "text": transcript,
            "final": True
        })

        history = memory_manager.get_history(session_id)
        active_context = memory_manager.get_active_context(history, session_id=session_id)

        # ── CRM: fetch user info ──────────────────────────
        nonlocal current_user_id
        current_user_id = current_user_id or session_id
        await _auto_capture_crm_profile(crm_tool, current_user_id, transcript)

        crm_result = await crm_tool.get_user_info(current_user_id)
        user_info = crm_result.get("user") if isinstance(crm_result, dict) else None

        # Apply the same domain guardrail as text chat.
        if not is_hotel_related_request(transcript, active_context):
            full_response = OUT_OF_DOMAIN_REFUSAL
            memory_manager.add_message(session_id, "user", transcript)
            memory_manager.add_message(session_id, "assistant", full_response)
            await websocket.send_json({"type": "token", "content": full_response})
            await websocket.send_json({"type": "done", "message": "Response complete"})
            await websocket.send_json({"type": "audio_done", "chunks": 0})
            return

        # ── RAG: retrieve relevant hotel knowledge (match /ws/chat behavior) ───────
        rag_chunks = await _retrieve_rag_context(transcript, top_k=2)

        prompt = prompt_builder.build_prompt(
            active_context, 
            transcript,
            rag_chunks=rag_chunks,
            user_info=user_info,
            tool_instructions=tool_orchestrator.get_tool_system_prompt(),
            system_prompt_override=system_prompt_override,
        )
        
        try:
            memory_manager.add_message(session_id, "user", transcript)
            await crm_tool.append_interaction(current_user_id, transcript)
        except Exception as crm_err:
            logger.warning(f"CRM interaction logging failed: {crm_err}")

        # Low-latency voice output with deterministic chunking:
        # - stream text tokens immediately to UI
        # - first audio chunk is emitted at first sentence-ending punctuation
        # - second chunk (optional) contains the remaining response
        # - total chunks per reply: max 2
        full_response = ""
        has_history = len(active_context) > 0
        prefix_buffer = ""
        prefix_released = not has_history
        first_audio_buffer = ""
        trailing_audio_buffer = ""
        audio_seq = 0
        first_audio_task = None
        first_audio_started = False

        await websocket.send_json({
            "type": "status",
            "message": "Generating response..."
        })

        async for token in ollama_client.generate_stream(prompt):
            if not token:
                continue
            full_response += token

            emit_text = ""
            if prefix_released:
                emit_text = token
            else:
                prefix_buffer += token
                if len(prefix_buffer) >= 32 or any(ch in prefix_buffer for ch in [" ", ",", ".", "!", "?", "\n"]):
                    emit_text = sanitize_stream_prefix(prefix_buffer, has_history)
                    prefix_buffer = ""
                    prefix_released = True

            if emit_text:
                await websocket.send_json({
                    "type": "token",
                    "content": emit_text
                })

            if not first_audio_started:
                first_audio_buffer += emit_text

                # Start chunk-1 at the first complete sentence boundary.
                split_idx = -1
                for punct in (".", "?", "!", "\n"):
                    idx = first_audio_buffer.find(punct)
                    if idx != -1 and (split_idx == -1 or idx < split_idx):
                        split_idx = idx

                if split_idx != -1:
                    first_fragment = first_audio_buffer[: split_idx + 1].strip()
                    trailing_audio_buffer = first_audio_buffer[split_idx + 1 :] + trailing_audio_buffer

                    if not first_fragment:
                        continue

                    first_audio_task = asyncio.create_task(
                        _stream_tts_for_text(websocket, piper_tts, first_fragment, audio_seq)
                    )
                    first_audio_buffer = ""
                    first_audio_started = True
            else:
                trailing_audio_buffer += emit_text

        if not prefix_released and prefix_buffer:
            emit_text = sanitize_stream_prefix(prefix_buffer, has_history)
            if emit_text:
                await websocket.send_json({
                    "type": "token",
                    "content": emit_text
                })
                if not first_audio_started:
                    first_audio_buffer += emit_text
                else:
                    trailing_audio_buffer += emit_text

        if first_audio_started and first_audio_task is not None:
            audio_seq = await first_audio_task
            remaining = (first_audio_buffer + trailing_audio_buffer).strip()
            if remaining:
                audio_seq = await _stream_tts_for_text(websocket, piper_tts, remaining, audio_seq)
        else:
            # Fallback when response is too short to trigger early synthesis.
            only_fragment = first_audio_buffer.strip() or full_response.strip()
            if only_fragment:
                audio_seq = await _stream_tts_for_text(websocket, piper_tts, only_fragment, audio_seq)

        # ── TOOL ORCHESTRATION ──────────────────────────
        executed_tools = await tool_orchestrator.execute_tool_calls(full_response, user_message=transcript)
        if executed_tools:
            logger.info("Voice: Tool results detected, using deterministic narration")
            full_response = _format_tool_narration(executed_tools)
            if full_response.strip():
                await websocket.send_json({"type": "token", "content": full_response})
                audio_seq = await _stream_tts_for_text(websocket, piper_tts, full_response, audio_seq)

        full_response = repair_greeting_opener_with_llm(
            transcript,
            full_response,
            ollama_client,
        )
        full_response = sanitize_model_response_text(full_response)
        cleaned_response = clean_greeting_from_response(full_response, has_history)

        memory_manager.add_message(session_id, "assistant", cleaned_response)

        await websocket.send_json({"type": "done", "message": "Response complete"})
        await websocket.send_json({"type": "audio_done", "chunks": audio_seq})

    try:
        while True:
            packet = await websocket.receive()

            if "bytes" in packet and packet["bytes"] is not None:
                # Binary frames are audio chunks from live mic or upload stream.
                buffered_audio.extend(packet["bytes"])
                continue

            if "text" not in packet or packet["text"] is None:
                continue

            try:
                message_data = json.loads(packet["text"])
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON format"})
                continue

            if not isinstance(message_data, dict):
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                continue

            msg_type = message_data.get("type", "")
            session_id = message_data.get("session_id")
            user_id = message_data.get("user_id") or session_id

            if not session_id:
                await websocket.send_json({"type": "error", "message": "Missing session_id"})
                continue

            await register_session_if_needed(session_id)
            await ensure_state_for_session(session_id)

            if msg_type == "init":
                current_user_id = str(user_id)
                try:
                    system_prompt_override = await crm_tool.get_system_prompt_with_context(
                        current_user_id,
                        base_system_prompt=prompt_builder.system_prompt,
                    )
                except Exception as crm_prompt_err:  # noqa: BLE001
                    logger.warning("Failed building CRM system prompt (non-fatal): %s", crm_prompt_err)
                    system_prompt_override = None
                await websocket.send_json({"type": "status", "message": "Voice session registered"})
                continue

            if msg_type == "audio_chunk_meta":
                # Metadata can be sent ahead of binary chunks to identify mime/container.
                current_mime_type = message_data.get("mime_type", current_mime_type)
                continue

            if msg_type == "audio_end":
                current_mime_type = message_data.get("mime_type", current_mime_type)
                audio_payload = bytes(buffered_audio)
                buffered_audio.clear()

                try:
                    await process_audio_turn(session_id, audio_payload, current_mime_type)
                except (RuntimeError, ValueError, TypeError, OSError) as turn_error:
                    logger.error("Voice turn failed for %s: %s", session_id, turn_error, exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Voice pipeline error: {turn_error}"
                    })
                continue

            await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected for session: %s", current_session_id)
        if current_connection_key:
            await ws_manager.disconnect(current_connection_key)
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        logger.error("Unexpected voice websocket error: %s", exc, exc_info=True)
        if current_connection_key:
            await ws_manager.disconnect(current_connection_key)
        try:
            await websocket.send_json({"type": "error", "message": f"Unexpected error: {exc}"})
        except RuntimeError:
            pass

