from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


CALCULATE_ROOM_COST_SCHEMA: Dict[str, Any] = {
    "name": "calculate_room_cost",
    "description": "Calculate hotel room cost for a stay window and return a concise pricing breakdown.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "room_type": {"type": "string", "description": "Room category such as Standard, Deluxe, or Suite."},
            "check_in": {"type": "string", "description": "Check-in date in YYYY-MM-DD format."},
            "check_out": {"type": "string", "description": "Check-out date in YYYY-MM-DD format."},
            "num_guests": {"type": "integer", "description": "Number of guests staying in the room.", "minimum": 1},
        },
        "required": ["room_type", "check_in", "check_out"],
    },
}


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


async def calculate_room_cost(
    room_type: str,
    check_in: str,
    check_out: str,
    num_guests: Optional[int] = None,
) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        room_type_clean = (room_type or "").strip()
        if not room_type_clean:
            return {"ok": False, "message": "Please provide a room type to calculate the stay cost."}

        room_prices = {
            "standard": 70.0,
            "deluxe": 150.0,
            "suite": 300.0,
        }
        room_key = room_type_clean.lower()
        if room_key not in room_prices:
            return {"ok": False, "message": "Room type must be Standard, Deluxe, or Suite."}
        price_per_night = room_prices[room_key]

        check_in_date = _parse_date(check_in)
        check_out_date = _parse_date(check_out)
        nights = (check_out_date - check_in_date).days
        if nights <= 0:
            return {"ok": False, "message": "Check-out must be after check-in to calculate room cost."}

        guests = int(num_guests) if num_guests is not None else 1
        if guests <= 0:
            return {"ok": False, "message": "Number of guests must be at least 1."}

        base_total = float(price_per_night) * nights
        surcharge_rate = 0.0
        surcharge_reason = None

        if room_type_clean.lower() == "suite" and guests > 2:
            surcharge_rate = 0.15
            surcharge_reason = "Suite occupancy above 2 guests"

        surcharge_amount = round(base_total * surcharge_rate, 2)
        total_cost = round(base_total + surcharge_amount, 2)

        narration = (
            f"Your {nights}-night stay in a {room_type_clean} room will cost ${total_cost:.2f}."
            if surcharge_amount == 0
            else (
                f"Your {nights}-night stay in a {room_type_clean} room will cost ${total_cost:.2f}, "
                f"including a ${surcharge_amount:.2f} occupancy surcharge."
            )
        )

        return {
            "ok": True,
            "room_type": room_type_clean,
            "nights": nights,
            "price_per_night": round(price_per_night, 2),
            "base_total": round(base_total, 2),
            "surcharge_amount": surcharge_amount,
            "surcharge_reason": surcharge_reason,
            "total_cost": total_cost,
            "message": narration,
        }
    except ValueError:
        return {"ok": False, "message": "Dates must follow YYYY-MM-DD format, and numeric fields must be valid."}
    except Exception as exc:  # noqa: BLE001
        logger.exception("calculate_room_cost failed: %s", exc)
        return {"ok": False, "message": "I could not calculate the room cost right now. Please try again."}
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("Tool calculate_room_cost executed in %.2fms", elapsed_ms)
