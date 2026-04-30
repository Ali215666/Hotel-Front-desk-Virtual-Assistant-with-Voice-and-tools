from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

try:
    from icalendar import Calendar, Event
except ImportError:  # pragma: no cover
    Calendar = None
    Event = None

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
CALENDAR_DIR = ROOT_DIR / "calendars"
BOOKINGS_JSON = CALENDAR_DIR / "bookings.json"

ADD_BOOKING_TO_CALENDAR_SCHEMA: Dict[str, Any] = {
    "name": "add_booking_to_calendar",
    "description": "Create a guest booking calendar event file (.ics) and store a JSON booking record.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "user_id": {"type": "string", "description": "Unique identifier for the guest session."},
            "room_type": {"type": "string", "description": "Booked room category."},
            "check_in": {"type": "string", "description": "Check-in date in YYYY-MM-DD format."},
            "check_out": {"type": "string", "description": "Check-out date in YYYY-MM-DD format."},
        },
        "required": ["user_id", "room_type", "check_in", "check_out"],
    },
}


def _write_booking_files(record: Dict[str, Any], ics_filename: str) -> None:
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)

    if BOOKINGS_JSON.exists():
        try:
            existing = json.loads(BOOKINGS_JSON.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:  # noqa: BLE001
            existing = []
    else:
        existing = []

    existing.append(record)
    BOOKINGS_JSON.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    calendar = Calendar()
    calendar.add("prodid", "-//Hotel Front Desk Assistant//EN")
    calendar.add("version", "2.0")

    event = Event()
    event.add("uid", record["event_id"])
    event.add("summary", record["summary"])
    event.add("description", record["description"])
    event.add("dtstart", datetime.strptime(record["check_in"], "%Y-%m-%d").date())
    event.add("dtend", datetime.strptime(record["check_out"], "%Y-%m-%d").date())
    event.add("dtstamp", datetime.utcnow())
    calendar.add_component(event)

    (CALENDAR_DIR / ics_filename).write_bytes(calendar.to_ical())


async def add_booking_to_calendar(
    user_id: str,
    room_type: str,
    check_in: str,
    check_out: str,
    guest_name: str = "Guest",
) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        if Calendar is None or Event is None:
            return {
                "ok": False,
                "message": "Calendar service is unavailable because the icalendar package is not installed.",
            }

        check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
        check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()
        if check_out_date <= check_in_date:
            return {"ok": False, "message": "Check-out date must be after check-in date."}

        event_id = str(uuid4())
        safe_user = (user_id or "guest").strip() or "guest"
        ics_filename = f"{safe_user}_{event_id}.ics"
        summary = f"{guest_name} - {room_type} booking"

        record = {
            "event_id": event_id,
            "user_id": safe_user,
            "guest_name": guest_name,
            "room_type": room_type,
            "check_in": check_in,
            "check_out": check_out,
            "summary": summary,
            "description": f"Hotel stay for {guest_name} in a {room_type} room.",
            "ics_file_path": str((CALENDAR_DIR / ics_filename).resolve()),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

        await asyncio.to_thread(_write_booking_files, record, ics_filename)

        return {
            "ok": True,
            "summary": summary,
            "message": (
                f"Your booking has been added to the calendar for {check_in} to {check_out}. "
                "Use the download path to add it to your calendar app."
            ),
            "download_path": record["ics_file_path"],
            "check_in": check_in,
            "check_out": check_out,
            "room_type": room_type,
        }
    except ValueError:
        return {"ok": False, "message": "Please provide check-in and check-out in YYYY-MM-DD format."}
    except Exception as exc:  # noqa: BLE001
        logger.exception("add_booking_to_calendar failed: %s", exc)
        return {"ok": False, "message": "I could not create the calendar event right now. Please try again."}
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("Tool add_booking_to_calendar executed in %.2fms", elapsed_ms)
