from fastmcp import FastMCP
from services.weather import (
    get_weather as fetch_weather,
    get_hourly_forecast,
)

import math

import httpx

import database

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os
from pathlib import Path
from dotenv import load_dotenv
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.dependencies import TokenClaim

load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

AUTH_MODE = os.getenv("AUTH_MODE", "local").strip().lower()


def _local_user_tokens() -> dict[str, dict[str, object]]:
    users = (
        ("DEV_MOCK_USER_ONE_TOKEN", "dev_mock_user_1"),
        ("DEV_MOCK_USER_TWO_TOKEN", "dev_mock_user_2"),
    )
    tokens: dict[str, dict[str, object]] = {}

    for env_name, user_sub in users:
        token = os.getenv(env_name, "").strip()
        if len(token) < 32:
            raise RuntimeError(
                f"{env_name} must contain a distinct token of at least 32 characters."
            )
        if token in tokens:
            raise RuntimeError("Local mock user tokens must be different.")

        tokens[token] = {
            "client_id": "smart-daily-assistant-local",
            "scopes": [],
            "sub": user_sub,
        }

    return tokens

if AUTH_MODE == "oauth":
    mcp = FastMCP(
        name="Smart Daily Assistant",
        auth=GoogleProvider(
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            base_url=os.environ["MCP_BASE_URL"],
        ),
    )

elif AUTH_MODE in {"local", "mock"}:
    # Local-only bearer tokens map to fixed subjects; callers cannot choose a user.
    mcp = FastMCP(
        name="Smart Daily Assistant",
        auth=StaticTokenVerifier(_local_user_tokens()),
    )

else:
    raise RuntimeError(f"Unsupported AUTH_MODE: {AUTH_MODE}")

