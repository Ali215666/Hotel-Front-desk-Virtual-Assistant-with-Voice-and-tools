import json
import logging
import re
import time
from typing import Dict, Any, Optional, List
from .crm import (
    CRMTool,
    get_user_info as tool_get_user_info,
    store_user_info as tool_store_user_info,
    update_user_info as tool_update_user_info,
)
from .calculator import calculate_room_cost as tool_calculate_room_cost
from .calendar_tool import add_booking_to_calendar as tool_add_booking_to_calendar
from .weather import get_hotel_weather as tool_get_hotel_weather
from . import TOOL_SCHEMAS

logger = logging.getLogger(__name__)

def _extract_json_objects(text: str) -> List[str]:
    """
    Extract top-level JSON object substrings from free-form text.
    Handles nested braces and braces inside strings.
    """
    if not text:
        return []

    out: List[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False

    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
            continue

        if ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    out.append(text[start : i + 1])
                    start = -1
            continue

    return out

class ToolOrchestrator:
    def infer_relevant_tools(self, user_message: Optional[str]) -> List[str]:
        if not user_message:
            return []
        text = user_message.lower()
        tools: List[str] = []

        has_dates = bool(re.search(r"\d{4}-\d{2}-\d{2}", text))
        has_room = any(k in text for k in ["room", "standard", "deluxe", "suite"])

        if has_dates and has_room and any(k in text for k in ["cost", "price", "how much", "calculate"]):
            tools.append("calculate_room_cost")

        if has_dates and any(k in text for k in ["book", "booking", "reserve", "reservation"]):
            tools.append("add_booking_to_calendar")

        if has_dates and any(k in text for k in ["weather", "forecast", "temperature", "rain", "there"]):
            tools.append("get_hotel_weather")

        if any(k in text for k in ["my name", "my email", "my phone", "who am i"]):
            tools.extend(["get_user_info", "store_user_info", "update_user_info"])

        return tools

    def should_enable_tools(self, user_message: Optional[str]) -> bool:
        return len(self.infer_relevant_tools(user_message)) > 0

    def _is_tool_call_appropriate(self, tool_name: str, user_message: Optional[str]) -> bool:
        """
        Guardrail to avoid unnecessary tool calls if model emits spurious JSON.
        """
        if not user_message:
            return True
        text = user_message.lower()

        if tool_name == "calculate_room_cost":
            has_cost_intent = any(k in text for k in ["cost", "price", "how much", "calculate"])
            has_room_intent = any(k in text for k in ["room", "standard", "deluxe", "suite"])
            has_dates = bool(re.search(r"\d{4}-\d{2}-\d{2}", text))
            return has_cost_intent and has_room_intent and has_dates

        if tool_name == "add_booking_to_calendar":
            has_booking_intent = any(k in text for k in ["book", "booking", "reserve", "reservation"])
            has_dates = bool(re.search(r"\d{4}-\d{2}-\d{2}", text))
            return has_booking_intent and has_dates

        if tool_name == "get_hotel_weather":
            has_weather_intent = any(k in text for k in ["weather", "forecast", "temperature", "rain", "there"])
            has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", text))
            return has_weather_intent and has_date

        if tool_name in {"get_user_info", "store_user_info", "update_user_info"}:
            return any(k in text for k in ["my name", "my email", "my phone", "who am i", "profile", "preferences"])

        return True

    """
    Orchestrates tool discovery, parsing, and execution.
    """
    def __init__(self, crm_tool: CRMTool):
        self.crm_tool = crm_tool
        self.tools = {
            "get_user_info": self._get_user_info_handler,
            "store_user_info": self._store_user_info_handler,
            "update_user_info": self._update_user_info_handler,
            "calculate_room_cost": self._calculate_room_cost_handler,
            "add_booking_to_calendar": self._add_booking_to_calendar_handler,
            "get_hotel_weather": self._get_hotel_weather_handler,
        }
        self.schemas = list(TOOL_SCHEMAS)

    async def _get_user_info_handler(self, args: Dict[str, Any]) -> str:
        user_id = args.get("user_id")
        if not user_id:
            return json.dumps({"ok": False, "error": "Missing user_id"})
        result = await tool_get_user_info(str(user_id), crm=self.crm_tool)
        return json.dumps(result)

    async def _store_user_info_handler(self, args: Dict[str, Any]) -> str:
        user_id = args.get("user_id")
        name = args.get("name")
        email = args.get("email")
        phone = args.get("phone")
        preferences = args.get("preferences")

        missing = [k for k in ["user_id", "name", "email", "phone", "preferences"] if args.get(k) is None]
        if missing:
            return json.dumps({"ok": False, "error": f"Missing required fields: {', '.join(missing)}"})
        if not isinstance(preferences, dict):
            return json.dumps({"ok": False, "error": "preferences must be an object/dict"})

        result = await tool_store_user_info(
            str(user_id),
            str(name),
            str(email),
            str(phone),
            preferences,
            crm=self.crm_tool,
        )
        return json.dumps(result)

    async def _update_user_info_handler(self, args: Dict[str, Any]) -> str:
        user_id = args.get("user_id")
        field = args.get("field")
        value = args.get("value")

        if not user_id:
            return json.dumps({"ok": False, "error": "Missing user_id"})
        if not field:
            return json.dumps({"ok": False, "error": "Missing field"})

        result = await tool_update_user_info(str(user_id), str(field), value, crm=self.crm_tool)
        return json.dumps(result)

    async def _calculate_room_cost_handler(self, args: Dict[str, Any]) -> str:
        required = ["room_type", "check_in", "check_out"]
        missing = [k for k in required if args.get(k) is None]
        if missing:
            return json.dumps({"ok": False, "message": f"Missing required fields: {', '.join(missing)}"})
        result = await tool_calculate_room_cost(
            room_type=str(args.get("room_type")),
            check_in=str(args.get("check_in")),
            check_out=str(args.get("check_out")),
            num_guests=args.get("num_guests"),
        )
        return json.dumps(result)

    async def _add_booking_to_calendar_handler(self, args: Dict[str, Any]) -> str:
        required = ["user_id", "room_type", "check_in", "check_out"]
        missing = [k for k in required if args.get(k) is None]
        if missing:
            return json.dumps({"ok": False, "message": f"Missing required fields: {', '.join(missing)}"})

        guest_name = str(args.get("guest_name") or "").strip()
        if not guest_name:
            crm = await tool_get_user_info(str(args.get("user_id")), crm=self.crm_tool)
            user = crm.get("user", {}) if isinstance(crm, dict) else {}
            guest_name = str(user.get("name") or "Guest")

        result = await tool_add_booking_to_calendar(
            user_id=str(args.get("user_id")),
            room_type=str(args.get("room_type")),
            check_in=str(args.get("check_in")),
            check_out=str(args.get("check_out")),
            guest_name=guest_name,
        )
        return json.dumps(result)

    async def _get_hotel_weather_handler(self, args: Dict[str, Any]) -> str:
        required = ["date"]
        missing = [k for k in required if args.get(k) is None]
        if missing:
            return json.dumps({"ok": False, "message": f"Missing required fields: {', '.join(missing)}"})

        result = await tool_get_hotel_weather(
            date=str(args.get("date")),
            city=str(args.get("city") or "Islamabad"),
        )
        return json.dumps(result)

    async def execute_tool_calls(self, text: str, user_message: Optional[str] = None) -> List[Dict[str, Any]]:
        tool_calls = self.extract_tool_calls(text)
        if not tool_calls:
            return []
        executed: List[Dict[str, Any]] = []
        for call in tool_calls:
            tool_name = call.get("name")
            params = call.get("parameters") or {}
            if tool_name not in self.tools:
                executed.append({"tool_name": tool_name, "ok": False, "result": {"message": f"Tool '{tool_name}' not found"}})
                continue
            if not self._is_tool_call_appropriate(str(tool_name), user_message):
                logger.info("Skipping unnecessary tool call: %s for message: %s", tool_name, user_message)
                continue
            start = time.perf_counter()
            try:
                raw = await self.tools[tool_name](params)
                payload = json.loads(raw) if isinstance(raw, str) else raw
                executed.append({"tool_name": tool_name, "ok": True, "result": payload})
            except Exception as e:
                logger.error("Error executing tool %s: %s", tool_name, e)
                executed.append({"tool_name": tool_name, "ok": False, "result": {"message": str(e)}})
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.info("Tool %s completed in %.2fms", tool_name, elapsed_ms)
        return executed

    def extract_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract tool calls from LLM response.
        Expected format (either):
        - {"tool":"<tool_name>", ...tool_parameters}
        - {"name":"<tool_name>","arguments":{...tool_parameters}}
        """
        tool_calls = []
        potential_jsons = _extract_json_objects(text)
        
        for json_str in potential_jsons:
            try:
                data = json.loads(json_str)
                if not isinstance(data, dict):
                    continue

                if isinstance(data.get("name"), str) and isinstance(data.get("arguments"), dict):
                    tool_calls.append({"name": data["name"], "parameters": data["arguments"]})
                    continue

                if isinstance(data.get("tool"), str):
                    params = dict(data)
                    tool_name = params.pop("tool")
                    tool_calls.append({"name": tool_name, "parameters": params})
            except json.JSONDecodeError:
                continue
        
        return tool_calls

    async def handle_tool_calls(self, text: str) -> Optional[str]:
        """
        Detect and execute tool calls found in the text.
        Returns a formatted string of results if any tools were called.
        """
        executed = await self.execute_tool_calls(text)
        if not executed:
            return None
        results = []
        for item in executed:
            tool_name = item.get("tool_name")
            result = item.get("result")
            if item.get("ok"):
                results.append(f"TOOL_RESULT ({tool_name}): {json.dumps(result)}")
            else:
                results.append(f"TOOL_ERROR ({tool_name}): {json.dumps(result)}")
        return "\n".join(results)

    def get_tool_system_prompt(self) -> str:
        """
        Returns the system prompt snippet that explains how to use tools.
        """
        schemas_str = json.dumps(self.schemas, indent=2)
        return f"""
AVAILABLE TOOLS:
{schemas_str}

TOOL USAGE RULES:
- Output exactly ONE JSON object only when a tool is required. Do not include any extra prose with tool JSON.
- Never call tools for general conversation, greetings, policy Q&A, or when you can answer directly.
- Call at most one tool per guest message unless the guest explicitly asks for multiple actions.
- Use either:
  - {{"tool":"<tool_name>", ...tool_parameters}}
  - {{"name":"<tool_name>","arguments":{{...tool_parameters}}}}
- Always use the 'user_id' provided in the 'CURRENT GUEST CONTEXT' section.
- `calculate_room_cost`: trigger for requests like "Calculate Deluxe room cost from 2026-05-05 to 2026-05-10". Use room_type, check_in, check_out, optional num_guests. Never ask for or send price_per_night.
- `add_booking_to_calendar`: trigger for requests like "Book a Deluxe room for me from 2026-05-05 to 2026-05-10". Use room_type, check_in, check_out, user_id. Do not ask for guest_name; system will infer from CRM.
- `get_hotel_weather`: hotel city is Islamabad by default. For prompts like "what is the weather there on 2026-05-05?", call with date only.
- After calling a tool, the system will narrate the final response.

Examples:
- Create user: {{"tool":"store_user_info","user_id":"user_123","name":"Ahmed","email":"ahmed@x.com","phone":"0300-1234567","preferences":{{"language":"en"}}}}
- Get user: {{"tool":"get_user_info","user_id":"user_123"}}
- Update phone: {{"tool":"update_user_info","user_id":"user_123","field":"phone","value":"0300-1234567"}}
"""
