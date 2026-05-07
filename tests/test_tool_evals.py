import asyncio
import json
import uuid
import pytest
import sys
import os
from datetime import date, timedelta
from pathlib import Path
import websockets

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.crm import SQLiteCRM
from tools.calculator import calculate_room_cost
from tools.calendar_tool import add_booking_to_calendar
from tools.weather import get_hotel_weather

pytestmark = pytest.mark.asyncio

@pytest.fixture
def crm_instance(temp_crm_db):
    return SQLiteCRM(db_path=temp_crm_db)

# ==============================================================================
# 1. CRM CRUD Tests
# ==============================================================================

async def test_create_guest(crm_instance):
    res = await crm_instance.store_user_info(
        user_id="user_test_1",
        name="Alice",
        email="alice@example.com",
        phone="1234567890",
        preferences={"floor": "high"}
    )
    assert res.get("ok") is True
    assert res["user"]["name"] == "Alice"
    assert res["user"]["phone"] == "1234567890"

async def test_read_guest(crm_instance):
    await crm_instance.store_user_info(
        user_id="user_test_2",
        name="Bob",
        email="bob@example.com",
        phone="0987654321",
        preferences={"bed": "king"}
    )
    res = await crm_instance.get_user_info("user_test_2")
    assert res.get("ok") is True
    assert res["user"]["name"] == "Bob"
    assert res["user"]["preferences"]["bed"] == "king"

async def test_update_guest(crm_instance):
    await crm_instance.store_user_info("user_test_3", name="Charlie", email="c@x.com", phone="111", preferences={})
    res = await crm_instance.update_user_info("user_test_3", "phone", "222")
    assert res.get("ok") is True
    assert res["user"]["phone"] == "222"

async def test_delete_or_overwrite(crm_instance):
    # Try storing the same user twice
    await crm_instance.store_user_info("user_test_4", name="Dave", email="d@x.com", phone="1", preferences={})
    res = await crm_instance.store_user_info("user_test_4", name="Dave", email="d@x.com", phone="2", preferences={})
    assert res.get("ok") is False
    assert "already exists" in res.get("error", "").lower()

async def test_crm_with_invalid_id(crm_instance):
    res = await crm_instance.get_user_info("")
    assert res.get("ok") is False
    assert "user_id is required" in res.get("error", "")

# ==============================================================================
# 2. Calculator Tests
# ==============================================================================

async def test_single_room_cost():
    res = await calculate_room_cost("standard", "2026-06-01", "2026-06-04", 2)
    assert res.get("ok") is True
    assert res["nights"] == 3
    assert res["base_total"] == 70.0 * 3
    assert res["total_cost"] == 210.0

async def test_suite_cost():
    res = await calculate_room_cost("suite", "2026-06-01", "2026-06-08", 4)
    assert res.get("ok") is True
    assert res["nights"] == 7
    assert res["base_total"] == 300.0 * 7
    # 15% surcharge for suite > 2 guests
    expected_surcharge = round((300.0 * 7) * 0.15, 2)
    assert res["surcharge_amount"] == expected_surcharge

async def test_invalid_room_type():
    res = await calculate_room_cost("spaceship", "2026-06-01", "2026-06-02", 1)
    assert res.get("ok") is False
    assert "must be Standard, Deluxe, or Suite" in res.get("message", "")

async def test_zero_nights():
    res = await calculate_room_cost("standard", "2026-06-01", "2026-06-01", 1)
    assert res.get("ok") is False
    assert "must be after check-in" in res.get("message", "")

# ==============================================================================
# 3. Calendar Tests
# ==============================================================================

async def test_create_booking():
    res = await add_booking_to_calendar("u_cal_1", "deluxe", "2026-07-01", "2026-07-05")
    assert res.get("ok") is True
    assert "download_path" in res
    ics_path = Path(res["download_path"])
    assert ics_path.exists()
    assert ics_path.suffix == ".ics"

