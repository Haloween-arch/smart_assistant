# Smart Daily Assistant

A local-first MCP server for daily planning. It exposes task and calendar tools, weather lookups, task prioritization, and combined daily summaries through FastMCP over Streamable HTTP.

## Features

- Create, list, and complete tasks with priority and due dates.
- Create and list calendar events with timezone-aware timestamps.
- Fetch current weather and hourly forecasts through Open-Meteo.
- Produce daily briefings and deterministic task/weather recommendations.
- Scope task and calendar records by the authenticated user's `sub` value.
- Run locally with two separate bearer-token identities, without Google or Microsoft sign-in.

## Requirements

- Python 3.12 (the project has been used with Python 3.12.6).
- Windows PowerShell instructions below; equivalent virtual-environment commands work on macOS and Linux.

## Local Setup

Create and activate a virtual environment, then install the project dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a local environment file from the template:

```powershell
Copy-Item .env.example .env
```

Generate two different random bearer tokens locally. Run this command twice and use one output for each user:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set `DEV_MOCK_USER_ONE_TOKEN` and `DEV_MOCK_USER_TWO_TOKEN` in `.env` to the two generated values. Each must be at least 32 characters and the values must differ. Keep `.env` private; it is excluded by `.gitignore`.

The default `AUTH_MODE=local` verifies the bearer tokens and maps them server-side to `dev_mock_user_1` and `dev_mock_user_2`. The caller cannot choose or override the resulting user identity. All tool calls using one token access that user's task and calendar rows.

Start the server from the project directory with the virtual environment active:

```powershell
python server.py
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. The server binds to loopback by default.

## VS Code MCP Client

The workspace configuration in `.vscode/mcp.json` defines two server entries that use the same local endpoint but prompt for different bearer tokens. When VS Code prompts, enter the same values configured in `.env` for user one and user two. Use the corresponding server entry to act as that identity. Do not put the token values directly into `mcp.json` or source control.

## Authentication Modes

`AUTH_MODE=local` (default) uses FastMCP's static token verifier for local development. This is a development convenience, not production authentication: anyone who obtains a token can act as its associated user. Keep the service on loopback and rotate tokens if they are exposed.

`AUTH_MODE=oauth` enables the configured Google OAuth provider. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `MCP_BASE_URL` in the server environment. The Google callback defaults to `/auth/callback`; register the matching callback URI with Google Cloud. The current VS Code config is for local bearer-token mode and must be configured for OAuth before using this mode.

## Data Model and Isolation

Tasks and calendar events carry a `user_sub` owner. Database operations filter listings and updates using that owner, and MCP tools obtain the identity through FastMCP's verified token claim dependency rather than a user-supplied argument. Daily briefing, prioritization, and recommendations reuse those scoped database operations.

The current SQLite migration adds `user_sub` to older databases as a nullable column but does not assign existing rows to an owner. Those legacy rows will not appear in user-scoped queries until they are explicitly reviewed and assigned. Back up `assistant.db` before any manual data migration.

Local mock mode has exactly two configured identities. It does not provide account creation, password login, account recovery, or team membership. It is not a substitute for a production identity provider.

## MCP Tools

- `add_task`, `list_tasks`, `complete_task`
- `add_calendar_event`, `get_upcoming_events`
- `get_weather`
- `prioritize_tasks`
- `get_daily_briefing`
- `get_daily_recommendations`

Task and calendar tools are owner-scoped. Weather is requested for the city supplied to the tool and is not stored as a personal task or event.

## Tests

Run the standard-library unit suite from the project root:

```powershell
python -m unittest discover -s tests -v
```

Tests stub the database when loading `server.py`, mock weather services, and use FastMCP's in-process client for MCP protocol coverage. The user-isolation integration test verifies that two token subjects query separate task sets. The current suite does not replace dedicated database migration tests against temporary SQLite databases.

## Extending for Collaboration

For real multi-user or team collaboration:

1. Replace local static tokens with a production identity provider or a trusted identity broker.
2. Resolve a stable internal principal from validated issuer and subject claims. Google and Microsoft subjects should not be assumed interchangeable; link provider identities to an internal user account explicitly.
3. Add organizations, memberships, roles, and resource ownership/ACLs if users need to share selected tasks or events. Keep private-by-default behavior and authorize every read, update, and delete in the database layer.
4. Add migrations that assign or quarantine legacy ownerless rows; never assign them automatically to whichever user logs in first.
5. Add database and MCP integration tests for cross-user reads, updates, event access, shared-resource permissions, token expiry, and invalid identities.

## Project Layout

```text
server.py                  FastMCP tools, auth mode, and HTTP startup
database.py                SQLite schema, migrations, and owner-scoped queries
services/weather.py        Current weather and hourly forecast client
tests/                     Unit and in-process MCP integration tests
.vscode/mcp.json           Local VS Code MCP entries for both dev users
.env.example               Environment variable template; contains no secrets
```

[![M8ven Score](https://m8ven.ai/badge/mcp/haloween-arch-smart-assistant-7dxeh9?v=41175ea22cc324417ebcbe27b6cf6cb1)](https://m8ven.ai/mcp/haloween-arch-smart-assistant-7dxeh9?s=readme)
