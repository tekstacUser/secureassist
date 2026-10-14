"""MCP client used by the SecureAssist backend (PREDEFINED).

This is a genuine Model Context Protocol client built on the official SDK
(`mcp` package, same pinned version as the server). For every call it:

  1. checks the tool name against the local ALLOWLIST (rejected before any
     network traffic if not approved),
  2. validates the arguments,
  3. opens an MCP session over Streamable HTTP and runs `initialize`,
  4. discovers tools with `tools/list` and confirms the server offers the tool,
  5. invokes it with `tools/call`, within a timeout.

Command-line verification (from the VM with a port-forward, or inside the
backend Pod with `kubectl exec`):

    python mcp_client.py list
    python mcp_client.py call search_support_faq '{"query": "reset password"}'
    python mcp_client.py call get_service_status '{"service": "vpn"}'
"""

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://secureassist-mcp:8093/mcp")
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "10"))

APPROVED_SERVICES = {"email", "vpn", "sso", "wifi", "printing", "helpdesk-portal"}


def _validate_faq_args(args: dict) -> dict:
    query = args.get("query")
    if set(args) != {"query"} or not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise MCPError("mcp_invalid_arguments", "search_support_faq needs {'query': 1-200 chars}")
    return {"query": query.strip()}


def _validate_status_args(args: dict) -> dict:
    service = args.get("service")
    if set(args) != {"service"} or not isinstance(service, str):
        raise MCPError("mcp_invalid_arguments", "get_service_status needs {'service': <name>}")
    service = service.strip().lower()
    if service not in APPROVED_SERVICES:
        raise MCPError("mcp_invalid_arguments", f"service must be one of {sorted(APPROVED_SERVICES)}")
    return {"service": service}


# The ONLY tools the backend may call, each with its argument validator.
ALLOWED_TOOLS = {
    "search_support_faq": _validate_faq_args,
    "get_service_status": _validate_status_args,
}


class MCPError(Exception):
    """Raised for any MCP failure. `category` is safe to log and show."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _unwrap(exc: BaseException) -> BaseException:
    """The SDK uses task groups, so real errors can be wrapped in ExceptionGroups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def _with_session(work):
    async with httpx.AsyncClient(timeout=MCP_TIMEOUT) as http_client:
        async with streamable_http_client(MCP_SERVER_URL, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await work(session)


def _run(work):
    try:
        return asyncio.run(asyncio.wait_for(_with_session(work), timeout=MCP_TIMEOUT + 2))
    except MCPError:
        raise
    except BaseException as exc:  # noqa: BLE001 - classify every failure clearly
        exc = _unwrap(exc)
        if isinstance(exc, MCPError):
            raise exc from None
        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
            raise MCPError("mcp_timeout", f"MCP server did not answer within {MCP_TIMEOUT:.0f}s") from None
        if isinstance(exc, httpx.ConnectError):
            raise MCPError("mcp_unreachable", f"MCP server unreachable at {MCP_SERVER_URL}") from None
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise MCPError("mcp_protocol_error", f"MCP error: {type(exc).__name__}: {exc}") from None


def list_tools() -> list[dict]:
    """Discover tools on the server (MCP tools/list)."""

    async def work(session):
        result = await session.list_tools()
        return [{"name": t.name, "description": (t.description or "").strip(),
                 "approved": t.name in ALLOWED_TOOLS} for t in result.tools]

    return _run(work)


def call_tool(name: str, arguments: dict) -> dict:
    """Validate and invoke one approved tool. Returns the tool's JSON result."""
    if name not in ALLOWED_TOOLS:
        raise MCPError("mcp_tool_not_allowed", f"Tool '{name}' is not on the approved allowlist")
    if not isinstance(arguments, dict):
        raise MCPError("mcp_invalid_arguments", "arguments must be a JSON object")
    clean_args = ALLOWED_TOOLS[name](arguments)

    async def work(session):
        offered = {t.name for t in (await session.list_tools()).tools}
        if name not in offered:
            raise MCPError("mcp_tool_not_offered", f"Server does not offer tool '{name}'")
        result = await session.call_tool(name, clean_args)
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.isError:
            raise MCPError("mcp_tool_error", text[:300] or "tool returned an error")
        if isinstance(result.structuredContent, dict) and "result" not in result.structuredContent:
            return result.structuredContent
        try:
            data = json.loads(text)
        except ValueError:
            raise MCPError("mcp_invalid_result", "tool result was not valid JSON") from None
        if not isinstance(data, dict):
            raise MCPError("mcp_invalid_result", "tool result was not a JSON object")
        return data

    return _run(work)


def check_server() -> dict:
    """Used by /ready?deep=true. Never raises."""
    try:
        tools = list_tools()
        return {"ok": True, "url": MCP_SERVER_URL, "tools": [t["name"] for t in tools]}
    except MCPError as exc:
        return {"ok": False, "url": MCP_SERVER_URL, "detail": exc.category}


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 2 and sys.argv[1] == "list":
            print(json.dumps({"server": MCP_SERVER_URL, "tools": list_tools()}, indent=2))
        elif len(sys.argv) >= 3 and sys.argv[1] == "call":
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            print(json.dumps({"tool": sys.argv[2], "result": call_tool(sys.argv[2], args)}, indent=2))
        else:
            print(__doc__)
            sys.exit(2)
    except MCPError as err:
        print(json.dumps({"error": err.category, "detail": str(err)}, indent=2))
        sys.exit(1)
