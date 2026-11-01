from datetime import datetime as real_datetime, timezone
import unittest
from unittest.mock import Mock, patch

from server_test_support import LOCAL_USER_ONE_SUB, load_test_server


server = load_test_server("_smart_daily_assistant_server_for_calendar_tests")


FIXED_NOW = real_datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
class FixedDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW.replace(tzinfo=None)
        return FIXED_NOW.astimezone(tz)


class CalendarEventTests(unittest.TestCase):
    event = {"id": 1, "title": "Project review"}

    def call_add_calendar_event(self, start_time, end_time):
        with patch.object(
            server.database,
            "create_calendar_event",
            return_value=self.event,
        ) as create_event_mock:
            result = server.add_calendar_event(
                "Project review",
                start_time,
                end_time,
                user_sub=LOCAL_USER_ONE_SUB,
            )

        return result, create_event_mock

    def call_get_upcoming_events(self, limit):
        with patch.object(
            server.database,
            "list_upcoming_events",
            return_value=[self.event],
        ) as list_events_mock:
            with patch.object(server, "datetime", FixedDateTime):
                result = server.get_upcoming_events(
                    limit,
                    user_sub=LOCAL_USER_ONE_SUB,
                )

        return result, list_events_mock

    def test_timezone_offsets_are_normalized_to_utc(self):
        result, create_event_mock = self.call_add_calendar_event(
            "2026-10-18T17:00:00+05:30",
            "2026-10-18T19:00:00+05:30",
        )

        self.assertEqual(result, {"success": True, "event": self.event})
        create_event_mock.assert_called_once_with(
            "Project review",
            "2026-10-18T11:30:00+00:00",
            "2026-10-18T13:30:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
        )

    def test_utc_z_timestamps_are_accepted(self):
        result, create_event_mock = self.call_add_calendar_event(
            "2026-10-18T11:30:00Z",
            "2026-10-18T13:30:00Z",
        )

        self.assertEqual(result, {"success": True, "event": self.event})
        create_event_mock.assert_called_once_with(
            "Project review",
            "2026-10-18T11:30:00+00:00",
            "2026-10-18T13:30:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
        )

    def test_naive_timestamps_are_rejected(self):
        cases = (
            (
                "naive start",
                "2026-10-18T11:30:00",
                "2026-10-18T13:30:00Z",
            ),
            (
                "naive end",
                "2026-10-18T11:30:00Z",
                "2026-10-18T13:30:00",
            ),
        )

        for case_name, start_time, end_time in cases:
            with self.subTest(case=case_name):
                result, create_event_mock = self.call_add_calendar_event(
                    start_time,
                    end_time,
                )

                self.assertEqual(
                    result,
                    {
                        "success": False,
                        "error": "Timestamps must include a timezone.",
                    },
                )
                create_event_mock.assert_not_called()

    def test_invalid_iso_timestamp_returns_failure(self):
        result, create_event_mock = self.call_add_calendar_event(
            "not-a-timestamp",
            "2026-10-18T13:30:00Z",
        )

        self.assertFalse(result["success"])
        self.assertEqual(set(result), {"success", "error"})
        self.assertIsInstance(result["error"], str)
        create_event_mock.assert_not_called()

    def test_end_time_must_be_after_start_time(self):
        start_time = "2026-10-18T12:00:00Z"
        cases = (
            ("equal", start_time),
            ("earlier", "2026-10-18T11:59:00Z"),
        )

        for case_name, end_time in cases:
            with self.subTest(case=case_name):
                result, create_event_mock = self.call_add_calendar_event(
                    start_time,
                    end_time,
                )

                self.assertEqual(
                    result,
                    {
                        "success": False,
                        "error": "End time must be after start time.",
                    },
                )
                create_event_mock.assert_not_called()

    def test_upcoming_events_uses_fixed_utc_time_and_limit(self):
        result, list_events_mock = self.call_get_upcoming_events(4)

        self.assertEqual(
            result,
            {
                "success": True,
                "count": 1,
                "events": [self.event],
            },
        )
        list_events_mock.assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=4,
        )

    def test_invalid_limits_are_rejected(self):
        for limit in (0, 51):
            with self.subTest(limit=limit):
                result, list_events_mock = self.call_get_upcoming_events(limit)

                self.assertEqual(
                    result,
                    {
                        "success": False,
                        "error": "Limit must be between 1 and 50.",
                    },
                )
                list_events_mock.assert_not_called()

    def test_successful_upcoming_events_response_structure(self):
        events = [self.event, {"id": 2, "title": "Planning"}]
        with patch.object(
            server.database,
            "list_upcoming_events",
            return_value=events,
        ) as list_events_mock:
            with patch.object(server, "datetime", FixedDateTime):
                result = server.get_upcoming_events(
                    user_sub=LOCAL_USER_ONE_SUB,
                )

        self.assertEqual(
            result,
            {
                "success": True,
                "count": 2,
                "events": events,
            },
        )
        list_events_mock.assert_called_once_with(
            from_time="2026-10-18T12:00:00+00:00",
            user_sub=LOCAL_USER_ONE_SUB,
            limit=10,
        )


if __name__ == "__main__":
    unittest.main()