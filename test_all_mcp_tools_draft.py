import asyncio
import os
import logging
from typing import Dict, Any
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import MCP tools handling
try:
    from app.crew_pipeline.mcp_tools import get_mcp_tools, MCPToolWrapper
except ImportError:
    # Adjust path if running directly from root
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from app.crew_pipeline.mcp_tools import get_mcp_tools, MCPToolWrapper

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://travliaq-mcp-production.up.railway.app/sse")

async def test_tool(tool_name: str, tool_func: Any, args: Dict[str, Any]):
    logger.info(f"Testing {tool_name} with args: {args}")
    try:
        # The tool is an instance of MCPToolWrapper (BaseTool)
        # We can call it directly or via _run/_async_run
        if hasattr(tool_func, '_async_run'):
            result = await tool_func._async_run(**args)
        else:
            result = tool_func._run(**args)
            
        logger.info(f"✅ {tool_name} SUCCESS")
        # logger.info(f"Output: {str(result)[:200]}...") # Truncate output
        return True
    except Exception as e:
        logger.error(f"❌ {tool_name} FAILED: {e}")
        return False

async def main():
    logger.info(f"Connecting to MCP Server: {MCP_SERVER_URL}")
    
    # 1. Fetch all tools
    try:
        tools_list, resources_list = await asyncio.to_thread(lambda: asyncio.run(get_mcp_tools_async_wrapper())) 
        # Wait, get_mcp_tools is synchronous but calls async code internally with asyncio.run
        # But we are already in an async loop. 
        # Let's look at mcp_tools.py implementation again.
        pass
    except Exception as e:
        logger.error(f"Failed to fetch tools: {e}")
        return

    # Actually, get_mcp_tools in mcp_tools.py uses asyncio.run() internally.
    # Calling it from here (inside async def main) might cause "asyncio.run() cannot be called from a running event loop".
    # We should probably import the internal async function or run it in a thread.
    # Let's check mcp_tools.py content first.

if __name__ == "__main__":
    # We'll implement the logic after checking mcp_tools.py
    pass
