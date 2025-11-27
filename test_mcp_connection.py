"""Test script to diagnose MCP server connectivity."""
import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_mcp_connection():
    """Test MCP server connection using the same method as the pipeline."""
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError as e:
        print(f"[ERROR] MCP library not installed: {e}")
        return

    server_url = "https://travliaq-mcp-production.up.railway.app/sse"
    # server_url = "http://127.0.0.1:8001/sse"
    
    print(f"[*] Testing connection to: {server_url}")
    print(f"[*] Using SSE client to connect...")
    
    try:
        async with asyncio.timeout(10):
            async with sse_client(server_url) as (read, write):
                print("[OK] SSE connection established")
                async with ClientSession(read, write) as session:
                    print("[*] Initializing session...")
                    await session.initialize()
                    print("[OK] Session initialized")
                    
                    print("[*] Listing available tools...")
                    tools_list = await session.list_tools()
                    print(f"[OK] Found {len(tools_list.tools)} tools:")
                    for tool in tools_list.tools:
                        print(f"  - {tool.name}: {tool.description}")
    
    except asyncio.TimeoutError:
        print("[ERROR] Connection timeout after 10 seconds")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp_connection())
