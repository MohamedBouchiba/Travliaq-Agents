import asyncio
import logging
from typing import Any, List, Dict, Type, Optional
import time
import re

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, create_model

# Try importing mcp, handle if not installed (though we added it to requirements)
try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client, aconnect_sse, remove_request_params, create_mcp_http_client, SSEError
    from mcp.client.session import SessionMessage
    import mcp.types as types
except ImportError:
    ClientSession = None
    sse_client = None
    aconnect_sse = None
    remove_request_params = None
    create_mcp_http_client = None
    SessionMessage = None
    SSEError = None
    types = None

import httpx
import anyio
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse

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
                    
                    # Force Accept header for both SSE and POST
                    headers["Accept"] = "application/json, text/event-stream"
                    
                    # Construct POST endpoint URL (same as server URL but with session ID)
                    post_url = self.server_url
                    if "Mcp-Session-Id" in headers:
                        if "?" in post_url:
                            post_url += f"&sessionId={headers['Mcp-Session-Id']}"
                        else:
                            post_url += f"?sessionId={headers['Mcp-Session-Id']}"
                    
                    async with custom_sse_client(self.server_url, headers=headers, override_endpoint_url=post_url) as (read, write):
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

class MCPResourceWrapper(BaseTool):
    """
    A wrapper for MCP resources (knowledge base) to be used in CrewAI.
    Exposes resources as callable tools that return the resource content.
    """
    server_url: str = Field(..., description="URL of the MCP server")
    resource_uri: str = Field(..., description="URI of the resource")
    timeout: int = Field(default=MCP_TIMEOUT_SECONDS, description="Timeout en secondes")
    
    def _run(self, **kwargs: Any) -> Any:
        return asyncio.run(self._async_run(**kwargs))
    
    async def _async_run(self, **kwargs: Any) -> Any:
        if not sse_client:
            logger.error("MCP library not installed")
            return "MCP library not installed."
        
        try:
            async with asyncio.timeout(self.timeout):
                # Récupération des headers de session
                headers = await _get_session_headers(self.server_url)
                headers["Accept"] = "application/json, text/event-stream"
                headers["Content-Type"] = "application/json"
                
                # Construct POST endpoint URL
                post_url = self.server_url
                if "Mcp-Session-Id" in headers:
                    if "?" in post_url:
                        post_url += f"&sessionId={headers['Mcp-Session-Id']}"
                    else:
                        post_url += f"?sessionId={headers['Mcp-Session-Id']}"
                
                async with custom_sse_client(self.server_url, headers=headers, override_endpoint_url=post_url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        
                        # Read the resource
                        logger.info(f"📖 Reading MCP resource: {self.resource_uri}")
                        result = await session.read_resource(self.resource_uri)
                        
                        # Extract content from the resource
                        output = []
                        if result.contents:
                            for item in result.contents:
                                if hasattr(item, "text"):
                                    output.append(item.text)
                                else:
                                    output.append(str(item))
                        
                        success_output = "\n".join(output)
                        logger.info(f"✅ MCP resource {self.resource_uri} read successfully")
                        return success_output
                        
        except asyncio.TimeoutError:
            error_msg = f"Timeout après {self.timeout}s"
            logger.error(f"❌ Timeout reading resource {self.resource_uri}")
            return f"Error reading resource {self.resource_uri}: {error_msg}"
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Error reading resource {self.resource_uri}: {e}")
            return f"Error reading resource {self.resource_uri}: {error_msg}"

@asynccontextmanager
async def custom_sse_client(
    url: str,
    headers: Dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    httpx_client_factory: Any = create_mcp_http_client,
    auth: Any | None = None,
    override_endpoint_url: str | None = None,
):
    """
    Custom Client transport for SSE that supports manual endpoint URL override.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as tg:
        try:
            # Ensure headers include Content-Type and Accept for POST requests
            if headers is None:
                headers = {}
            # Add required headers for both SSE (GET) and POST requests
            headers.setdefault("Accept", "application/json, text/event-stream")
            headers.setdefault("Content-Type", "application/json")
            
            logger.debug(f"Connecting to SSE endpoint: {remove_request_params(url)}")
            async with httpx_client_factory(
                headers=headers, auth=auth, timeout=httpx.Timeout(timeout, read=sse_read_timeout)
            ) as client:
                async with aconnect_sse(
                    client,
                    "GET",
                    url,
                ) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("SSE connection established")

                    async def sse_reader(
                        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
                    ):
                        try:
                            # If override provided, start immediately
                            if override_endpoint_url:
                                logger.info(f"🔧 Using override endpoint URL: {override_endpoint_url}")
                                task_status.started(override_endpoint_url)
                            
                            logger.info("📡 Starting SSE event loop...")
                            async for sse in event_source.aiter_sse():
                                logger.info(f"📨 Received SSE event: {sse.event}, data length: {len(sse.data) if sse.data else 0}")
                                match sse.event:
                                    case "endpoint":
                                        endpoint_url = urljoin(url, sse.data)
                                        logger.info(f"🔗 Received endpoint URL: {endpoint_url}")
                                        
                                        if not override_endpoint_url:
                                            logger.info(f"✅ Starting with endpoint: {endpoint_url}")
                                            task_status.started(endpoint_url)
                                        else:
                                            logger.info(f"⚠️ Ignoring endpoint event (using override)")

                                    case "message":
                                        logger.info(f"💬 Processing message event...")
                                        try:
                                            message = types.JSONRPCMessage.model_validate_json(
                                                sse.data
                                            )
                                            logger.info(f"✅ Parsed server message: method={getattr(message, 'method', None)}, id={getattr(message, 'id', None)}")
                                        except Exception as exc:
                                            logger.exception("❌ Error parsing server message")
                                            await read_stream_writer.send(exc)
                                            continue

                                        session_message = SessionMessage(message)
                                        logger.info(f"📬 Sending message to session: {session_message}")
                                        await read_stream_writer.send(session_message)
                                    case _:
                                        logger.warning(f"⚠️ Unknown SSE event: {sse.event}, data: {sse.data[:100] if sse.data else 'None'}")
                        except SSEError as sse_exc:
                            logger.exception("Encountered SSE exception")
                            raise sse_exc
                        except Exception as exc:
                            logger.exception("Error in sse_reader")
                            await read_stream_writer.send(exc)
                        finally:
                            await read_stream_writer.aclose()

                    async def post_writer(endpoint_url: str):
                        logger.info(f"📤 Starting post_writer with endpoint: {endpoint_url}")
                        try:
                            async with write_stream_reader:
                                logger.info("📝 Waiting for messages to send...")
                                async for session_message in write_stream_reader:
                                    logger.info(f"📮 Sending client message: method={getattr(session_message.message, 'method', None)}, id={getattr(session_message.message, 'id', None)}")
                                    
                                    # The httpx client already has all necessary headers
                                    # (Content-Type, Accept, Mcp-Session-Id) set during client creation
                                    # No need to override them here
                                    
                                    response = await client.post(
                                        endpoint_url,
                                        json=session_message.message.model_dump(
                                            by_alias=True,
                                            mode="json",
                                            exclude_none=True,
                                        )
                                    )
                                    response.raise_for_status()
                                    logger.info(f"✅ Client message sent successfully: {response.status_code}, response length: {len(response.text) if response.text else 0}")
                                    
                                    # CRITICAL FIX: This MCP server responds directly in POST body
                                    # instead of via SSE events. Parse and forward to read stream.
                                    if response.text:
                                        try:
                                            logger.info(f"📦 Parsing POST response as JSON-RPC message...")
                                            
                                            # The response might be SSE-formatted (event: message\ndata: {...})
                                            response_text = response.text.strip()
                                            json_text = response_text
                                            
                                            # Check if it's SSE format
                                            if response_text.startswith("event:"):
                                                logger.info("🔍 Detected SSE format in POST response, extracting data...")
                                                # Extract the JSON from the 'data:' line
                                                for line in response_text.split('\n'):
                                                    if line.startswith('data:'):
                                                        json_text = line[5:].strip()  # Remove 'data:' prefix
                                                        logger.info(f"✂️ Extracted JSON from SSE data line")
                                                        break
                                            
                                            response_message = types.JSONRPCMessage.model_validate_json(json_text)
                                            logger.info(f"✅ Parsed response: method={getattr(response_message, 'method', None)}, id={getattr(response_message, 'id', None)}")
                                            response_session_message = SessionMessage(response_message)
                                            await read_stream_writer.send(response_session_message)
                                            logger.info(f"📬 Response forwarded to session read stream")
                                        except Exception as exc:
                                            logger.error(f"❌ Failed to parse POST response: {exc}")
                                            logger.error(f"Response text: {response.text[:500]}")
                        except Exception:
                            logger.exception("Error in post_writer")
                        finally:
                            await write_stream.aclose()

                    endpoint_url = await tg.start(sse_reader)
                    logger.debug(f"Starting post writer with endpoint URL: {endpoint_url}")
                    tg.start_soon(post_writer, endpoint_url)

                    try:
                        yield read_stream, write_stream
                    finally:
                        tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()

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
        
        # Force Accept header for both SSE and POST
        headers["Accept"] = "application/json, text/event-stream"
        
        # Construct POST endpoint URL (same as server URL but with session ID)
        post_url = server_url
        if "Mcp-Session-Id" in headers:
            if "?" in post_url:
                post_url += f"&sessionId={headers['Mcp-Session-Id']}"
            else:
                post_url += f"?sessionId={headers['Mcp-Session-Id']}"
        
        async with custom_sse_client(server_url, headers=headers, override_endpoint_url=post_url) as (read, write):
            logger.info("SSE connection established")
            async with ClientSession(read, write) as session:
                logger.info("Initializing session...")
                await session.initialize()
                
                # Fetch tools
                logger.info("Session initialized. Listing tools...")
                tools = await session.list_tools()
                logger.info(f"Tools listed: {len(tools.tools)} found")
                
                # Fetch resources (knowledge base)
                logger.info("Listing resources (knowledge base)...")
                try:
                    resources = await session.list_resources()
                    logger.info(f"Resources listed: {len(resources.resources)} found")
                except Exception as e:
                    logger.warning(f"Failed to list resources: {e}")
                    resources = None
                
                return tools, resources

    try:
        logger.info(f"Fetching MCP tools from {server_url}...")
        tools_list, resources_list = asyncio.run(_fetch_tools())
        
        crew_tools = []
        
        # Process tools
        for tool in tools_list.tools:
            logger.info(f"Found MCP tool: {tool.name}")
            
            # Create dynamic args schema
            args_schema = _create_pydantic_model_from_schema(tool.name, tool.inputSchema)
            
            # Instantiate the tool directly with all parameters
            # Don't set class attributes as they conflict with BaseTool's Pydantic fields
            instance = MCPToolWrapper(
                name=tool.name,
                description=tool.description or f"Tool {tool.name} from MCP",
                args_schema=args_schema,
                server_url=server_url,
                tool_name=tool.name
            )
            crew_tools.append(instance)
        
        # Process resources (knowledge base)
        if resources_list and hasattr(resources_list, 'resources'):
            for resource in resources_list.resources:
                logger.info(f"Found MCP resource: {resource.name} (URI: {resource.uri})")
                
                # Create a tool that reads this resource
                # No arguments needed for reading a resource
                empty_args_schema = create_model(f"{resource.name}Args")
                
                # Sanitize resource name for tool name
                safe_name = "".join(c if c.isalnum() else "_" for c in resource.name)
                safe_name = re.sub(r"_+", "_", safe_name).strip("_")
                
                resource_instance = MCPResourceWrapper(
                    name=f"read_{safe_name}",
                    description=resource.description or f"Read knowledge base resource: {resource.name}",
                    args_schema=empty_args_schema,
                    server_url=server_url,
                    resource_uri=str(resource.uri)
                )
                crew_tools.append(resource_instance)
        
        logger.info(f"✅ Total MCP tools and resources loaded: {len(crew_tools)}")
        return crew_tools

    except Exception as e:
        logger.error(f"Failed to fetch tools from MCP server: {e}")
        return []
