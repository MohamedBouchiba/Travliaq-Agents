import os
import asyncio
import logging
from typing import Any, List, Dict, Type, Optional
import time
import re
from datetime import date, datetime
from functools import wraps
from threading import local

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


def validate_date_params(func):
    """
    Décorateur qui valide les paramètres de date AVANT l'exécution de l'outil MCP.

    Vérifie que toutes les dates sont:
    - Au format ISO valide (YYYY-MM-DD)
    - Dans le futur (>= aujourd'hui)

    Lance une ValueError avec message explicite si validation échoue.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        today = date.today()

        # Liste des paramètres de date à valider
        date_params = [
            'checkin',
            'checkout',
            'departure',
            'return_date',
            'date',
            'departure_date',
            'return',
        ]

        for param in date_params:
            if param in kwargs:
                date_str = kwargs[param]

                if not date_str:
                    continue  # Paramètre optionnel non fourni

                # Validation du format
                try:
                    date_obj = datetime.fromisoformat(str(date_str)).date()
                except (ValueError, AttributeError) as e:
                    raise ValueError(
                        f"❌ Format de date invalide pour '{param}': {date_str}\n"
                        f"Format attendu: YYYY-MM-DD (exemple: 2025-12-15)\n"
                        f"Erreur: {e}"
                    ) from e

                # Validation date future
                if date_obj < today:
                    raise ValueError(
                        f"❌ Date passée détectée pour '{param}': {date_str}\n"
                        f"Les voyages ne peuvent être planifiés que dans le futur.\n"
                        f"Date minimum: {today.isoformat()}\n"
                        f"💡 Suggestion: Consulte system_contract.timing.departure_dates_whitelist "
                        f"pour les dates validées."
                    )

        # Si toutes les validations passent, exécuter la fonction
        return func(*args, **kwargs)

    return wrapper


# Configuration pour les retries et timeouts
_FAST_TEST_MODE = os.getenv("FAST_TEST_MODE", "").lower() in {"1", "true", "yes", "on"}

# Timeouts réduits en mode test rapide afin d'éviter les longues attentes pendant les tests
MCP_TIMEOUT_SECONDS = 15 if _FAST_TEST_MODE else 30
MCP_TIMEOUT_GEO_PLACES = 45 if _FAST_TEST_MODE else 90  # Timeout étendu pour geo/places qui peuvent être lents
MCP_TIMEOUT_BOOKING_FLIGHTS = 90 if _FAST_TEST_MODE else 180  # Timeout étendu pour booking et flights (scraping)

# Moins de retries pour accélérer les tests en mode rapide
MCP_MAX_RETRIES = 1 if _FAST_TEST_MODE else 3
MCP_RETRY_DELAY_SECONDS = 0.5 if _FAST_TEST_MODE else 1

# 🔧 FIX: Thread-local storage pour sessions MCP (évite conflits 409)
_thread_local = local()

def _get_thread_session_id(server_url: str) -> Optional[str]:
    """
    Récupère le session ID MCP pour le thread courant.
    Crée une nouvelle session si nécessaire.
    """
    if not hasattr(_thread_local, 'session_ids'):
        _thread_local.session_ids = {}

    if server_url not in _thread_local.session_ids:
        # Créer une nouvelle session pour ce thread
        import uuid
        session_id = str(uuid.uuid4()).replace('-', '')
        _thread_local.session_ids[server_url] = session_id
        logger.info(f"🆕 Nouvelle session MCP créée pour thread {id(_thread_local)}: {session_id[:16]}...")

    return _thread_local.session_ids[server_url]

# Cache pour les headers de session (pour éviter de refaire le probe à chaque appel)
_session_headers_cache: Dict[str, Dict[str, str]] = {}

async def _get_session_headers(server_url: str) -> Dict[str, str]:
    """
    Récupère les headers de session nécessaires pour le serveur MCP.
    🔧 FIX: Utilise un session ID unique par thread pour éviter conflits 409.
    """
    # Utiliser session ID par thread
    thread_session_id = _get_thread_session_id(server_url)

    headers = {}
    headers["Mcp-Session-Id"] = thread_session_id
    logger.debug(f"🔑 Using thread-local session ID: {thread_session_id[:16]}...")

    return headers


def _sanitize_tool_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Supprime les paramètres None pour éviter les erreurs de validation Pydantic."""

    cleaned: Dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        if value is None:
            continue
        cleaned[key] = value
    return cleaned