async def test_booking_content():
    res = await add_booking_to_calendar("u_cal_2", "suite", "2026-08-01", "2026-08-03")
    ics_path = Path(res["download_path"])
    content = ics_path.read_text(encoding="utf-8")
    assert "BEGIN:VEVENT" in content
    assert "DTSTART;VALUE=DATE:20260801" in content
    assert "DTEND;VALUE=DATE:20260803" in content
    assert "SUMMARY:Guest - suite booking" in content

async def test_duplicate_booking():
    res1 = await add_booking_to_calendar("u_cal_3", "standard", "2026-09-01", "2026-09-02")
    res2 = await add_booking_to_calendar("u_cal_3", "standard", "2026-09-01", "2026-09-02")
    assert res1.get("ok") is True
    assert res2.get("ok") is True
    assert res1["download_path"] != res2["download_path"]

# ==============================================================================
# 4. Weather Tests
# ==============================================================================

async def test_weather_valid_location():
    # Only test if API key is present so we don't fail CI
    import os
    if not os.getenv("OPENWEATHER_API_KEY"):
        pytest.skip("No OPENWEATHER_API_KEY")
    
    today = date.today().strftime("%Y-%m-%d")
    res = await get_hotel_weather(today, "Islamabad")
    assert res.get("ok") is True
    assert "temperature_c" in res
    assert "condition" in res

async def test_weather_invalid_location():
    if not os.getenv("OPENWEATHER_API_KEY"):
        pytest.skip("No OPENWEATHER_API_KEY")
    
    today = date.today().strftime("%Y-%m-%d")
    res = await get_hotel_weather(today, "FakeCityThatDoesNotExist12345")
    assert res.get("ok") is False
    assert "could not find weather data" in res.get("message", "").lower()

# ==============================================================================
# 5. LLM Tool Invocation Accuracy
# ==============================================================================

UTTERANCES = [
    {"text": "My phone number is 0300-1234567.", "expected_tool": "update_user_info", "expected_args": ["0300-1234567"]},
    {"text": "Update my email to ahmed@example.com", "expected_tool": "update_user_info", "expected_args": ["ahmed@example.com"]},
    {"text": "What is my phone number?", "expected_tool": "get_user_info", "expected_args": []},
    
    {"text": "How much for a standard room from 2026-06-01 to 2026-06-04?", "expected_tool": "calculate_room_cost", "expected_args": ["210", "standard", "3"]},
    {"text": "Cost of suite for 7 nights starting 2026-06-01 to 2026-06-08?", "expected_tool": "calculate_room_cost", "expected_args": ["2100", "suite", "7"]},
    
    {"text": "Book me a standard room from 2026-06-01 to 2026-06-05", "expected_tool": "add_booking_to_calendar", "expected_args": ["added to the calendar", "download"]},
    {"text": "I want to reserve a deluxe room starting 2026-10-10 until 2026-10-12", "expected_tool": "add_booking_to_calendar", "expected_args": ["added to the calendar"]},

    {"text": f"What's the weather like in Islamabad on {(date.today()).strftime('%Y-%m-%d')}?", "expected_tool": "get_hotel_weather", "expected_args": ["islamabad"]},
    {"text": f"Will it rain tomorrow in Lahore on {(date.today() + timedelta(days=1)).strftime('%Y-%m-%d')}?", "expected_tool": "get_hotel_weather", "expected_args": ["islamabad"]},

    {"text": "Hi, how are you?", "expected_tool": None, "expected_args": []},
    {"text": "What are the hotel policies?", "expected_tool": None, "expected_args": []},
    {"text": "Is the swimming pool open?", "expected_tool": None, "expected_args": []}
]

