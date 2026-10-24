"""Real MCP stdio client/server exchange without starting an authorized Windows command."""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

def extract_result(result):
    if result.structuredContent is not None:
        data = result.structuredContent
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(result.content[0].text)

def test_real_stdio_mcp_handshake():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "termylo.server"],
            cwd=str(Path(__file__).resolve().parents[1]), env=dict(os.environ)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"termylo_status", "execute_powershell", "powershell_result", "cancel_powershell", "open_visible_session", "visible_session_status", "execute_visible_powershell", "close_visible_session"} <= names
                status = extract_result(await session.call_tool("termylo_status"))
                assert status["online"] is True
                assert "visible_session" in status
                bad = extract_result(await session.call_tool("execute_powershell", {"command": "", "timeout_seconds": 10}))
                assert bad["status"] == "rejected"
                unknown = extract_result(await session.call_tool("powershell_result", {"job_id": "not-a-real-id"}))
                assert unknown["status"] == "not_found"
                denied = extract_result(await session.call_tool("execute_visible_powershell", {"session_id": "not-approved", "command": "Get-Date"}))
                assert denied["status"] == "unavailable"
    asyncio.run(run())
