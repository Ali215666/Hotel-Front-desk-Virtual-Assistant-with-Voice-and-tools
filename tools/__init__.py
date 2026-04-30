from .calculator import CALCULATE_ROOM_COST_SCHEMA, calculate_room_cost
from .calendar_tool import ADD_BOOKING_TO_CALENDAR_SCHEMA, add_booking_to_calendar
from .crm import CRM_TOOL_SCHEMAS, get_user_info, store_user_info, update_user_info
from .weather import GET_HOTEL_WEATHER_SCHEMA, get_hotel_weather

TOOL_SCHEMAS = [
    *[
        {
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema.get("input_schema", schema.get("parameters", {})),
        }
        for schema in CRM_TOOL_SCHEMAS
    ],
    CALCULATE_ROOM_COST_SCHEMA,
    ADD_BOOKING_TO_CALENDAR_SCHEMA,
    GET_HOTEL_WEATHER_SCHEMA,
]

__all__ = [
    "TOOL_SCHEMAS",
    "get_user_info",
    "store_user_info",
    "update_user_info",
    "calculate_room_cost",
    "add_booking_to_calendar",
    "get_hotel_weather",
]