def _matches_tool(response: str, expected_tool: str, expected_args: list) -> bool:
    resp_lower = response.lower()
    
    # Infer tool from narration keywords
    detected_tool = None
    if "phone number has been updated" in resp_lower or ("email" in resp_lower and "updated" in resp_lower):
        detected_tool = "update_user_info"
    elif "i have your profile" in resp_lower or "your phone is" in resp_lower or "we don't have a phone" in resp_lower or "is not on file" in resp_lower or "don't have a phone" in resp_lower:
        detected_tool = "get_user_info"
    elif "cost" in resp_lower and "stay" in resp_lower:
        detected_tool = "calculate_room_cost"
    elif "added to the calendar" in resp_lower or "calendar event" in resp_lower:
        detected_tool = "add_booking_to_calendar"
    elif "weather" in resp_lower or "forecast" in resp_lower:
        detected_tool = "get_hotel_weather"
        
    if expected_tool is None:
        return detected_tool is None
        
    if detected_tool != expected_tool:
        return False
        
    # Check args
    for arg in expected_args:
        if str(arg).lower() not in resp_lower:
            return False
            
    return True

async def test_llm_tool_invocation_accuracy():
    url = "ws://localhost:8000/ws/chat"
    
    correct_tools = 0
    correct_args = 0
    false_positives = 0
    total = len(UTTERANCES)
    
    results = []
    
    for u in UTTERANCES:
        session_id = f"eval_tool_{uuid.uuid4().hex[:8]}"
        
        try:
            async with websockets.connect(url) as ws:
                # Handshake
                await ws.send(json.dumps({
                    "session_id": session_id,
                    "message": "__INIT__",
                    "type": "init"
                }))
                await ws.recv() # Status
                
                # Send message
                await ws.send(json.dumps({
                    "session_id": session_id,
                    "message": u["text"]
                }))
                
                full_response = ""
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if data.get("type") == "token":
                        full_response += data.get("content", "")
                    elif data.get("type") == "done":
                        break
                        
                is_correct = _matches_tool(full_response, u["expected_tool"], u["expected_args"])
                if is_correct:
                    if u["expected_tool"] is not None:
                        correct_tools += 1
                        correct_args += 1
                elif u["expected_tool"] is None and full_response and _matches_tool(full_response, "any", []):
                    false_positives += 1
                    
                results.append({
                    "utterance": u["text"],
                    "expected": u["expected_tool"],
                    "response": full_response,
                    "success": is_correct
                })
        except Exception as e:
            results.append({
                "utterance": u["text"],
                "expected": u["expected_tool"],
                "response": f"ERROR: {e}",
                "success": False
            })

    # Avoid zero division
    positives = sum(1 for u in UTTERANCES if u["expected_tool"] is not None)
    negatives = total - positives
    
    correct_tool_rate = correct_tools / positives if positives > 0 else 0.0
    correct_args_rate = correct_args / positives if positives > 0 else 0.0
    fp_rate = false_positives / negatives if negatives > 0 else 0.0

    report_dir = Path("eval_reports")
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / "tool_report.md"
    
    lines = [
        "# Tool Invocation Evaluation Report",
        "",
        "## Metrics",
        f"- **Correct Tool Rate:** {correct_tool_rate:.2%}",
        f"- **Correct Args Rate:** {correct_args_rate:.2%}",
        f"- **False Positive Rate:** {fp_rate:.2%}",
        "",
        "## Utterance Details",
        "| Utterance | Expected Tool | Success | Response Snapshot |",
        "|-----------|---------------|---------|-------------------|"
    ]
    for r in results:
        snap = r["response"].replace("\n", " ")[:60] + "..."
        lines.append(f"| {r['utterance']} | {r['expected']} | {'✅' if r['success'] else '❌'} | {snap} |")
        
    report_path.write_text("\n".join(lines), encoding="utf-8")
    
    # Assert acceptable performance
    assert correct_tool_rate >= 0.7, f"Correct tool rate too low: {correct_tool_rate}"
    assert fp_rate <= 0.3, f"False positive rate too high: {fp_rate}"
