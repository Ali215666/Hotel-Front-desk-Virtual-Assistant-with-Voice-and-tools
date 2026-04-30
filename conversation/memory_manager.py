"""
Thread-safe in-memory session manager for storing conversation history.
"""

import re
import threading
from typing import Dict, List, Literal, Optional


class MemoryManager:
    """Thread-safe in-memory session manager for conversation history."""
    
    def __init__(self):
        """Initialize the memory manager with thread-safe storage."""
        self._sessions: Dict[str, List[dict]] = {}
        self._session_summaries: Dict[str, str] = {}
        self._summary_last_index: Dict[str, int] = {}
        self._session_booking_slots: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max_recent_messages = 6
        self._max_context_chars = 1000
        self._max_summary_lines = 10
        self._max_fact_chars = 180

    def _new_booking_slots(self) -> dict:
        return {
            "guest_name": None,
            "arrival_date": None,
            "guests_count": None,
            "room_category": None,
            "special_requests": [],
        }

    def _extract_booking_slots(self, text: str) -> dict:
        normalized = self._normalize_text(text)
        lowered = normalized.lower()
        extracted = {}

        # Guest name
        name_patterns = [
            r"\bmy name is\s+([a-zA-Z][a-zA-Z\s\-']{1,40})",
            r"\bi am\s+([a-zA-Z][a-zA-Z\s\-']{1,40})",
        ]
        for pattern in name_patterns:
            m = re.search(pattern, normalized, re.IGNORECASE)
            if m:
                name = self._normalize_text(m.group(1)).strip(" .,!?")
                if name and len(name.split()) <= 4:
                    extracted["guest_name"] = name.title()
                    break

        # Arrival date
        date_patterns = [
            r"\barrival date is\s+([a-zA-Z0-9\s\-/]{3,30})",
            r"\barriv(?:e|ing)\s+on\s+([a-zA-Z0-9\s\-/]{3,30})",
            r"\bcheck[-\s]?in\s+(?:date\s+)?(?:is\s+)?([a-zA-Z0-9\s\-/]{3,30})",
        ]
        for pattern in date_patterns:
            m = re.search(pattern, normalized, re.IGNORECASE)
            if m:
                extracted["arrival_date"] = self._normalize_text(m.group(1)).strip(" .,!?")
                break

        # Guests count
        guest_patterns = [
            r"\bwe are\s+(\d{1,2})\s*(?:guests?|people|persons?)?",
            r"\b(\d{1,2})\s*(?:guests?|people|persons?)\b",
            r"\bfor\s+(\d{1,2})\b",
        ]
        for pattern in guest_patterns:
            m = re.search(pattern, lowered)
            if m:
                extracted["guests_count"] = int(m.group(1))
                break

        # Room category
        categories = ("standard", "deluxe", "suite", "family", "executive", "single", "double")
        for category in categories:
            if re.search(rf"\b{category}\b", lowered):
                extracted["room_category"] = category
                break

        # Special requests
        if any(k in lowered for k in ("need", "require", "prefer", "allergy", "wheelchair", "accessible")):
            extracted["special_request"] = self._clip_text(normalized, 90)

        return extracted

    def _update_booking_slots(self, session_id: str, role: str, content: str) -> None:
        if role != "user":
            return

        slots = self._session_booking_slots.get(session_id)
        if slots is None:
            slots = self._new_booking_slots()
            self._session_booking_slots[session_id] = slots

        extracted = self._extract_booking_slots(content)
        if not extracted:
            return

        for key in ("guest_name", "arrival_date", "guests_count", "room_category"):
            if key in extracted and extracted[key]:
                slots[key] = extracted[key]

        if extracted.get("special_request"):
            req = extracted["special_request"]
            if req not in slots["special_requests"]:
                slots["special_requests"].append(req)

            slots["special_requests"] = slots["special_requests"][-3:]

    def _booking_slots_context(self, session_id: str) -> Optional[str]:
        slots = self._session_booking_slots.get(session_id)
        if not slots:
            return None

        details = []
        if slots.get("guest_name"):
            details.append(f"- Guest name: {slots['guest_name']}")
        if slots.get("arrival_date"):
            details.append(f"- Arrival date: {slots['arrival_date']}")
        if slots.get("guests_count"):
            details.append(f"- Guests count: {slots['guests_count']}")
        if slots.get("room_category"):
            details.append(f"- Room category: {slots['room_category']}")
        if slots.get("special_requests"):
            details.append(f"- Special requests: {' | '.join(slots['special_requests'])}")

        if not details:
            return None

        return "[Known booking details]\n" + "\n".join(details)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    def _clip_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    def _extract_key_facts(self, messages: List[dict], limit: int = 8) -> List[str]:
        """
        Extract important conversation facts using lightweight heuristics.

        This avoids extra model calls and keeps summarization fully local.
        """
        important_terms = (
            "name",
            "check-in",
            "check in",
            "check-out",
            "check out",
            "arrival",
            "departure",
            "reservation",
            "booking",
            "room",
            "bed",
            "wifi",
            "parking",
            "breakfast",
            "airport",
            "invoice",
            "payment",
            "late",
            "early",
            "allergy",
            "diet",
            "accessible",
            "wheelchair",
            "policy",
            "cancel",
            "cancellation",
        )

        facts: List[str] = []
        seen = set()

        for msg in messages:
            role = msg.get("role", "user")
            content = self._normalize_text(msg.get("content", ""))
            if not content:
                continue

            lowered = content.lower()
            is_important = any(term in lowered for term in important_terms)

            if not is_important and role == "assistant":
                # Keep assistant lines stricter to avoid bloating summary.
                continue

            line = f"Guest: {content}" if role == "user" else f"Assistant: {content}"
            line = self._clip_text(line, self._max_fact_chars)
            if line not in seen:
                seen.add(line)
                facts.append(line)

            if len(facts) >= limit:
                break

        if facts:
            return facts

        # Fallback: retain a tiny snapshot when no keyword matched.
        for msg in messages[-4:]:
            role = msg.get("role", "user")
            content = self._normalize_text(msg.get("content", ""))
            if not content:
                continue
            line = f"Guest: {content}" if role == "user" else f"Assistant: {content}"
            line = self._clip_text(line, self._max_fact_chars)
            if line not in seen:
                seen.add(line)
                facts.append(line)

        return facts[:limit]

    def _merge_summary_lines(self, existing_summary: str, new_lines: List[str], max_lines: int = 12) -> str:
        existing_lines = []
        if existing_summary:
            for line in existing_summary.splitlines():
                clean = self._normalize_text(line.lstrip("- "))
                if clean:
                    existing_lines.append(clean)

        merged = []
        seen = set()

        for line in existing_lines + [self._normalize_text(l) for l in new_lines]:
            if not line or line in seen:
                continue
            seen.add(line)
            merged.append(line)

        merged = merged[-max_lines:]
        return "\n".join(f"- {line}" for line in merged)

    def _update_session_summary(self, session_id: str, history: List[dict], summarize_upto: int) -> None:
        last_idx = self._summary_last_index.get(session_id, 0)
        if summarize_upto <= last_idx:
            return

        new_slice = history[last_idx:summarize_upto]
        if not new_slice:
            return

        new_facts = self._extract_key_facts(new_slice)
        if new_facts:
            existing = self._session_summaries.get(session_id, "")
            self._session_summaries[session_id] = self._merge_summary_lines(
                existing,
                new_facts,
                max_lines=self._max_summary_lines,
            )

        self._summary_last_index[session_id] = summarize_upto
    
    def create_session(self, session_id: str) -> None:
        """
        Create a new session with empty history.
        
        Args:
            session_id: Unique session identifier
        """
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
                self._session_summaries[session_id] = ""
                self._summary_last_index[session_id] = 0
                self._session_booking_slots[session_id] = self._new_booking_slots()
    
    def add_message(self, session_id: str, role: Literal["user", "assistant"], content: str) -> None:
        """
        Add a message to the session history.
        
        Args:
            session_id: Session identifier
            role: Message role ("user" or "assistant")
            content: Message content
        """
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            if session_id not in self._session_booking_slots:
                self._session_booking_slots[session_id] = self._new_booking_slots()
            
            message = {
                "role": role,
                "content": content
            }
            self._sessions[session_id].append(message)
            self._update_booking_slots(session_id, role, content)
    
    def get_history(self, session_id: str) -> List[dict]:
        """
        Retrieve full conversation history for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List[dict]: List of message dictionaries with 'role' and 'content'
        """
        with self._lock:
            # Return a copy to prevent external modification
            return list(self._sessions.get(session_id, []))
    
    def get_active_context(self, history: List[dict], session_id: Optional[str] = None) -> List[dict]:
        """
        Filter conversation history to keep only last 6 dialogue turns.
        
        Args:
            history: Full conversation history
            
        Returns:
            List[dict]: Filtered history with last 6 turns (12 messages max)
        """
        if not history:
            return []
        
        # Keep up to last 6 turns = 12 messages, then trim by char budget.
        max_messages = self._max_recent_messages
        
        # If session-aware call, maintain and prepend rolling summary.
        summary_text = ""
        booking_text = None
        if session_id is not None:
            with self._lock:
                if session_id not in self._sessions:
                    self._sessions[session_id] = list(history)
                    self._session_summaries[session_id] = ""
                    self._summary_last_index[session_id] = 0
                    self._session_booking_slots[session_id] = self._new_booking_slots()

                summarize_upto = max(0, len(history) - max_messages)
                self._update_session_summary(session_id, history, summarize_upto)
                summary_text = self._session_summaries.get(session_id, "")
                booking_text = self._booking_slots_context(session_id)
        elif len(history) > max_messages:
            # Backward-compatible fallback when session_id is not available.
            summary_lines = self._extract_key_facts(history[:-max_messages])
            summary_text = self._merge_summary_lines("", summary_lines, max_lines=self._max_summary_lines)

        active = history if len(history) <= max_messages else history[-max_messages:]

        # Hard cap context payload growth to keep latency stable.
        budget = self._max_context_chars
        compact_active: List[dict] = []
        for msg in reversed(active):
            content = self._normalize_text(msg.get("content", ""))
            if not content:
                continue
            role = msg.get("role", "user")
            required = len(content) + 12
            if compact_active and required > budget:
                continue
            if required > budget:
                content = self._clip_text(content, max(24, budget - 12))
                required = len(content) + 12
            budget -= required
            compact_active.append({"role": role, "content": content})
            if budget <= 0:
                break
        compact_active.reverse()

        prefix_messages: List[dict] = []

        if booking_text:
            booking_message = {"role": "assistant", "content": booking_text}
            booking_len = len(booking_message["content"])
            if booking_len <= budget:
                prefix_messages.append(booking_message)
                budget -= booking_len

        if summary_text:
            summary_message = {
                "role": "assistant",
                "content": "[Earlier important context]\n" + summary_text,
            }
            summary_len = len(summary_message["content"])
            if summary_len <= budget:
                prefix_messages.append(summary_message)

        if prefix_messages:
            return prefix_messages + compact_active

        return compact_active
    
    def reset_session(self, session_id: str) -> None:
        """
        Clear all messages from a session.
        
        Args:
            session_id: Session identifier
        """
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = []
            self._session_summaries[session_id] = ""
            self._summary_last_index[session_id] = 0
            self._session_booking_slots[session_id] = self._new_booking_slots()
    
    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists.
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session exists
        """
        with self._lock:
            return session_id in self._sessions
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session entirely.
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session was deleted, False if not found
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._session_summaries.pop(session_id, None)
                self._summary_last_index.pop(session_id, None)
                self._session_booking_slots.pop(session_id, None)
                return True
            return False
    
    def get_message_count(self, session_id: str) -> int:
        """
        Get the number of messages in a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            int: Number of messages in the session
        """
        with self._lock:
            return len(self._sessions.get(session_id, []))
    
    # Legacy compatibility methods
    def add_interaction(self, session_id: str, user_message: str, ai_response: str) -> None:
        """
        Legacy method: Add a user-assistant interaction pair.
        
        Args:
            session_id: Session identifier
            user_message: User's input message
            ai_response: AI's generated response
        """
        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", ai_response)
    
    def clear_history(self, session_id: str) -> None:
        """
        Legacy method: Clear conversation history for a session.
        
        Args:
            session_id: Session identifier
        """
        self.reset_session(session_id)
