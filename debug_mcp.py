"""
Script de diagnostic MCP pour identifier le problème exact.
"""
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    url = 'https://travliaq-mcp-production.up.railway.app/mcp'

    print(f"[1] Connecting to {url}...")

    try:
        async with streamablehttp_client(url) as (read, write, get_session_id):
            print(f"[2] Connected! Session ID: {get_session_id()}")

            async with ClientSession(read, write) as session:
                print("[3] Initializing session...")
                result = await session.initialize()
                print(f"[4] Initialized! Protocol: {result.protocolVersion}")
                print(f"    Server: {result.serverInfo.name} v{result.serverInfo.version}")

                print("[5] Listing tools...")
                tools = await session.list_tools()
                print(f"[6] SUCCESS! Found {len(tools.tools)} tools:")
                for tool in tools.tools[:5]:
                    print(f"    - {tool.name}")
                if len(tools.tools) > 5:
                    print(f"    ... and {len(tools.tools) - 5} more")

                print("[7] Listing resources...")
                try:
                    resources = await session.list_resources()
                    print(f"[8] SUCCESS! Found {len(resources.resources)} resources")
                except Exception as e:
                    print(f"[8] FAILED to list resources: {type(e).__name__}: {e}")

                return len(tools.tools)
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 0

if __name__ == "__main__":
    result = asyncio.run(main())
    print(f"\nResult: {result} tools loaded")
