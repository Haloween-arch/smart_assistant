import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from server_test_support import (
    LOCAL_USER_ONE_SUB,
    LOCAL_USER_ONE_TOKEN,
    LOCAL_USER_TWO_SUB,
    LOCAL_USER_TWO_TOKEN,
    load_test_server,
    make_test_access_token,
)


server = load_test_server("_smart_daily_assistant_server_for_mcp_tests")


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database_mocks = {}
        for database_function in (
            "create_task",
            "list_tasks",
            "complete_task",
            "create_calendar_event",
            "list_upcoming_events",
        ):
            patcher = patch.object(server.database, database_function)
            self.database_mocks[database_function] = patcher.start()
            self.addCleanup(patcher.stop)

        weather_patcher = patch.object(
            server,
            "fetch_weather",
            new_callable=AsyncMock,
        )
        self.fetch_weather = weather_patcher.start()
        self.addCleanup(weather_patcher.stop)

        forecast_patcher = patch.object(
            server,
            "get_hourly_forecast",
            new_callable=AsyncMock,
        )
        self.get_hourly_forecast = forecast_patcher.start()
        self.addCleanup(forecast_patcher.stop)

        access_token_patcher = patch(
            "fastmcp.server.dependencies.get_access_token",
            return_value=make_test_access_token(LOCAL_USER_ONE_SUB),
        )
        self.get_access_token = access_token_patcher.start()
        self.addCleanup(access_token_patcher.stop)

    async def test_mcp_lists_registered_tools_and_input_schemas(self):
        async with Client(FastMCPTransport(mcp=server.mcp)) as client:
            tools = await client.list_tools()

        tool_schemas = {
            tool.name: tool.inputSchema
            for tool in tools
        }
        self.assertEqual(
            set(tool_schemas),
            {
                "get_daily_briefing",
                "add_task",
                "list_tasks",
                "complete_task",
                "get_weather",
                "add_calendar_event",
                "get_upcoming_events",
                "prioritize_tasks",
                "get_daily_recommendations",
            },
        )

        for tool_name, required in {
            "get_daily_briefing": ["city"],
            "add_task": ["title"],
            "list_tasks": [],
            "complete_task": ["task_id"],
            "get_weather": ["city"],
            "add_calendar_event": ["title", "start_time", "end_time"],
            "get_upcoming_events": [],
            "prioritize_tasks": [],
            "get_daily_recommendations": ["city"],
        }.items():
            self.assertEqual(
                tool_schemas[tool_name].get("required", []),
                required,
                tool_name,
            )

        schemas = tool_schemas
        self.assertEqual(
            schemas["get_daily_briefing"]["properties"]["city"]["type"],
            "string",
        )
        self.assertEqual(
            schemas["add_task"]["properties"]["priority"]["default"],
            "medium",
        )
        self.assertEqual(
            schemas["add_task"]["properties"]["due_date"]["default"],
            None,
        )
        self.assertEqual(
            schemas["add_task"]["properties"]["due_date"]["anyOf"],
            [{"type": "string"}, {"type": "null"}],
        )
        self.assertEqual(
            schemas["list_tasks"]["properties"]["pending_only"]["default"],
            True,
        )
        self.assertEqual(
            schemas["complete_task"]["properties"]["task_id"]["type"],
            "integer",
        )
        self.assertEqual(
            schemas["add_calendar_event"]["required"],
            ["title", "start_time", "end_time"],
        )
        self.assertEqual(
            schemas["get_upcoming_events"]["properties"]["limit"]["default"],
            10,
        )
        self.assertEqual(
            schemas["prioritize_tasks"]["properties"],
            {},
        )
        for tool_name in (
            "get_daily_briefing",
            "add_task",
            "list_tasks",
            "complete_task",
            "add_calendar_event",
            "get_upcoming_events",
            "prioritize_tasks",
            "get_daily_recommendations",
        ):
            self.assertNotIn("user_sub", schemas[tool_name]["properties"])

    async def test_local_bearer_tokens_map_to_distinct_users(self):
        user_one = await server.mcp.auth.verify_token(LOCAL_USER_ONE_TOKEN)
        user_two = await server.mcp.auth.verify_token(LOCAL_USER_TWO_TOKEN)
        invalid = await server.mcp.auth.verify_token("invalid-local-token")

        self.assertEqual(user_one.claims["sub"], LOCAL_USER_ONE_SUB)
        self.assertEqual(user_two.claims["sub"], LOCAL_USER_TWO_SUB)
        self.assertIsNone(invalid)

    async def test_valid_tool_call_returns_structured_result(self):
        self.database_mocks["list_tasks"].return_value = [
            {
                "id": 4,
                "title": "Draft report",
                "completed": 0,
                "priority": "high",
                "due_date": None,
            },
        ]

        async with Client(FastMCPTransport(mcp=server.mcp)) as client:
            result = await client.call_tool_mcp(
                "list_tasks",
                {"pending_only": True},
            )

        self.assertFalse(result.isError)
        self.assertEqual(
            result.structuredContent,
            {
                "result": [
                    {
                        "id": 4,
                        "title": "Draft report",
                        "completed": False,
                        "priority": "high",
                        "due_date": None,
                    },
                ],
            },
        )
        self.database_mocks["list_tasks"].assert_called_once_with(
            user_sub=LOCAL_USER_ONE_SUB,
            pending_only=True,
        )
        self.fetch_weather.assert_not_awaited()
        self.get_hourly_forecast.assert_not_awaited()

    async def test_missing_required_argument_is_mcp_validation_error(self):
        async with Client(FastMCPTransport(mcp=server.mcp)) as client:
            result = await client.call_tool_mcp("get_weather", {})

        self.assertTrue(result.isError)
        self.fetch_weather.assert_not_awaited()

    async def test_database_exception_is_reported_as_tool_error(self):
        self.database_mocks["list_tasks"].side_effect = RuntimeError(
            "database unavailable"
        )

        async with Client(FastMCPTransport(mcp=server.mcp)) as client:
            raw_result = await client.call_tool_mcp("list_tasks", {})
            with self.assertRaises(ToolError):
                await client.call_tool("list_tasks", {})

        self.assertTrue(raw_result.isError)
        self.database_mocks["list_tasks"].assert_has_calls(
            [
                call(user_sub=LOCAL_USER_ONE_SUB, pending_only=True),
                call(user_sub=LOCAL_USER_ONE_SUB, pending_only=True),
            ]
        )

    async def test_local_users_only_receive_their_own_tasks(self):
        tasks_by_user = {
            LOCAL_USER_ONE_SUB: [{
                "id": 101,
                "title": "User one task",
                "completed": 0,
                "priority": "medium",
                "due_date": None,
            }],
            LOCAL_USER_TWO_SUB: [{
                "id": 202,
                "title": "User two task",
                "completed": 0,
                "priority": "medium",
                "due_date": None,
            }],
        }

        def list_tasks_for_user(*, user_sub, pending_only):
            self.assertTrue(pending_only)
            return tasks_by_user[user_sub]

        self.database_mocks["list_tasks"].side_effect = list_tasks_for_user
        results = {}

        for user_sub in (LOCAL_USER_ONE_SUB, LOCAL_USER_TWO_SUB):
            self.get_access_token.return_value = make_test_access_token(user_sub)
            async with Client(FastMCPTransport(mcp=server.mcp)) as client:
                results[user_sub] = await client.call_tool_mcp(
                    "list_tasks",
                    {"pending_only": True},
                )

        self.assertEqual(
            [task["id"] for task in results[LOCAL_USER_ONE_SUB].structuredContent["result"]],
            [101],
        )
        self.assertEqual(
            [task["id"] for task in results[LOCAL_USER_TWO_SUB].structuredContent["result"]],
            [202],
        )
        self.database_mocks["list_tasks"].assert_has_calls(
            [
                call(user_sub=LOCAL_USER_ONE_SUB, pending_only=True),
                call(user_sub=LOCAL_USER_TWO_SUB, pending_only=True),
            ]
        )

    async def test_application_failure_is_not_an_mcp_tool_error(self):
        async with Client(FastMCPTransport(mcp=server.mcp)) as client:
            result = await client.call_tool_mcp(
                "complete_task",
                {"task_id": 0},
            )

        self.assertFalse(result.isError)
        self.assertEqual(
            result.structuredContent,
            {
                "success": False,
                "error": "Task ID must be positive.",
            },
        )
        self.database_mocks["complete_task"].assert_not_called()


if __name__ == "__main__":
    unittest.main()