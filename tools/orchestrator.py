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

        if any(k in text for k in [
            "my name", "my email", "my phone", "who am i",
            "email address", "phone number", "contact number",
            "store my", "save my", "update my", "remember my",
            "what is my", "what's my", "do you have my",
            "profile", "preferences", "my info", "my details",
        ]):
            tools.extend(["get_user_info", "store_user_info", "update_user_info"])

        return tools

    def should_enable_tools(self, user_message: Optional[str]) -> bool:
        return len(self.infer_relevant_tools(user_message)) > 0

    def try_direct_crm_operation(self, user_message: Optional[str], user_id: str) -> Optional[Dict[str, Any]]:
        """
        Try to directly match and execute common CRM patterns without LLM.
        Returns the executed tool result or None if no direct match.
        
        Patterns:
        - "my phone number is X" -> update_user_info(field="phone", value="X")
        - "my email is X" / "my email address is X" -> update_user_info(field="email", value="X")
        - "my name is X" -> update_user_info(field="name", value="X")
        - "my preferences are: ..." / "my preferences: ..." -> update_user_info(field="preferences", value="...")
        - "what is my phone?" / "what's my phone number?" -> get_user_info()
        - "what is my email?" / "what's my email address?" -> get_user_info()
        - "what is my name?" / "tell me my name" / "do you remember my name?" -> get_user_info()
        - "what are my preferences?" / "do you remember my preferences?" -> get_user_info()
        """
        if not user_message or not user_id:
            return None
        
        text = user_message.strip()
        text_lower = text.lower()
        
        # Pattern 1: "my phone number is 123456" or "my phone is 123456"
        phone_match = re.search(r'my\s+phone(?:\s+number)?\s+is\s+(.+?)(?:\s*[.!?]|\s*$)', text_lower)
        if phone_match:
            phone_value = phone_match.group(1).strip()
            if phone_value:
                return {
                    "tool_name": "update_user_info",
                    "params": {"user_id": user_id, "field": "phone", "value": phone_value},
                    "direct": True
                }
        
        # Pattern 2: "my email is X" or "my email address is X"
        email_match = re.search(r'my\s+email(?:\s+address)?\s+is\s+([^\s]+@[^\s]+)(?:\s|$)', text_lower)
        if email_match:
            email_value = email_match.group(1).strip()
            if email_value and '@' in email_value:  # Basic email validation
                return {
                    "tool_name": "update_user_info",
                    "params": {"user_id": user_id, "field": "email", "value": email_value},
                    "direct": True
                }
        
        # Pattern 3: "my name is X"
        name_match = re.search(r'my\s+name\s+is\s+(.+?)(?:\s*[.!?]|\s*$)', text_lower)
        if name_match:
            name_value = name_match.group(1).strip()
            if name_value:
                return {
                    "tool_name": "update_user_info",
                    "params": {"user_id": user_id, "field": "name", "value": name_value},
                    "direct": True
                }
        
        # Pattern 4: "what is my phone?" or "what's my phone number?" or "do you remember my phone?"
        if any(k in text_lower for k in ["what is my phone", "what's my phone", "do you have my phone", "do you remember my phone"]):
            return {
                "tool_name": "get_user_info",
                "params": {"user_id": user_id},
                "direct": True
            }
        
        # Pattern 5: "what is my email?" or "what's my email address?" or "do you remember my email?"
        if any(k in text_lower for k in ["what is my email", "what's my email", "do you have my email", "do you remember my email"]):
            return {
                "tool_name": "get_user_info",
                "params": {"user_id": user_id},
                "direct": True
            }
        
        # Pattern 6: "my preferences are ..." or "my preferences: ..."
        pref_match = re.search(r'my\s+preferences\s*(?:are)?\s*:?\s*(.+?)(?:\s*[.!?]|\s*$)', text_lower)
        if pref_match:
            pref_value = pref_match.group(1).strip()
            if pref_value:
                return {
                    "tool_name": "update_user_info",
                    "params": {"user_id": user_id, "field": "preferences", "value": pref_value},
                    "direct": True
                }
        
        # Pattern 7: "what is my name?" or "tell me my name" or "do you remember my name?"
        if any(k in text_lower for k in ["what is my name", "tell me my name", "do you remember my name"]):
            return {
                "tool_name": "get_user_info",
                "params": {"user_id": user_id},
                "direct": True
            }
        
        # Pattern 8: "what are my preferences?" or "do you remember my preferences?"
        if any(k in text_lower for k in ["what are my preferences", "do you remember my preferences"]):
            return {
                "tool_name": "get_user_info",
                "params": {"user_id": user_id},
                "direct": True
            }
        
        return None

    async def execute_direct_crm_operation(self, crm_op: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a direct CRM operation that was matched by try_direct_crm_operation.
        Returns formatted tool execution results or None if operation fails.
        """
        if not crm_op or not crm_op.get("direct"):
            return None
        
        tool_name = crm_op.get("tool_name")
        params = crm_op.get("params", {})
        
        if tool_name not in self.tools:
            return None
        
        try:
            start = time.perf_counter()
            raw = await self.tools[tool_name](params)
            payload = json.loads(raw) if isinstance(raw, str) else raw
            
            result = {
                "tool_name": tool_name,
                "ok": True,
                "result": payload,
                "params": params
            }
            
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("Direct CRM operation %s completed in %.2fms", tool_name, elapsed_ms)
            
            return [result]
        except Exception as e:
            logger.error("Error executing direct CRM operation %s: %s", tool_name, e)
            return None

    def try_direct_calculator_operation(self, user_message: Optional[str]) -> Optional[Dict[str, Any]]:
        """Try to directly match calculator operation pattern."""
        if not user_message:
            return None
        
        text_lower = user_message.lower()
        
        # Pattern: Extract dates in YYYY-MM-DD format
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', text_lower)
        if len(dates) < 2:
            return None
        
        # Pattern: Look for room type keywords
        room_types = ["standard", "king", "queen", "deluxe", "suite", "twin", "double", "single"]
        room_type = None
        for rt in room_types:
            if rt in text_lower:
                room_type = rt.capitalize()
                break
        
        # Must have room type AND dates AND cost-related keywords
        has_cost_intent = any(k in text_lower for k in ["cost", "price", "how much", "calculate"])
        
        if room_type and len(dates) >= 2 and has_cost_intent:
            return {
                "tool_name": "calculate_room_cost",
                "params": {
                    "room_type": room_type,
                    "check_in": dates[0],
                    "check_out": dates[1]
                },
                "direct": True
            }
        
        return None

    def try_direct_weather_operation(self, user_message: Optional[str]) -> Optional[Dict[str, Any]]:
        """Try to directly match weather operation pattern."""
        if not user_message:
            return None
        
        text_lower = user_message.lower()
        
        # Check for weather intent
        has_weather_intent = any(k in text_lower for k in ["weather", "forecast", "temperature", "rain"])
        if not has_weather_intent:
            return None
        
        # Extract date in YYYY-MM-DD format
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', text_lower)
        if not date_match:
            return None
        
        return {
            "tool_name": "get_hotel_weather",
            "params": {"date": date_match.group(1)},
            "direct": True
        }

    def try_direct_calendar_operation(self, user_message: Optional[str], user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Try to directly match calendar booking operation pattern."""
        if not user_message:
            return None
        
        text_lower = user_message.lower()
        
        # Check for booking intent
        has_booking_intent = any(k in text_lower for k in ["book", "booking", "reserve", "reservation"])
        if not has_booking_intent:
            return None
        
        # Extract dates in YYYY-MM-DD format
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', text_lower)
        if len(dates) < 2:
            return None
        
        # Look for room type keywords
        room_types = ["standard", "king", "queen", "deluxe", "suite", "twin", "double", "single"]
        room_type = None
        for rt in room_types:
            if rt in text_lower:
                room_type = rt.capitalize()
                break
        
        # Room type is optional for calendar, but dates are required
        return {
            "tool_name": "add_booking_to_calendar",
            "params": {
                "user_id": user_id or "guest_unknown",
                "guest_name": "Guest",  # Default, will be updated from context if available
                "check_in": dates[0],
                "check_out": dates[1],
                "room_type": room_type or "Standard"
            },
            "direct": True
        }
    
    def try_direct_tool_operation(self, user_message: Optional[str], user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Try to directly match ANY direct pattern without LLM."""
        if not user_message:
            return None
        
        # Try each direct operation in order
        if user_id:
            crm_op = self.try_direct_crm_operation(user_message, user_id)
            if crm_op:
                return crm_op
        
        calc_op = self.try_direct_calculator_operation(user_message)
        if calc_op:
            return calc_op
        
        weather_op = self.try_direct_weather_operation(user_message)
        if weather_op:
            return weather_op
        
        calendar_op = self.try_direct_calendar_operation(user_message, user_id)
        if calendar_op:
            return calendar_op
        
        return None

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
            return any(k in text for k in [
                "my name", "my email", "my phone", "who am i",
                "email address", "phone number", "contact number",
                "store my", "save my", "update my", "remember my",
                "what is my", "what's my", "do you have my",
                "profile", "preferences", "my info", "my details",
            ])

        return True

    def __init__(self, crm_tool: CRMTool):
        """Initialize the tool orchestrator with a CRM tool instance."""
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
                executed.append({"tool_name": tool_name, "ok": False, "result": {"message": f"Tool '{tool_name}' not found"}, "params": params})
                continue
            if not self._is_tool_call_appropriate(str(tool_name), user_message):
                logger.info("Skipping unnecessary tool call: %s for message: %s", tool_name, user_message)
                continue
            start = time.perf_counter()
            try:
                raw = await self.tools[tool_name](params)
                payload = json.loads(raw) if isinstance(raw, str) else raw
                executed.append({"tool_name": tool_name, "ok": True, "result": payload, "params": params})
            except Exception as e:
                logger.error("Error executing tool %s: %s", tool_name, e)
                executed.append({"tool_name": tool_name, "ok": False, "result": {"message": str(e)}, "params": params})
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