class MCPToolWrapper(BaseTool):
    """
    A generic wrapper for MCP tools to be used in CrewAI.
    
    Inclut retry logic, timeout et gestion d'erreurs robuste.
    """
    server_url: str = Field(..., description="URL of the MCP server")
    tool_name: str = Field(..., description="Name of the tool on the MCP server")
    timeout: int = Field(default=MCP_TIMEOUT_SECONDS, description="Timeout en secondes")
    max_retries: int = Field(default=MCP_MAX_RETRIES, description="Nombre maximum de tentatives")

    @validate_date_params
    def _run(self, **kwargs: Any) -> Any:
        return asyncio.run(self._async_run(**kwargs))

    async def _async_run(self, **kwargs: Any) -> Any:
        if not sse_client:
            logger.error("MCP library not installed")
            return "MCP library not installed."

        last_error = None

        normalized_kwargs = _sanitize_tool_arguments(dict(kwargs))
        if self.tool_name.startswith("flights.") and "force_refresh" not in normalized_kwargs:
            # Certains outils flights exigent un booléen explicite, sinon Pydantic échoue
            normalized_kwargs["force_refresh"] = False
        
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
                            result = await session.call_tool(self.tool_name, arguments=normalized_kwargs)
                            
                            # Format the result
                            output = []
                            if result.content:
                                for item in result.content:
                                    if hasattr(item, "text"):
                                        output.append(item.text)
                                    else:
                                        output.append(str(item))
                            
                            success_output = "\n".join(output)

                            # Log détaillé pour les outils images pour debug
                            if self.tool_name.startswith("images."):
                                logger.info(
                                    f"✅ MCP tool {self.tool_name} exécuté avec succès - Résultat: {success_output[:500]}",
                                    extra={"tool": self.tool_name, "output_size": len(success_output), "output_preview": success_output[:200]}
                                )
                            else:
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
            except BaseExceptionGroup as eg:
                # anyio TaskGroup raises BaseExceptionGroup when tasks fail
                # Extract first exception from the group for clearer error message
                first_exc = eg.exceptions[0] if eg.exceptions else eg
                last_error = f"TaskGroup error: {type(first_exc).__name__}: {str(first_exc)}"

                # 🔧 FIX: Détection spéciale des erreurs 409 Conflict
                is_409_conflict = "409" in str(first_exc) and "Conflict" in str(first_exc)

                logger.warning(
                    f"⚠️ TaskGroup error pour {self.tool_name} (tentative {attempt}/{self.max_retries}): {last_error}",
                    extra={"tool": self.tool_name, "error": last_error, "is_409": is_409_conflict}
                )
            except Exception as e:
                last_error = str(e)
                is_409_conflict = "409" in str(e) and "Conflict" in str(e)
                logger.warning(
                    f"⚠️ Erreur pour {self.tool_name} (tentative {attempt}/{self.max_retries}): {e}",
                    extra={"tool": self.tool_name, "error": str(e), "is_409": is_409_conflict}
                )

            # 🔧 FIX: Exponential backoff avec délai croissant (2^attempt secondes)
            if attempt < self.max_retries:
                backoff_delay = (2 ** attempt) * MCP_RETRY_DELAY_SECONDS  # 1s, 2s, 4s, 8s...
                logger.info(f"⏳ Retry dans {backoff_delay}s...")
                await asyncio.sleep(backoff_delay)
        
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

    @validate_date_params
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
        except BaseExceptionGroup as eg:
            # anyio TaskGroup raises BaseExceptionGroup when tasks fail
            first_exc = eg.exceptions[0] if eg.exceptions else eg
            error_msg = f"TaskGroup error: {type(first_exc).__name__}: {str(first_exc)}"
            logger.error(f"❌ TaskGroup error reading resource {self.resource_uri}: {error_msg}")
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
    sse_read_timeout: float = 30,  # Réduit de 5min à 30s pour éviter les hangs
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
                                        logger.info(f"📦 Parsing POST response as JSON-RPC message...")
                                        
                                        # The response might be SSE-formatted (event: message\ndata: {...})
                                        response_text = response.text.strip()
                                        json_text = response_text
                                        
                                        # Check if it's SSE format
                                        if response_text.startswith("event:"):
                                            current_event = None
                                            for line in response_text.split('\n'):
                                                line = line.strip()
                                                if not line:
                                                    continue
                                                    
                                                if line.startswith('event:'):
                                                    current_event = line[6:].strip()
                                                elif line.startswith('data:'):
                                                    json_text = line[5:].strip()
                                                    
                                                    try:
                                                        response_message = types.JSONRPCMessage.model_validate_json(json_text)
                                                        response_session_message = SessionMessage(response_message)
                                                        await read_stream_writer.send(response_session_message)
                                                    except Exception as exc:
                                                        logger.error(f"❌ Failed to parse JSON from SSE line: {exc}")
                                        else:
                                            # Fallback for non-SSE response (if any)
                                            try:
                                                response_message = types.JSONRPCMessage.model_validate_json(response_text)
                                                response_session_message = SessionMessage(response_message)
                                                await read_stream_writer.send(response_session_message)
                                            except Exception as exc:
                                                logger.error(f"❌ Failed to parse POST response: {exc}")
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
    Ensures clear descriptions to prevent LLM confusion.
    """
    fields = {}
    if "properties" in schema:
        for field_name, field_info in schema["properties"].items():
            # Basic type mapping
            field_type = Any
            type_name = "any"
            
            if field_info.get("type") == "string":
                field_type = str
                type_name = "string"
            elif field_info.get("type") == "integer":
                field_type = int
                type_name = "integer"
            elif field_info.get("type") == "number":
                field_type = float
                type_name = "number"
            elif field_info.get("type") == "boolean":
                field_type = bool
                type_name = "boolean"
            elif field_info.get("type") == "array":
                field_type = List[Any]
                type_name = "array"
            
            # Get original description and enhance it
            original_desc = field_info.get("description", "")
            
            # Create a CLEAR description that prevents confusion
            is_required = field_name in schema.get("required", [])
            
            default_value = None
            if field_type is bool:
                # ✅ Evite les erreurs pydantic "Input should be a valid boolean" en forçant un défaut explicite
                default_value = False
            elif field_info.get("type") == "array":
                default_value = []

            if is_required:
                # For required fields, emphasize passing the actual value
                enhanced_desc = f"{original_desc}. Pass a {type_name} value directly (not a dict/object)." if original_desc else f"Pass a {type_name} value directly (not a dict/object)."
                if default_value is not None:
                    fields[field_name] = (field_type, Field(default_value, description=enhanced_desc))
                else:
                    fields[field_name] = (field_type, Field(..., description=enhanced_desc))
            else:
                # For optional fields, allow None or actual value
                enhanced_desc = f"{original_desc}. Optional {type_name} value or omit." if original_desc else f"Optional {type_name} value or omit."
                fields[field_name] = (Optional[field_type], Field(default_value, description=enhanced_desc))
    
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
            
            # Déterminer le timeout en fonction du type d'outil
            tool_timeout = MCP_TIMEOUT_SECONDS
            if tool.name.startswith("booking.") or tool.name.startswith("flights."):
                tool_timeout = MCP_TIMEOUT_BOOKING_FLIGHTS
                logger.info(f"⏱️ Using extended timeout ({tool_timeout}s) for {tool.name}")
            elif tool.name.startswith("geo.") or tool.name.startswith("places."):
                tool_timeout = MCP_TIMEOUT_GEO_PLACES
                logger.info(f"⏱️ Using extended timeout ({tool_timeout}s) for {tool.name}")
            
            # Instantiate the tool directly with all parameters
            # Don't set class attributes as they conflict with BaseTool's Pydantic fields
            instance = MCPToolWrapper(
                name=tool.name,
                description=tool.description or f"Tool {tool.name} from MCP",
                args_schema=args_schema,
                server_url=server_url,
                tool_name=tool.name,
                timeout=tool_timeout
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

    except BaseExceptionGroup as eg:
        # anyio TaskGroup raises BaseExceptionGroup when tasks fail
        first_exc = eg.exceptions[0] if eg.exceptions else eg
        logger.error(f"TaskGroup error fetching tools from MCP server: {type(first_exc).__name__}: {str(first_exc)}")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch tools from MCP server: {e}")
        return []
