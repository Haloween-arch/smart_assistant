import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

# Preload FastMCP's dependency classes so dynamic server imports share identity.
import fastmcp.dependencies
from fastmcp.server.auth import AccessToken


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_USER_ONE_SUB = "dev_mock_user_1"
LOCAL_USER_TWO_SUB = "dev_mock_user_2"
LOCAL_USER_ONE_TOKEN = "test-only-user-one-token-0123456789abcdef"
LOCAL_USER_TWO_TOKEN = "test-only-user-two-token-0123456789abcdef"

TEST_AUTH_ENV = {
    "AUTH_MODE": "local",
    "DEV_MOCK_USER_ONE_TOKEN": LOCAL_USER_ONE_TOKEN,
    "DEV_MOCK_USER_TWO_TOKEN": LOCAL_USER_TWO_TOKEN,
}


def load_test_server(module_name: str):
    project_root_text = str(PROJECT_ROOT)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)

    server_path = PROJECT_ROOT / "server.py"
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load server module from {server_path}")

    server = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = server

    database_stub = ModuleType("database")
    for function_name in (
        "create_task",
        "list_tasks",
        "complete_task",
        "create_calendar_event",
        "list_upcoming_events",
    ):
        setattr(database_stub, function_name, Mock(name=f"database.{function_name}"))

    previous_database = sys.modules.get("database")
    sys.modules["database"] = database_stub
    try:
        with patch.dict(os.environ, TEST_AUTH_ENV, clear=False):
            spec.loader.exec_module(server)
    finally:
        if previous_database is None:
            del sys.modules["database"]
        else:
            sys.modules["database"] = previous_database

    return server


def make_test_access_token(user_sub: str) -> AccessToken:
    return AccessToken(
        token="in-process-test-token",
        client_id="in-process-test-client",
        scopes=[],
        claims={"sub": user_sub},
    )