@mcp.tool
async def get_daily_briefing(
    city: str,
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """Summarize weather, the authenticated user's pending tasks,
    and upcoming calendar events.
    """
    try:
        weather = await fetch_weather(city)
    except Exception:
        weather = {
            "success": False,
            "error": "Weather is temporarily unavailable.",
        }

    try:
        tasks = database.list_tasks(
            user_sub=user_sub,
            pending_only=True,
        )
        for task in tasks:
            task["completed"] = bool(task["completed"])
    except Exception:
        tasks = []

    try:
        now = datetime.now(timezone.utc).isoformat()
        events = database.list_upcoming_events(
            from_time=now,
            user_sub=user_sub,
            limit=10,
        )
    except Exception:
        events = []

    return {
        "city": city,
        "weather": weather,
        "pending_tasks": {
            "count": len(tasks),
            "items": tasks,
        },
        "upcoming_events": {
            "count": len(events),
            "items": events,
        },
    }




@mcp.tool
def add_task(
    title: str,
    priority: str = "medium",
    user_sub: str = TokenClaim("sub"),
    due_date: str | None = None,
) -> dict:
    """Create a task with a priority and optional due date.

    Priority must be low, medium, or high.
    Due date should use ISO 8601 format, such as
    2026-10-20 or 2026-10-20T18:00:00+00:00.
    """
    try:
        task = database.create_task(
            title=title,
            user_sub=user_sub,
            priority=priority,
            due_date=due_date,
        )

        task["completed"] = bool(task["completed"])

        return {
            "success": True,
            "message": "Task created successfully.",
            "task": task,
        }

    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    except Exception:
        return {
            "success": False,
            "error": "Unable to create the task right now.",
        }


@mcp.tool
def list_tasks(
    pending_only: bool = True,
    user_sub: str = TokenClaim("sub"),
) -> list[dict]:
    """List pending tasks, or all tasks when pending_only is false."""
    tasks = database.list_tasks(
        user_sub=user_sub,
        pending_only=pending_only,
    )

    for task in tasks:
        task["completed"] = bool(task["completed"])

    return tasks


@mcp.tool
def complete_task(
    task_id: int,
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """Mark the authenticated user's task as completed."""
    if task_id <= 0:
        return {"success": False, "error": "Task ID must be positive."}

    task = database.complete_task(task_id, user_sub=user_sub)

    if task is None:
        return {
            "success": False,
            "error": "Task was not found.",
        }

    task["completed"] = bool(task["completed"])
    return {"success": True, "task": task}



@mcp.tool
async def get_weather(city: str) -> dict:
    """Get current weather conditions for a named city."""
    try:
        return await fetch_weather(city)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except httpx.HTTPError:
        return {
            "success": False,
            "error": "The weather service is temporarily unavailable.",
        }
    except (KeyError, TypeError, ValueError):
        return {
            "success": False,
            "error": "The weather service returned an unexpected response.",
        }


@mcp.tool
def add_calendar_event(
    title: str,
    start_time: str,
    end_time: str,
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """Create a calendar event.

    Provide start_time and end_time as ISO 8601 timestamps
    with a timezone offset, such as +05:30, or in UTC with Z.
    """
    try:
        start = datetime.fromisoformat(
            start_time.replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            end_time.replace("Z", "+00:00")
        )

        if start.tzinfo is None or end.tzinfo is None:
            return {
                "success": False,
                "error": "Timestamps must include a timezone.",
            }

        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        if end_utc <= start_utc:
            return {
                "success": False,
                "error": "End time must be after start time.",
            }

        event = database.create_calendar_event(
            title,
            start_utc.isoformat(),
            end_utc.isoformat(),
            user_sub=user_sub
        )

        return {"success": True, "event": event}

    except ValueError as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool
def get_upcoming_events(
    limit: int = 10,
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """List upcoming calendar events, ordered by start time."""
    if not 1 <= limit <= 50:
        return {
            "success": False,
            "error": "Limit must be between 1 and 50.",
        }

    now = datetime.now(timezone.utc).isoformat()
    events = database.list_upcoming_events(
    from_time=now,
    user_sub=user_sub,
    limit=limit,
)

    return {
        "success": True,
        "count": len(events),
        "events": events,
    }


@mcp.tool
def prioritize_tasks(
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """Rank the authenticated user's pending tasks by overdue status,
    priority, and due date."""

    try:
        tasks = database.list_tasks(user_sub=user_sub, pending_only=True)
        now = datetime.now(timezone.utc)

        def get_deadline(task):
            due_date = task.get("due_date")

            if not due_date:
                return None

            try:
                parsed = datetime.fromisoformat(
                    due_date.replace("Z", "+00:00")
                )

                # Treat date-only deadlines as midnight UTC.
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)

                return parsed.astimezone(timezone.utc)

            except (ValueError, TypeError):
                return None

        def sort_key(task):
            deadline = get_deadline(task)
            priority = str(task.get("priority", "medium")).lower()

            # Overdue tasks come first, followed by high, medium, low.
            overdue_rank = 0 if deadline and deadline < now else 1

            priority_rank = {
                "high": 0,
                "medium": 1,
                "low": 2,
            }.get(priority, 1)

            # Tasks with deadlines precede tasks without deadlines
            # when their overdue and priority ranks are equal.
            deadline_rank = (
                deadline.timestamp()
                if deadline is not None
                else float("inf")
            )

            return overdue_rank, priority_rank, deadline_rank

        tasks.sort(key=sort_key)

        prioritized = []

        for rank, task in enumerate(tasks, start=1):
            deadline = get_deadline(task)

            prioritized.append({
                "rank": rank,
                "task_id": task["id"],
                "title": task["title"],
                "priority": task.get("priority", "medium"),
                "due_date": task.get("due_date"),
                "overdue": bool(deadline and deadline < now),
            })

        return {
            "success": True,
            "count": len(prioritized),
            "prioritized_tasks": prioritized,
        }

    except Exception:
        return {
            "success": False,
            "error": "Unable to prioritize tasks right now.",
        }



def build_weather_recommendations(
    weather: dict,
    city: str,
) -> list[dict]:
    """Create actionable recommendations from weather measurements."""

    recommendations = []

    if not weather.get("success", True):
        return [{
            "type": "weather_unavailable",
            "message": f"Weather data is unavailable for {city}.",
        }]

    temperature = weather.get("temperature_c")
    feels_like = weather.get("feels_like_c")
    precipitation = weather.get("precipitation_mm")
    wind_speed = weather.get("wind_speed_kmh")
    weather_code = weather.get("weather_code")

    # Validate numeric values before comparing them.
    temperature = (
        temperature
        if isinstance(temperature, (int, float))
        and not isinstance(temperature, bool)
        and math.isfinite(temperature)
        else None
    )
    feels_like = (
        feels_like
        if isinstance(feels_like, (int, float))
        and not isinstance(feels_like, bool)
        and math.isfinite(feels_like)
        else None
    )
    precipitation = (
        precipitation
        if isinstance(precipitation, (int, float))
        and not isinstance(precipitation, bool)
        and math.isfinite(precipitation)
        else None
    )
    wind_speed = (
        wind_speed
        if isinstance(wind_speed, (int, float))
        and not isinstance(wind_speed, bool)
        and math.isfinite(wind_speed)
        else None
    )

    # WMO codes for drizzle, rain, showers, and thunderstorms.
    is_rainy_weather = (
        isinstance(weather_code, int)
        and not isinstance(weather_code, bool)
        and (
            51 <= weather_code <= 67
            or 80 <= weather_code <= 82
            or 95 <= weather_code <= 99
        )
    )

    if is_rainy_weather:
        recommendations.append({
            "type": "rain_or_storm",
            "message": (
                f"Drizzle, rain, or thunderstorms may affect outdoor "
                f"plans in {city}. Carry an umbrella, allow extra "
                "travel time, and check local conditions before leaving."
            ),
            "action": "prepare_for_rain",
        })

    elif precipitation is not None and precipitation >= 1:
        recommendations.append({
            "type": "precipitation",
            "message": (
                f"Precipitation is currently {precipitation} mm in {city}. "
                "Consider rain protection and check conditions "
                "before heading outdoors."
            ),
            "action": "check_outdoor_conditions",
        })

    # Heat advice: prefer feels-like temperature when available.
    apparent_temperature = (
        feels_like if feels_like is not None else temperature
    )

    if apparent_temperature is not None:
        if apparent_temperature >= 40:
            recommendations.append({
                "type": "extreme_heat",
                "message": (
                    f"It feels like {apparent_temperature}°C in {city}. "
                    "Avoid strenuous outdoor activity where possible, "
                    "stay in a cool place, and drink water regularly."
                ),
                "action": "avoid_extreme_heat",
            })
        elif apparent_temperature >= 35:
            recommendations.append({
                "type": "heat",
                "message": (
                    f"It feels like {apparent_temperature}°C in {city}. "
                    "Drink water, seek shade, and limit strenuous "
                    "outdoor activity."
                ),
                "action": "reduce_heat_exposure",
            })

    # Strong-wind advice.
    if wind_speed is not None and wind_speed >= 40:
        recommendations.append({
            "type": "strong_wind",
            "message": (
                f"Strong winds of {wind_speed} km/h may affect outdoor "
                f"plans in {city}. Use caution and reconsider exposed "
                "outdoor activities."
            ),
            "action": "use_wind_caution",
        })

    # Fallback when no warning conditions are detected.
    if not recommendations:
        recommendations.append({
            "type": "weather",
            "message": (
                f"No major weather warning was triggered by the available "
                f"measurements for {city}. Check the forecast before "
                "outdoor plans."
            ),
            "action": "continue_as_planned",
        })

    return recommendations






@mcp.tool
async def get_daily_recommendations(
    city: str,
    user_sub: str = TokenClaim("sub"),
) -> dict:
    """Generate actionable recommendations using tasks, events, and weather."""

    recommendations = []

    # 1. Prioritize pending tasks.
    try:
        task_result = prioritize_tasks(user_sub)

        if not task_result.get("success"):
            raise RuntimeError("Task prioritization failed.")

        for task in task_result["prioritized_tasks"]:
            if task.get("overdue"):
                recommendations.append({
                    "type": "overdue_task",
                    "message": f"Address '{task['title']}' because it is overdue.",
                    "task_id": task["task_id"],
                })
            elif task.get("priority") == "high":
                recommendations.append({
                    "type": "high_priority_task",
                    "message": (
                        f"Prioritize '{task['title']}' "
                        "because it has high priority."
                    ),
                    "task_id": task["task_id"],
                })

    except Exception:
        return {
            "success": False,
            "error": "Unable to retrieve pending tasks.",
        }

    # 2. Retrieve upcoming calendar events.
    next_event = None

    try:
        now = datetime.now(timezone.utc)
        events = database.list_upcoming_events(
    from_time=now.isoformat(),
    user_sub=user_sub,
    limit=10,
)

        if events:
            next_event = events[0]

            event_time = datetime.fromisoformat(
                next_event["start_time"].replace("Z", "+00:00")
            )

            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            india_timezone = ZoneInfo("Asia/Kolkata")
            event_local = event_time.astimezone(india_timezone)
            now_local = now.astimezone(india_timezone)

            days_until = (event_local.date() - now_local.date()).days

            if days_until == 0:
                timing = "today"
            elif days_until == 1:
                timing = "tomorrow"
            else:
                timing = f"in {days_until} days"

            recommendations.append({
                "type": "upcoming_event",
                "message": (
                    f"Your next event is '{next_event['title']}', "
                    f"{timing}, at {event_local.strftime('%I:%M %p')}."
                ),
                "event_id": next_event["id"],
                "start_time_local": event_local.isoformat(),
                "days_until": days_until,
            })

    except Exception:
        recommendations.append({
            "type": "calendar_unavailable",
            "message": "Calendar information is temporarily unavailable.",
        })

    # 3. Check general weather with useful HTTP error details.
    try:
        weather = await fetch_weather(city)
        recommendations.extend(build_weather_recommendations(weather, city))

    except httpx.HTTPStatusError as exc:
        recommendations.append({
            "type": "weather_unavailable",
            "message": (
                f"Weather API returned HTTP {exc.response.status_code}. "
                "Check the weather service and try again."
            ),
        })

    except httpx.RequestError as exc:
        recommendations.append({
            "type": "weather_unavailable",
            "message": (
                "Could not connect to the weather service "
                f"({type(exc).__name__}). Check the network and retry."
            ),
        })

    except Exception as exc:
        recommendations.append({
            "type": "weather_unavailable",
            "message": f"Weather lookup failed: {type(exc).__name__}.",
        })

    # 4. Check weather across the actual event duration.
    if next_event is not None:
        try:
            event_start = datetime.fromisoformat(
                next_event["start_time"].replace("Z", "+00:00")
            )
            event_end = datetime.fromisoformat(
                next_event["end_time"].replace("Z", "+00:00")
            )

            if event_start.tzinfo is None or event_end.tzinfo is None:
                raise ValueError("Event timestamps must include a timezone.")

            duration_seconds = (event_end - event_start).total_seconds()

            if duration_seconds <= 0:
                raise ValueError("Event end time must be after start time.")

            duration_hours = max(
                1,
                int((duration_seconds + 3599) // 3600),
            )
            duration_hours = min(duration_hours, 12)

            event_weather = await get_hourly_forecast(
                city=city,
                start_time=next_event["start_time"],
                hours=duration_hours,
            )

            if not event_weather.get("success"):
                recommendations.append({
                    "type": "event_weather_unavailable",
                    "message": (
                        f"Couldn't retrieve the forecast for "
                        f"'{next_event['title']}'."
                    ),
                    "event_id": next_event["id"],
                    "weather_error": event_weather.get("error"),
                })

            else:
                forecasts = event_weather["forecasts"]
                hourly_alerts = []

                for forecast in forecasts:
                    alerts = []

                    rain_probability = forecast.get(
                        "precipitation_probability_percent"
                    )
                    precipitation = forecast.get("precipitation_mm")
                    temperature = forecast.get("temperature_c")
                    wind_speed = forecast.get("wind_speed_kmh")
                    weather_code = forecast.get("weather_code")

                    # Rain, drizzle, showers, and thunderstorms.
                    is_rainy_code = (
                        isinstance(weather_code, int)
                        and not isinstance(weather_code, bool)
                        and (
                            51 <= weather_code <= 67
                            or 80 <= weather_code <= 82
                            or 95 <= weather_code <= 99
                        )
                    )

                    if is_rainy_code:
                        alerts.append("drizzle, rain, or thunderstorms possible")
                    elif (
                        isinstance(rain_probability, (int, float))
                        and rain_probability >= 50
                    ):
                        alerts.append("rain is possible")
                    elif (
                        isinstance(precipitation, (int, float))
                        and precipitation >= 1
                    ):
                        alerts.append("measurable precipitation is expected")

                    # Heat.
                    if (
                        isinstance(temperature, (int, float))
                        and temperature >= 40
                    ):
                        alerts.append("extreme heat")
                    elif (
                        isinstance(temperature, (int, float))
                        and temperature >= 35
                    ):
                        alerts.append("high temperatures")

                    # Wind.
                    if (
                        isinstance(wind_speed, (int, float))
                        and wind_speed >= 40
                    ):
                        alerts.append("strong winds")

                    if alerts:
                        hourly_alerts.append({
                            "time": forecast["time"],
                            "alerts": alerts,
                        })

                if hourly_alerts:
                    alert_messages = [
                        f"{item['time']}: {', '.join(item['alerts'])}"
                        for item in hourly_alerts
                    ]

                    recommendations.append({
                        "type": "event_weather_alert",
                        "message": (
                            f"Weather may affect '{next_event['title']}': "
                            + "; ".join(alert_messages)
                            + ". Consider rain protection or adjusting "
                            "outdoor plans if needed."
                        ),
                        "action": "prepare_for_event_weather",
                        "event_id": next_event["id"],
                        "affected_hours": hourly_alerts,
                    })

                else:
                    recommendations.append({
                        "type": "event_weather",
                        "message": (
                            f"No major weather warning was detected "
                            f"throughout the forecast window for "
                            f"'{next_event['title']}'."
                        ),
                        "event_id": next_event["id"],
                        "forecasts": forecasts,
                    })

        except httpx.HTTPStatusError as exc:
            recommendations.append({
                "type": "event_weather_unavailable",
                "message": (
                    f"Weather API returned HTTP {exc.response.status_code} "
                    f"while checking '{next_event['title']}'."
                ),
                "event_id": next_event["id"],
            })

        except Exception as exc:
            recommendations.append({
                "type": "event_weather_unavailable",
                "message": (
                    f"Unable to check event-time weather: "
                    f"{type(exc).__name__}."
                ),
                "event_id": next_event["id"],
            })

    # 5. Fallback if there is nothing to recommend.
    if not recommendations:
        recommendations.append({
            "type": "general",
            "message": "Review your plans and choose a task to work on next.",
        })

    return {
        "success": True,
        "city": city,
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }





if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=8000,
        path="/mcp",
    )
