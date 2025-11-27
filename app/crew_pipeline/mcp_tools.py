import asyncio
import logging
from typing import Any, List, Dict, Type, Optional

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, create_model

# Try importing mcp, handle if not installed (though we added it to requirements)
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
except ImportError:
    ClientSession = None
    sse_client = None

logger = logging.getLogger(__name__)

class MCPToolWrapper(BaseTool):
    """
    A generic wrapper for MCP tools to be used in CrewAI.
    """
    server_url: str = Field(..., description="URL of the MCP server")
    tool_name: str = Field(..., description="Name of the tool on the MCP server")
    
    def _run(self, **kwargs: Any) -> Any:
        return asyncio.run(self._async_run(**kwargs))

    async def _async_run(self, **kwargs: Any) -> Any:
        if not sse_client:
            return "MCP library not installed."
            
        try:
            async with sse_client(self.server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(self.tool_name, arguments=kwargs)
                    
                    # Format the result
                    output = []
                    if result.content:
                        for item in result.content:
                            if hasattr(item, "text"):
                                output.append(item.text)
                            else:
                                output.append(str(item))
                    return "\n".join(output)
        except Exception as e:
            logger.error(f"Error calling MCP tool {self.tool_name}: {e}")
            return f"Error executing tool: {str(e)}"

def _create_pydantic_model_from_schema(name: str, schema: Dict[str, Any]) -> Type[BaseModel]:
    """
    Creates a Pydantic model from a JSON schema for tool arguments.
    """
    fields = {}
    if "properties" in schema:
        for field_name, field_info in schema["properties"].items():
            # Basic type mapping
            field_type = Any
            if field_info.get("type") == "string":
                field_type = str
            elif field_info.get("type") == "integer":
                field_type = int
            elif field_info.get("type") == "number":
                field_type = float
            elif field_info.get("type") == "boolean":
                field_type = bool
            elif field_info.get("type") == "array":
                field_type = List[Any]
            
            description = field_info.get("description", "")
            is_required = field_name in schema.get("required", [])
            
            if is_required:
                fields[field_name] = (field_type, Field(..., description=description))
            else:
                fields[field_name] = (Optional[field_type], Field(None, description=description))
    
    return create_model(f"{name}Args", **fields)

def get_mcp_tools(server_url: str) -> List[BaseTool]:
    """
    Connects to the MCP server, lists available tools, and returns them as CrewAI tools.
    """
    if not sse_client:
        logger.error("MCP library not installed. Cannot fetch tools.")
        return []

    async def _fetch_tools():
        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

    try:
        logger.info(f"Fetching MCP tools from {server_url}...")
        tools_list = asyncio.run(_fetch_tools())
        
        crew_tools = []
        for tool in tools_list.tools:
            logger.info(f"Found MCP tool: {tool.name}")
            
            # Create dynamic args schema
            args_schema = _create_pydantic_model_from_schema(tool.name, tool.inputSchema)
            
            # Create a subclass of MCPToolWrapper with specific name and description
            # This is necessary because CrewAI/LangChain often look at class attributes
            tool_class = type(
                f"MCP_{tool.name}",
                (MCPToolWrapper,),
                {
                    "name": tool.name,
                    "description": tool.description or f"Tool {tool.name} from MCP",
                    "args_schema": args_schema,
                    "server_url": server_url,
                    "tool_name": tool.name
                }
            )
            
            # Instantiate the tool
            # We pass server_url and tool_name again to be safe, though class attrs handle it
            instance = tool_class(server_url=server_url, tool_name=tool.name)
            crew_tools.append(instance)
            
        return crew_tools

    except Exception as e:
        logger.error(f"Failed to fetch tools from MCP server: {e}")
        return []
