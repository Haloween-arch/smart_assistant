from datetime import datetime as real_datetime, timezone
import unittest
from unittest.mock import Mock, patch

from server_test_support import LOCAL_USER_ONE_SUB, load_test_server


server = load_test_server("_smart_daily_assistant_server_for_task_tests")


FIXED_NOW = real_datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
class FixedDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW.replace(tzinfo=None)
        return FIXED_NOW.astimezone(tz)


def make_task(task_id, **fields):
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        **fields,
    }


class PrioritizeTasksTests(unittest.TestCase):
    def prioritize(self, tasks):
        with patch.object(
            server.database,
            "list_tasks",
            return_value=list(tasks),
        ) as list_tasks_mock:
            with patch.object(server, "datetime", FixedDateTime):
                result = server.prioritize_tasks(user_sub=LOCAL_USER_ONE_SUB)

            list_tasks_mock.assert_called_once_with(
                user_sub=LOCAL_USER_ONE_SUB,
                pending_only=True,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], len(tasks))
        return result["prioritized_tasks"]

    def assert_ranking(self, ranked, task_ids, overdue_values):
        self.assertEqual(
            [task["task_id"] for task in ranked],
            task_ids,
        )
        self.assertEqual(
            [task["overdue"] for task in ranked],
            overdue_values,
        )

    def test_priorities_sort_high_medium_low_when_not_overdue(self):
        due_date = "2026-10-19T12:00:00+00:00"
        tasks = [
            make_task(1, priority="low", due_date=due_date),
            make_task(2, priority="medium", due_date=due_date),
            make_task(3, priority="high", due_date=due_date),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [3, 2, 1], [False, False, False])

    def test_overdue_low_priority_sorts_before_future_high_priority(self):
        tasks = [
            make_task(
                1,
                priority="high",
                due_date="2026-10-19T12:00:00+00:00",
            ),
            make_task(
                2,
                priority="low",
                due_date="2026-10-17T12:00:00+00:00",
            ),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [2, 1], [True, False])

    def test_earlier_deadline_sorts_first_for_same_status_and_priority(self):
        tasks = [
            make_task(
                1,
                priority="medium",
                due_date="2026-10-18T16:00:00+00:00",
            ),
            make_task(
                2,
                priority="medium",
                due_date="2026-10-18T13:00:00+00:00",
            ),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [2, 1], [False, False])

    def test_valid_deadline_sorts_before_missing_deadline_on_tie(self):
        tasks = [
            make_task(1, priority="medium"),
            make_task(
                2,
                priority="medium",
                due_date="2026-10-19T12:00:00+00:00",
            ),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [2, 1], [False, False])

    def test_requests_pending_tasks_and_ranks_returned_tasks(self):
        tasks = [
            make_task(1, priority="low"),
            make_task(2, priority="high"),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [2, 1], [False, False])

    def test_missing_and_unrecognized_priorities_rank_as_medium(self):
        tasks = [
            make_task(1, priority="low"),
            make_task(2, priority="urgent"),
            make_task(3),
            make_task(4, priority="medium"),
            make_task(5, priority="high"),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(
            ranked,
            [5, 2, 3, 4, 1],
            [False, False, False, False, False],
        )

    def test_invalid_and_missing_due_dates_are_unavailable(self):
        tasks = [
            make_task(1),
            make_task(2, due_date="not-a-date"),
            make_task(3, due_date="2026-10-19T12:00:00+00:00"),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [3, 1, 2], [False, False, False])

    def test_timezone_aware_and_date_only_due_dates(self):
        tasks = [
            make_task(
                1,
                priority="medium",
                due_date="2026-10-18T12:00:00+01:00",
            ),
            make_task(
                2,
                priority="medium",
                due_date="2026-10-18",
            ),
        ]

        ranked = self.prioritize(tasks)

        self.assert_ranking(ranked, [2, 1], [True, True])


if __name__ == "__main__":
    unittest.main()