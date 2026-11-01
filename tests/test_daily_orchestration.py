from contextlib import ExitStack
from datetime import datetime as real_datetime, timedelta, timezone
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from server_test_support import LOCAL_USER_ONE_SUB, load_test_server


server = load_test_server("_smart_daily_assistant_server_for_orchestration_tests")


CITY = "Bengaluru"
FIXED_NOW = real_datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
FIXED_LOCAL_ZONE = timezone(timedelta(hours=5, minutes=30))
_UNSET = object()


class FixedDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW.replace(tzinfo=None)
        return FIXED_NOW.astimezone(tz)


def current_weather():
    return {
        "success": True,
        "temperature_c": 22,
        "feels_like_c": 22,
        "precipitation_mm": 0,
        "wind_speed_kmh": 10,
        "weather_code": 0,
    }


def upcoming_event():
    return {
        "id": 21,
        "title": "Morning run",
        "start_time": "2026-10-19T04:00:00+00:00",
        "end_time": "2026-10-19T05:30:00+00:00",
    }


def rainy_event_forecast():
    return {
        "success": True,
        "forecasts": [
            {
                "time": "2026-10-19T09:00:00+05:30",
                "temperature_c": 22,
                "precipitation_probability_percent": 60,
                "precipitation_mm": 0,
                "weather_code": 0,
                "wind_speed_kmh": 10,
            },
            {
                "time": "2026-10-19T10:00:00+05:30",
                "temperature_c": 22,
                "precipitation_probability_percent": 10,
                "precipitation_mm": 0,
                "weather_code": 0,
                "wind_speed_kmh": 10,
            },
        ],
    }


def benign_event_forecast():
    return {
        "success": True,
        "forecasts": [
            {
                "time": "2026-10-19T09:00:00+05:30",
                "temperature_c": 22,
                "precipitation_probability_percent": 10,
                "precipitation_mm": 0,
                "weather_code": 0,
                "wind_speed_kmh": 10,
            },
            {
                "time": "2026-10-19T10:00:00+05:30",
                "temperature_c": 22,
                "precipitation_probability_percent": 10,
                "precipitation_mm": 0,
                "weather_code": 0,
                "wind_speed_kmh": 10,
            },
        ],
    }


def http_status_error(status_code):
    request = httpx.Request("GET", "https://weather.test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        "weather request failed",
        request=request,
        response=response,
    )


class DailyOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def run_briefing(
        self,
        *,
        tasks=None,
        events=None,
        weather=_UNSET,
        task_exception=None,
        event_exception=None,
        weather_exception=None,
    ):
        tasks = [] if tasks is None else [dict(task) for task in tasks]
        events = [] if events is None else list(events)
        if weather is _UNSET:
            weather = current_weather()

        with ExitStack() as stack:
            weather_mock = stack.enter_context(
                patch.object(server, "fetch_weather", new_callable=AsyncMock)
            )
            task_mock = stack.enter_context(
                patch.object(server.database, "list_tasks")
            )
            event_mock = stack.enter_context(
                patch.object(server.database, "list_upcoming_events")
            )
            stack.enter_context(
                patch.object(server, "datetime", FixedDateTime)
            )

            weather_mock.return_value = weather
            task_mock.return_value = tasks
            event_mock.return_value = events

            if weather_exception is not None:
                weather_mock.side_effect = weather_exception
            if task_exception is not None:
                task_mock.side_effect = task_exception
            if event_exception is not None:
                event_mock.side_effect = event_exception

            result = await server.get_daily_briefing(
                CITY,
                user_sub=LOCAL_USER_ONE_SUB,
            )

        return result, {
            "weather": weather_mock,
            "tasks": task_mock,
            "events": event_mock,
        }

    async def run_recommendations(
        self,
        *,
        task_result=_UNSET,
        task_exception=None,
        events=None,
        event_exception=None,
        weather=_UNSET,
        weather_exception=None,
        forecast=_UNSET,
        forecast_exception=None,
        empty_weather_recommendations=False,
        use_real_prioritizer=False,
        raw_tasks=None,
    ):
        events = [] if events is None else list(events)
        raw_tasks = [] if raw_tasks is None else [
            dict(task) for task in raw_tasks
        ]
        if weather is _UNSET:
            weather = current_weather()
        if forecast is _UNSET:
            forecast = {"success": True, "forecasts": []}

        with ExitStack() as stack:
            task_database_mock = stack.enter_context(
                patch.object(
                    server.database,
                    "list_tasks",
                    return_value=raw_tasks,
                )
            )
            event_mock = stack.enter_context(
                patch.object(server.database, "list_upcoming_events")
            )
            weather_mock = stack.enter_context(
                patch.object(server, "fetch_weather", new_callable=AsyncMock)
            )
            forecast_mock = stack.enter_context(
                patch.object(
                    server,
                    "get_hourly_forecast",
                    new_callable=AsyncMock,
                )
            )
            stack.enter_context(
                patch.object(server, "datetime", FixedDateTime)
            )
            stack.enter_context(
                patch.object(
                    server,
                    "ZoneInfo",
                    side_effect=lambda _name: FIXED_LOCAL_ZONE,
                )
            )

            event_mock.return_value = events
            weather_mock.return_value = weather
            forecast_mock.return_value = forecast

            if event_exception is not None:
                event_mock.side_effect = event_exception
            if weather_exception is not None:
                weather_mock.side_effect = weather_exception
            if forecast_exception is not None:
                forecast_mock.side_effect = forecast_exception

            prioritizer_mock = None
            if not use_real_prioritizer:
                prioritizer_mock = stack.enter_context(
                    patch.object(server, "prioritize_tasks")
                )
                if task_exception is not None:
                    prioritizer_mock.side_effect = task_exception
                elif task_result is _UNSET:
                    prioritizer_mock.return_value = {
                        "success": True,
                        "count": 0,
                        "prioritized_tasks": [],
                    }
                else:
                    prioritizer_mock.return_value = task_result

            builder_mock = None
            if empty_weather_recommendations:
                builder_mock = stack.enter_context(
                    patch.object(
                        server,
                        "build_weather_recommendations",
                        return_value=[],
                    )
                )

            result = await server.get_daily_recommendations(
                CITY,
                user_sub=LOCAL_USER_ONE_SUB,
            )

        return result, {
            "prioritizer": prioritizer_mock,
            "tasks": task_database_mock,
            "events": event_mock,
            "weather": weather_mock,
            "forecast": forecast_mock,
            "builder": builder_mock,
        }

    async def test_briefing_aggregates_weather_tasks_and_events(self):
        tasks = [
            {"id": 1, "title": "Draft report", "completed": 0},
            {"id": 2, "title": "Review notes", "completed": 0},
        ]
        events = [upcoming_event()]
        weather = current_weather()

        result, mocks = await self.run_briefing(
            tasks=tasks,
            events=events,
            weather=weather,
        )

        self.assertEqual(
            result,
            {
                "city": CITY,
                "weather": weather,
                "pending_tasks": {
                    "count": 2,
                    "items": [
                        {"id": 1, "title": "Draft report", "completed": False},
                        {"id": 2, "title": "Review notes", "completed": False},
                    ],
                },
                "upcoming_events": {
                    "count": 1,
                    "items": events,
                },
            },
        )
        for task in result["pending_tasks"]["items"]:
            self.assertIs(task["completed"], False)
        mocks["weather"].assert_awaited_once_with(CITY)
        mocks["tasks"].assert_called_once_with(
            user_sub=LOCAL_USER_ONE_SUB,
            pending_only=True,
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )

    async def test_briefing_handles_empty_tasks_and_events(self):
        result, mocks = await self.run_briefing(tasks=[], events=[])

        self.assertEqual(result["pending_tasks"], {"count": 0, "items": []})
        self.assertEqual(result["upcoming_events"], {"count": 0, "items": []})
        self.assertEqual(result["weather"], current_weather())
        mocks["tasks"].assert_called_once_with(
            user_sub=LOCAL_USER_ONE_SUB,
            pending_only=True,
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )

    async def test_briefing_preserves_returned_weather_failure(self):
        weather = {
            "success": False,
            "error": "No location found for 'Bengaluru'.",
        }

        result, mocks = await self.run_briefing(weather=weather)

        self.assertEqual(result["weather"], weather)
        mocks["weather"].assert_awaited_once_with(CITY)

    async def test_briefing_converts_weather_exception_to_failure_object(self):
        result, mocks = await self.run_briefing(
            weather_exception=RuntimeError("offline")
        )

        self.assertEqual(
            result["weather"],
            {
                "success": False,
                "error": "Weather is temporarily unavailable.",
            },
        )
        mocks["weather"].assert_awaited_once_with(CITY)

    async def test_briefing_task_exception_returns_empty_task_list(self):
        result, mocks = await self.run_briefing(
            task_exception=RuntimeError("database error"),
            events=[upcoming_event()],
        )

        self.assertEqual(result["pending_tasks"], {"count": 0, "items": []})
        self.assertEqual(result["upcoming_events"]["count"], 1)
        mocks["tasks"].assert_called_once_with(
            user_sub=LOCAL_USER_ONE_SUB,
            pending_only=True,
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )

    async def test_briefing_event_exception_returns_empty_event_list(self):
        result, mocks = await self.run_briefing(
            tasks=[{"id": 3, "title": "Read", "completed": 0}],
            event_exception=RuntimeError("database error"),
        )

        self.assertEqual(result["pending_tasks"]["count"], 1)
        self.assertIs(result["pending_tasks"]["items"][0]["completed"], False)
        self.assertEqual(result["upcoming_events"], {"count": 0, "items": []})
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )

    async def test_recommendations_aggregate_tasks_event_and_weather(self):
        event = upcoming_event()
        task_result = {
            "success": True,
            "count": 2,
            "prioritized_tasks": [
                {
                    "task_id": 7,
                    "title": "Finish report",
                    "priority": "high",
                    "overdue": False,
                },
                {
                    "task_id": 8,
                    "title": "Submit invoice",
                    "priority": "medium",
                    "overdue": True,
                },
            ],
        }

        result, mocks = await self.run_recommendations(
            task_result=task_result,
            events=[event],
            forecast=rainy_event_forecast(),
        )

        recommendations = result["recommendations"]
        self.assertTrue(result["success"])
        self.assertEqual(result["city"], CITY)
        self.assertEqual(
            [item["type"] for item in recommendations],
            [
                "high_priority_task",
                "overdue_task",
                "upcoming_event",
                "weather",
                "event_weather_alert",
            ],
        )
        self.assertEqual(
            recommendations[0]["message"],
            "Prioritize 'Finish report' because it has high priority.",
        )
        self.assertEqual(
            recommendations[1]["message"],
            "Address 'Submit invoice' because it is overdue.",
        )
        self.assertEqual(
            recommendations[2],
            {
                "type": "upcoming_event",
                "message": (
                    "Your next event is 'Morning run', tomorrow, at 09:30 AM."
                ),
                "event_id": 21,
                "start_time_local": "2026-10-19T09:30:00+05:30",
                "days_until": 1,
            },
        )
        self.assertEqual(
            recommendations[3]["message"],
            "No major weather warning was triggered by the available "
            "measurements for Bengaluru. Check the forecast before "
            "outdoor plans.",
        )
        self.assertEqual(
            recommendations[4]["affected_hours"],
            [{
                "time": "2026-10-19T09:00:00+05:30",
                "alerts": ["rain is possible"],
            }],
        )
        self.assertEqual(
            recommendations[4]["message"],
            "Weather may affect 'Morning run': "
            "2026-10-19T09:00:00+05:30: rain is possible. "
            "Consider rain protection or adjusting outdoor plans if needed.",
        )
        self.assertEqual(
            result["recommendation_count"],
            len(recommendations),
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )
        mocks["weather"].assert_awaited_once_with(CITY)
        mocks["forecast"].assert_awaited_once_with(
            city=CITY,
            start_time=event["start_time"],
            hours=2,
        )

    async def test_recommendations_task_failure_object_returns_failure(self):
        result, mocks = await self.run_recommendations(
            task_result={"success": False, "error": "unavailable"},
        )

        self.assertEqual(
            result,
            {
                "success": False,
                "error": "Unable to retrieve pending tasks.",
            },
        )
        mocks["prioritizer"].assert_called_once_with(LOCAL_USER_ONE_SUB)
        mocks["events"].assert_not_called()
        mocks["weather"].assert_not_awaited()

    async def test_recommendations_task_exception_returns_failure(self):
        result, mocks = await self.run_recommendations(
            task_exception=RuntimeError("database error"),
        )

        self.assertEqual(
            result,
            {
                "success": False,
                "error": "Unable to retrieve pending tasks.",
            },
        )
        mocks["prioritizer"].assert_called_once_with(LOCAL_USER_ONE_SUB)
        mocks["events"].assert_not_called()

    async def test_recommendations_calendar_exception_adds_category(self):
        result, mocks = await self.run_recommendations(
            event_exception=RuntimeError("database error"),
        )

        recommendations = result["recommendations"]
        self.assertEqual(
            [item["type"] for item in recommendations],
            ["calendar_unavailable", "weather"],
        )
        self.assertEqual(
            recommendations[0]["message"],
            "Calendar information is temporarily unavailable.",
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )
        mocks["forecast"].assert_not_awaited()

    async def test_empty_events_skip_event_time_forecast(self):
        result, mocks = await self.run_recommendations(events=[])

        self.assertEqual(
            [item["type"] for item in result["recommendations"]],
            ["weather"],
        )
        mocks["events"].assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )
        mocks["forecast"].assert_not_awaited()

    async def test_current_weather_failure_paths(self):
        request = httpx.Request("GET", "https://weather.test")
        connect_error = httpx.ConnectError("offline", request=request)
        cases = (
            (
                "returned failure object",
                {"weather": {"success": False, "error": "unavailable"}},
                "Weather data is unavailable for Bengaluru.",
            ),
            (
                "generic exception",
                {"weather_exception": RuntimeError("offline")},
                "Weather lookup failed: RuntimeError.",
            ),
            (
                "HTTP status exception",
                {"weather_exception": http_status_error(503)},
                "Weather API returned HTTP 503. Check the weather service "
                "and try again.",
            ),
            (
                "request exception",
                {"weather_exception": connect_error},
                "Could not connect to the weather service (ConnectError). "
                "Check the network and retry.",
            ),
        )

        for case_name, options, expected_message in cases:
            with self.subTest(case=case_name):
                result, mocks = await self.run_recommendations(**options)

                self.assertEqual(
                    [item["type"] for item in result["recommendations"]],
                    ["weather_unavailable"],
                )
                self.assertEqual(
                    result["recommendations"][0]["message"],
                    expected_message,
                )
                mocks["weather"].assert_awaited_once_with(CITY)

    async def test_event_forecast_failure_object_is_reported(self):
        event = upcoming_event()
        result, mocks = await self.run_recommendations(
            events=[event],
            forecast={
                "success": False,
                "error": "forecast unavailable",
            },
        )

        recommendation = next(
            item
            for item in result["recommendations"]
            if item["type"] == "event_weather_unavailable"
        )
        self.assertEqual(
            recommendation,
            {
                "type": "event_weather_unavailable",
                "message": "Couldn't retrieve the forecast for 'Morning run'.",
                "event_id": 21,
                "weather_error": "forecast unavailable",
            },
        )
        mocks["forecast"].assert_awaited_once_with(
            city=CITY,
            start_time=event["start_time"],
            hours=2,
        )

    async def test_event_forecast_exceptions_are_reported(self):
        event = upcoming_event()
        cases = (
            (
                "generic exception",
                RuntimeError("offline"),
                "Unable to check event-time weather: RuntimeError.",
            ),
            (
                "HTTP status exception",
                http_status_error(502),
                "Weather API returned HTTP 502 while checking "
                "'Morning run'.",
            ),
        )

        for case_name, error, expected_message in cases:
            with self.subTest(case=case_name):
                result, mocks = await self.run_recommendations(
                    events=[event],
                    forecast_exception=error,
                )

                recommendation = next(
                    item
                    for item in result["recommendations"]
                    if item["type"] == "event_weather_unavailable"
                )
                self.assertEqual(recommendation["message"], expected_message)
                self.assertEqual(recommendation["event_id"], event["id"])
                mocks["forecast"].assert_awaited_once_with(
                    city=CITY,
                    start_time=event["start_time"],
                    hours=2,
                )

    async def test_event_forecast_without_alerts_adds_event_weather(self):
        event = upcoming_event()
        forecast = benign_event_forecast()
        result, mocks = await self.run_recommendations(
            events=[event],
            forecast=forecast,
        )

        recommendation = next(
            item
            for item in result["recommendations"]
            if item["type"] == "event_weather"
        )
        self.assertEqual(
            recommendation,
            {
                "type": "event_weather",
                "message": (
                    "No major weather warning was detected throughout the "
                    "forecast window for 'Morning run'."
                ),
                "event_id": 21,
                "forecasts": forecast["forecasts"],
            },
        )
        mocks["forecast"].assert_awaited_once_with(
            city=CITY,
            start_time=event["start_time"],
            hours=2,
        )

    async def test_general_fallback_when_no_recommendations_are_built(self):
        result, mocks = await self.run_recommendations(
            events=[],
            empty_weather_recommendations=True,
        )

        self.assertEqual(
            result["recommendations"],
            [{
                "type": "general",
                "message": "Review your plans and choose a task to work on next.",
            }],
        )
        self.assertEqual(result["recommendation_count"], 1)
        mocks["builder"].assert_called_once_with(current_weather(), CITY)
        mocks["forecast"].assert_not_awaited()

    async def test_real_prioritizer_uses_only_mocked_database_tasks(self):
        result, mocks = await self.run_recommendations(
            use_real_prioritizer=True,
            raw_tasks=[
                {
                    "id": 12,
                    "title": "Prepare slides",
                    "priority": "high",
                    "due_date": "2026-10-20T12:00:00+00:00",
                },
            ],
            events=[],
        )

        mocks["tasks"].assert_called_once_with(
            user_sub=LOCAL_USER_ONE_SUB,
            pending_only=True,
        )
        high_priority = next(
            item
            for item in result["recommendations"]
            if item["type"] == "high_priority_task"
        )
        self.assertEqual(high_priority["task_id"], 12)
        self.assertEqual(
            high_priority["message"],
            "Prioritize 'Prepare slides' because it has high priority.",
        )


if __name__ == "__main__":
    unittest.main()