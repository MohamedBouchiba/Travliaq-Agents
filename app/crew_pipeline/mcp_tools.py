import asyncio
import logging
from typing import Any, List, Dict, Type, Optional
import time

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, create_model

# Try importing mcp, handle if not installed (though we added it to requirements)
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
except ImportError:
    ClientSession = None
    sse_client = None

import httpx

logger = logging.getLogger(__name__)

# Configuration pour les retries et timeouts
MCP_TIMEOUT_SECONDS = 30
MCP_MAX_RETRIES = 3
MCP_RETRY_DELAY_SECONDS = 1

# Cache pour les headers de session (pour éviter de refaire le probe à chaque appel)
_session_headers_cache: Dict[str, Dict[str, str]] = {}

async def _get_session_headers(server_url: str) -> Dict[str, str]:
    """
    Récupère les headers de session nécessaires pour le serveur MCP.
    Gère le cas où le serveur nécessite un Mcp-Session-Id spécifique.
    """
    if server_url in _session_headers_cache:
        return _session_headers_cache[server_url]
    
    headers = {}
    try:
        # Probe initial pour voir si on a besoin d'un session ID
        # On ignore les erreurs de certificat pour simplifier en dev/test
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.get(server_url, headers={"Accept": "text/event-stream"})
            
            # Si le serveur renvoie 400 avec un session ID, c'est qu'il faut l'utiliser
            if resp.status_code == 400 and "Mcp-Session-Id" in resp.headers:
                session_id = resp.headers["Mcp-Session-Id"]
                logger.info(f"🔄 Session MCP récupérée: {session_id}")
                headers["Mcp-Session-Id"] = session_id
                _session_headers_cache[server_url] = headers
            elif resp.status_code == 200:
                # Connexion directe OK
                _session_headers_cache[server_url] = {}
                
    except Exception as e:
        logger.warning(f"⚠️ Échec du probe de session MCP: {e}")
    
    return headers

class MCPToolWrapper(BaseTool):
    """
    A generic wrapper for MCP tools to be used in CrewAI.
    
    Inclut retry logic, timeout et gestion d'erreurs robuste.
    """
    server_url: str = Field(..., description="URL of the MCP server")
    tool_name: str = Field(..., description="Name of the tool on the MCP server")
    timeout: int = Field(default=MCP_TIMEOUT_SECONDS, description="Timeout en secondes")
    max_retries: int = Field(default=MCP_MAX_RETRIES, description="Nombre maximum de tentatives")
    
    def _run(self, **kwargs: Any) -> Any:
        return asyncio.run(self._async_run(**kwargs))

    async def _async_run(self, **kwargs: Any) -> Any:
        if not sse_client:
            logger.error("MCP library not installed")
            return "MCP library not installed."
        
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    f"Tentative {attempt}/{self.max_retries} pour {self.tool_name}",
                    extra={"tool": self.tool_name, "attempt": attempt}
                )
                
                # Timeout pour la connexion et l'exécution
                async with asyncio.timeout(self.timeout):
                    # Récupération des headers de session
                    headers = await _get_session_headers(self.server_url)
                    
                    async with sse_client(self.server_url, headers=headers) as (read, write):
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
                            
                            success_output = "\n".join(output)
                            logger.info(
                                f"✅ MCP tool {self.tool_name} exécuté avec succès",
                                extra={"tool": self.tool_name, "output_size": len(success_output)}
                            )
                            return success_output
                            
            except asyncio.TimeoutError as e:
                last_error = f"Timeout après {self.timeout}s"
                logger.warning(
                    f"⏱️ Timeout pour {self.tool_name} (tentative {attempt}/{self.max_retries})",
                    extra={"tool": self.tool_name, "timeout": self.timeout}
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"⚠️ Erreur pour {self.tool_name} (tentative {attempt}/{self.max_retries}): {e}",
                    extra={"tool": self.tool_name, "error": str(e)}
                )
            
            # Attendre avant de réessayer (sauf pour la dernière tentative)
            if attempt < self.max_retries:
                await asyncio.sleep(MCP_RETRY_DELAY_SECONDS * attempt)
        
        # Toutes les tentatives ont échoué
        error_msg = f"Échec après {self.max_retries} tentatives: {last_error}"
        logger.error(
            f"❌ MCP tool {self.tool_name} a échoué définitivement",
            extra={"tool": self.tool_name, "error": last_error}
        )
        return f"Error executing tool {self.tool_name}: {error_msg}"

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
        # Récupération des headers de session
        headers = await _get_session_headers(server_url)
        logger.info(f"Connecting to SSE with headers: {headers}")
        
        async with sse_client(server_url, headers=headers) as (read, write):
            logger.info("SSE connection established")
            async with ClientSession(read, write) as session:
                logger.info("Initializing session...")
                await session.initialize()
                logger.info("Session initialized. Listing tools...")
                tools = await session.list_tools()
                logger.info(f"Tools listed: {len(tools.tools)} found")
                return tools

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
