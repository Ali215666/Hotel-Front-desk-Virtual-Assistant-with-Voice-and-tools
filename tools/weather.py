from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Tuple

import httpx

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 600
_WEATHER_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


GET_HOTEL_WEATHER_SCHEMA: Dict[str, Any] = {
    "name": "get_hotel_weather",
    "description": "Fetch weather details for a hotel city and target date with guest-friendly travel advice.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "date": {"type": "string", "description": "Target date in YYYY-MM-DD format."},
        },
        "required": ["date"],
    },
}


def _advice_from_condition(condition: str) -> str:
    lower = condition.lower()
    if "rain" in lower or "drizzle" in lower or "storm" in lower:
        return "Light rain expected, consider indoor activities."
    if "snow" in lower:
        return "Snow is expected, carry warm layers and check local transport conditions."
    if "clear" in lower:
        return "Clear weather expected, good for outdoor plans."
    if "cloud" in lower:
        return "Cloudy weather expected, a light jacket is a good idea."
    return "Weather may vary, so keep a flexible plan."


def _cache_get(city: str, target_date: str) -> Dict[str, Any] | None:
    key = (city.lower().strip(), target_date)
    hit = _WEATHER_CACHE.get(key)
    if not hit:
        return None
    expiry, payload = hit
    if time.time() > expiry:
        _WEATHER_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(city: str, target_date: str, payload: Dict[str, Any]) -> None:
    key = (city.lower().strip(), target_date)
    _WEATHER_CACHE[key] = (time.time() + CACHE_TTL_SECONDS, payload)


async def _fetch_json(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with asyncio.timeout(5):
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def get_hotel_weather(date: str, city: str = "Islamabad") -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        city_name = (city or "").strip()
        if not city_name:
            return {"ok": False, "message": "Please provide a city name for weather lookup."}

        logger.info(f"Weather request: city={city_name}, date={date}")
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        today = datetime.utcnow().date()

        cached = _cache_get(city_name, date)
        if cached:
            logger.info(f"Weather cache hit for {city_name} on {date}")
            return cached

        api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        logger.info(f"OpenWeather API key check: {'present' if api_key else 'MISSING'}")
        if not api_key:
            return {
                "ok": False,
                "message": "Weather service is unavailable because OPENWEATHER_API_KEY is not configured.",
            }

        async with httpx.AsyncClient(timeout=5.0) as client:
            geo = await _fetch_json(
                client,
                "http://api.openweathermap.org/geo/1.0/direct",
                {"q": city_name, "limit": 1, "appid": api_key},
            )
            if not geo:
                return {"ok": False, "message": f"I could not find weather data for {city_name}."}
            lat = geo[0]["lat"]
            lon = geo[0]["lon"]
            resolved_city = geo[0].get("name", city_name)

            if target_date == today:
                weather_json = await _fetch_json(
                    client,
                    "https://api.openweathermap.org/data/2.5/weather",
                    {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
                )
                main = weather_json.get("main", {})
                condition = weather_json.get("weather", [{}])[0].get("description", "Unknown")
                payload = {
                    "ok": True,
                    "city": resolved_city,
                    "date": date,
                    "temperature_c": main.get("temp"),
                    "humidity": main.get("humidity"),
                    "condition": condition,
                    "suggestion": _advice_from_condition(condition),
                    "message": (
                        f"Weather in {resolved_city} on {date}: {condition}, "
                        f"{main.get('temp')}°C with humidity at {main.get('humidity')}%."
                    ),
                }
                _cache_set(city_name, date, payload)
                return payload

            forecast_json = await _fetch_json(
                client,
                "https://api.openweathermap.org/data/2.5/forecast",
                {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            )
            entries = forecast_json.get("list", [])
            if not entries:
                return {"ok": False, "message": "Forecast data is unavailable at the moment."}

            # Free tier forecast typically covers up to 5 days.
            if target_date > today + timedelta(days=5):
                return {
                    "ok": False,
                    "message": "Forecast is available up to 5 days ahead on the free weather plan.",
                }

            same_day = [e for e in entries if datetime.utcfromtimestamp(e.get("dt", 0)).date() == target_date]
            chosen = same_day[0] if same_day else entries[0]
            main = chosen.get("main", {})
            condition = chosen.get("weather", [{}])[0].get("description", "Unknown")

            payload = {
                "ok": True,
                "city": resolved_city,
                "date": date,
                "temperature_c": main.get("temp"),
                "humidity": main.get("humidity"),
                "condition": condition,
                "suggestion": _advice_from_condition(condition),
                "message": (
                    f"Forecast for {resolved_city} on {date}: {condition}, "
                    f"around {main.get('temp')}°C with humidity near {main.get('humidity')}%."
                ),
            }
            _cache_set(city_name, date, payload)
            return payload
    except TimeoutError:
        logger.warning("Weather lookup timed out")
        return {"ok": False, "message": "Weather lookup timed out. Please try again in a moment."}
    except ValueError as e:
        logger.warning("Invalid date format: %s", e)
        return {"ok": False, "message": "Date must be in YYYY-MM-DD format for weather lookup."}
    except httpx.HTTPError as e:
        logger.error("HTTP error fetching weather: %s", e)
        return {"ok": False, "message": "I could not reach the weather service right now."}
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_hotel_weather failed: %s", exc)
        return {"ok": False, "message": "I could not fetch the weather right now. Please try again."}
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("Tool get_hotel_weather executed in %.2fms", elapsed_ms)
