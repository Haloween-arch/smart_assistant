
import httpx


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


async def get_weather(city: str) -> dict:
    city = city.strip()

    if not city:
        raise ValueError("City cannot be empty.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Find the city's latitude and longitude.
        geo_response = await client.get(
            GEOCODING_URL,
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        results = geo_data.get("results", [])
        if not results:
            return {
                "success": False,
                "error": f"No location found for '{city}'.",
            }

        location = results[0]
        latitude = location["latitude"]
        longitude = location["longitude"]

        # 2. Request the current weather.
        weather_response = await client.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "apparent_temperature,"
                    "is_day,"
                    "precipitation,"
                    "weather_code,"
                    "wind_speed_10m"
                ),
                "timezone": "auto",
            },
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()

    current = weather_data["current"]

    return {
        "success": True,
        "location": {
            "name": location["name"],
            "country": location.get("country"),
            "latitude": latitude,
            "longitude": longitude,
        },
        "timezone": weather_data.get("timezone"),
        "observed_at": current.get("time"),
        "temperature_c": current["temperature_2m"],
        "feels_like_c": current["apparent_temperature"],
        "humidity_percent": current["relative_humidity_2m"],
        "precipitation_mm": current["precipitation"],
        "wind_speed_kmh": current["wind_speed_10m"],
        "is_day": bool(current["is_day"]),
        "weather_code": current["weather_code"],
    }



async def get_hourly_forecast(
    city: str,
    start_time: str,
    hours: int = 3,
) -> dict:
    """Get hourly weather forecasts across an event's duration."""

    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    city = city.strip()

    if not city:
        raise ValueError("City cannot be empty.")

    if not 1 <= hours <= 12:
        raise ValueError("Hours must be between 1 and 12.")

    try:
        event_time = datetime.fromisoformat(
            start_time.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        raise ValueError(
            "start_time must be a valid ISO 8601 datetime."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Resolve the city.
        geo_response = await client.get(
            GEOCODING_URL,
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        geo_response.raise_for_status()

        results = geo_response.json().get("results", [])

        if not results:
            return {
                "success": False,
                "error": f"No location found for '{city}'.",
            }

        location = results[0]

        # 2. Request hourly forecast data.
        forecast_params = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "hourly": (
                "temperature_2m,"
                "precipitation_probability,"
                "precipitation,"
                "weather_code,"
                "wind_speed_10m"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        }

        try:
            forecast_response = await client.get(
                FORECAST_URL,
                params=forecast_params,
            )
            forecast_response.raise_for_status()
            data = forecast_response.json()

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            return {
                "success": False,
                "error": "Weather forecast service returned an error.",
                "status_code": status_code,
                "retryable": status_code in (
                    429, 500, 502, 503, 504
                ),
            }

        except httpx.RequestError:
            return {
                "success": False,
                "error": (
                    "Unable to connect to the weather forecast service."
                ),
                "retryable": True,
            }

    # 3. Resolve the location's timezone.
    timezone_name = data.get("timezone")

    if not timezone_name:
        return {
            "success": False,
            "error": "Forecast timezone is unavailable.",
        }

    try:
        local_zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return {
            "success": False,
            "error": "Forecast timezone could not be loaded.",
            "timezone_received": timezone_name,
        }

    # 4. Convert the event start time to local time.
    if event_time.tzinfo is not None:
        event_local = event_time.astimezone(local_zone)
    else:
        event_local = event_time.replace(tzinfo=local_zone)

    # 5. Build the requested hourly time window.
    # hours=3 returns the start hour and the next two hours.
    requested_times = [
        event_local.replace(minute=0, second=0, microsecond=0)
        + timedelta(hours=offset)
        for offset in range(hours)
    ]

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])

    if not times:
        return {
            "success": False,
            "error": "Hourly forecast data is unavailable.",
        }

    # Open-Meteo hourly timestamps are local wall-clock times.
    time_to_index = {
        datetime.fromisoformat(time_text): index
        for index, time_text in enumerate(times)
    }

    required_fields = (
        "temperature_2m",
        "precipitation_probability",
        "precipitation",
        "weather_code",
        "wind_speed_10m",
    )

    if any(field not in hourly for field in required_fields):
        return {
            "success": False,
            "error": "Hourly forecast fields are incomplete.",
        }

    # 6. Collect forecasts for every requested hour.
    forecasts = []

    for requested_time in requested_times:
        index = time_to_index.get(requested_time.replace(tzinfo=None))

        if index is None:
            return {
                "success": False,
                "error": (
                    "The forecast does not cover the entire event window."
                ),
                "missing_hour": requested_time.isoformat(),
                "timezone": timezone_name,
            }

        if any(index >= len(hourly[field]) for field in required_fields):
            return {
                "success": False,
                "error": "Hourly forecast fields are incomplete.",
            }

        forecasts.append({
            "time": requested_time.isoformat(),
            "temperature_c": hourly["temperature_2m"][index],
            "precipitation_probability_percent": (
                hourly["precipitation_probability"][index]
            ),
            "precipitation_mm": hourly["precipitation"][index],
            "weather_code": hourly["weather_code"][index],
            "wind_speed_kmh": hourly["wind_speed_10m"][index],
        })

    return {
        "success": True,
        "location": location["name"],
        "timezone": timezone_name,
        "event_start_local": event_local.isoformat(),
        "duration_hours": hours,
        "forecasts": forecasts,
    }
