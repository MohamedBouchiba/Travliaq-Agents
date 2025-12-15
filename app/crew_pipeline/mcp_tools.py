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
MCP_TIMEOUT_SECONDS = 15 if _FAST_TEST_MODE else 60
MCP_TIMEOUT_GEO_PLACES = 45 if _FAST_TEST_MODE else 240  # Timeout étendu pour geo/places qui peuvent être lents (Wikipedia, OSM)
MCP_TIMEOUT_BOOKING_FLIGHTS = 90 if _FAST_TEST_MODE else 300  # Timeout étendu pour booking et flights (scraping)

# Moins de retries pour accélérer les tests en mode rapide
MCP_MAX_RETRIES = 1 if _FAST_TEST_MODE else 3
MCP_RETRY_DELAY_SECONDS = 0.5 if _FAST_TEST_MODE else 1

# 🔧 FIX: Thread-local storage pour sessions MCP (évite conflits 409)
_thread_local = local()
_server_session_cache: Dict[str, Dict[str, Any]] = {}  # Cache global pour session IDs avec timestamp
# Structure: {server_url: {"session_id": str, "timestamp": float, "retries": int}}

# Session expiry time (5 minutes = 300 seconds)
MCP_SESSION_EXPIRY_SECONDS = 300

async def _ensure_fresh_session(server_url: str, force_refresh: bool = False) -> Optional[str]:
    """
    Assure qu'on a une session MCP fraîche (< 5 minutes).

    Args:
        server_url: URL du serveur MCP
        force_refresh: Si True, force la création d'une nouvelle session

    Returns:
        Session ID ou None si échec
    """
    cached = _server_session_cache.get(server_url)

    # Vérifier si session existe et est toujours valide
    if cached and not force_refresh:
        session_age = time.time() - cached.get("timestamp", 0)
        if session_age < MCP_SESSION_EXPIRY_SECONDS:
            logger.debug(f"Reusing fresh session (age: {int(session_age)}s)")
            return cached.get("session_id")
        else:
            logger.info(f"🔄 Session expired (age: {int(session_age)}s), refreshing...")

    # Créer nouvelle session via initialize
    try:
        session_id = await _initialize_new_session(server_url)
        if session_id:
            _server_session_cache[server_url] = {
                "session_id": session_id,
                "timestamp": time.time(),
                "retries": 0
            }
            logger.info(f"✅ New MCP session created: {session_id[:16]}...")
            return session_id
    except Exception as e:
        logger.error(f"❌ Failed to create new session: {e}")
        return None

    return None

async def _initialize_new_session(server_url: str) -> Optional[str]:
    """
    Initialise une nouvelle session MCP et retourne le session ID.
    """
    import json

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                server_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "roots": {"listChanged": False},
                            "sampling": {}
                        },
                        "clientInfo": {
                            "name": "travliaq-pipeline",
                            "version": "1.0.0"
                        }
                    },
                    "id": 1
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            ) as response:
                response.raise_for_status()

                # Extract session ID from response headers
                session_id = response.headers.get("mcp-session-id")

                if session_id:
                    logger.debug(f"Initialized new session: {session_id[:16]}...")
                    return session_id

                logger.warning("No session ID returned from initialize")
                return None

    except Exception as e:
        logger.error(f"Failed to initialize session: {e}")
        return None

async def _probe_server_session(server_url: str) -> Optional[str]:
    """
    Tente d'obtenir un session ID depuis le serveur MCP.
    Retourne None si le serveur ne fournit pas de session ID.
    """
    cached = _server_session_cache.get(server_url)
    if cached:
        return cached.get("session_id")

    try:
        # Probe initial pour voir si le serveur fournit un session ID
        async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
            resp = await client.get(server_url, headers={"Accept": "text/event-stream"})

            # Si le serveur renvoie un session ID dans les headers
            if "Mcp-Session-Id" in resp.headers:
                session_id = resp.headers["Mcp-Session-Id"]
                logger.info(f"🔄 Session ID reçu du serveur: {session_id[:16]}...")
                _server_session_cache[server_url] = {
                    "session_id": session_id,
                    "timestamp": time.time(),
                    "retries": 0
                }
                return session_id
    except Exception as e:
        logger.debug(f"⚠️ Probe serveur échoué (normal si serveur n'exige pas de session): {e}")

    # Pas de session ID fourni par le serveur
    return None

def _get_thread_session_id(server_url: str) -> str:
    """
    Récupère le session ID MCP pour le thread courant.
    Crée une nouvelle session UUID si nécessaire.
    """
    if not hasattr(_thread_local, 'session_ids'):
        _thread_local.session_ids = {}

    if server_url not in _thread_local.session_ids:
        # Créer une nouvelle session UUID pour ce thread
        import uuid
        session_id = str(uuid.uuid4()).replace('-', '')
        _thread_local.session_ids[server_url] = session_id
        logger.info(f"🆕 Session UUID créée pour thread {id(_thread_local)}: {session_id[:16]}...")

    return _thread_local.session_ids[server_url]

# Cache pour les headers de session (pour éviter de refaire le probe à chaque appel)
_session_headers_cache: Dict[str, Dict[str, str]] = {}

async def _get_session_headers(server_url: str, use_server_session: bool = True) -> Dict[str, str]:
    """
    Récupère les headers de session nécessaires pour le serveur MCP.

    🔧 FIX:
    1. Essaie d'abord d'obtenir session ID du serveur (si use_server_session=True)
    2. Sinon, utilise session ID unique par thread pour éviter conflits 409

    Args:
        server_url: URL du serveur MCP
        use_server_session: Si True, tente d'obtenir session depuis serveur (défaut: True)
    """
    headers = {}

    # Option 1: Essayer d'obtenir session ID du serveur (pour initialisation)
    if use_server_session:
        server_session = await _probe_server_session(server_url)
        if server_session:
            headers["Mcp-Session-Id"] = server_session
            logger.debug(f"🔑 Using server-provided session ID: {server_session[:16]}...")
            return headers

    # Option 2: Utiliser session ID par thread (pour appels parallèles)
    thread_session_id = _get_thread_session_id(server_url)
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

    async def _call_tool_via_post_sse(self, arguments: dict, retry_on_400: bool = True) -> str:
        """
        Call MCP tool using POST+SSE (bypasses GET requests which Railway rejects).

        This method:
        1. Ensures session is fresh (< 5 minutes)
        2. Sends tools/call via POST with SSE headers
        3. Parses SSE response to extract tool result
        4. Auto-reinitializes session on 400 errors
        """
        import json

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 🔧 FIX: Ensure session is fresh (refresh if expired)
            session_id = await _ensure_fresh_session(self.server_url)

            if not session_id:
                # Try one more time with force refresh
                logger.warning("No session available, forcing refresh...")
                session_id = await _ensure_fresh_session(self.server_url, force_refresh=True)

            if not session_id:
                raise Exception("Could not obtain MCP session ID")

            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id
            }

            logger.debug(f"Calling {self.tool_name} via POST+SSE (session: {session_id[:16]}...)")

            # Build tools/call JSON-RPC request
            call_request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": self.tool_name,
                    "arguments": arguments
                },
                "id": 3  # Arbitrary ID for this request
            }

            try:
                # Send POST request and parse SSE response
                async with client.stream(
                    "POST",
                    self.server_url,
                    json=call_request,
                    headers=headers
                ) as response:
                    response.raise_for_status()

                    # Parse SSE stream to find tool result
                    async for event_data in _parse_sse_events(response.aiter_lines()):
                        if event_data.get("id") == 3:
                            # Found our response
                            if "error" in event_data:
                                error_msg = event_data["error"].get("message", str(event_data["error"]))
                                raise Exception(f"MCP tool error: {error_msg}")

                            # Extract result content
                            result = event_data.get("result", {})
                            content_list = result.get("content", [])

                            # Format output from content items
                            output = []
                            for item in content_list:
                                if isinstance(item, dict):
                                    if "text" in item:
                                        output.append(item["text"])
                                    else:
                                        output.append(str(item))
                                else:
                                    output.append(str(item))

                            return "\n".join(output) if output else str(result)

                    # If we got here, response wasn't found in stream
                    raise Exception(f"No response received for {self.tool_name} (id=3)")

            except httpx.HTTPStatusError as e:
                # 🔧 FIX: Auto-reinitialize on 400 Bad Request
                if e.response.status_code == 400 and retry_on_400:
                    logger.warning(f"⚠️ 400 Bad Request - session may be invalid, refreshing session...")
                    # Force refresh session
                    await _ensure_fresh_session(self.server_url, force_refresh=True)
                    # Retry once with new session
                    return await self._call_tool_via_post_sse(arguments, retry_on_400=False)
                else:
                    # Re-raise other HTTP errors
                    raise

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
                    # 🔧 FIX: Use POST+SSE instead of GET (Railway rejects GET requests)
                    # This method reuses the session from _fetch_tools() and sends tools/call via POST
                    success_output = await self._call_tool_via_post_sse(normalized_kwargs)

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

                # 🔧 FIX: Pas de session ID dans l'URL, seulement dans les headers
                # Le serveur MCP gère les sessions via headers uniquement
                post_url = self.server_url

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
    timeout: float = 10,  # 🔧 FIX: Augmenté à 10s pour connexion initiale
    sse_read_timeout: float = 60,  # 🔧 FIX: Augmenté à 60s pour initialisation
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

async def _parse_sse_events(lines_iter):
    """Parse SSE events from async line iterator, handling multi-line data."""
    import json

    current_data = []

    async for line in lines_iter:
        if line.startswith("data: "):
            # Accumulate data lines
            current_data.append(line[6:])
        elif line == "" and current_data:
            # Blank line marks end of event - parse accumulated data
            json_str = "".join(current_data)
            current_data = []
            try:
                yield json.loads(json_str)
            except json.JSONDecodeError:
                pass

def get_mcp_tools(server_url: str) -> List[BaseTool]:
    """
    Connects to the MCP server, lists available tools, and returns them as CrewAI tools.
    """
    if not sse_client:
        logger.error("MCP library not installed. Cannot fetch tools.")
        return []

    async def _fetch_tools():
        """
        Fetch tools from MCP server using POST with SSE response parsing.

        Railway's fastMCP server responds with SSE format even for POST requests
        when Accept header includes text/event-stream.
        """
        import json

        try:
            # Timeout élevé pour permettre aux outils lents (places.overview, booking) de fonctionner
            # Note: Ce timeout est pour la connexion initiale, pas pour l'exécution des outils
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 1: Initialize session
                logger.debug(f"Initializing MCP session with POST to {server_url}")

                async with client.stream(
                    "POST",
                    server_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "roots": {"listChanged": False},
                                "sampling": {}
                            },
                            "clientInfo": {
                                "name": "travliaq-pipeline",
                                "version": "1.0.0"
                            }
                        },
                        "id": 1
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                ) as response:
                    response.raise_for_status()

                    # Extract session ID from response headers
                    session_id = response.headers.get("mcp-session-id")
                    logger.debug(f"MCP session ID: {session_id}")

                    # 🔧 FIX: Store session ID globally with timestamp for reuse in tool execution
                    if session_id:
                        _server_session_cache[server_url] = {
                            "session_id": session_id,
                            "timestamp": time.time(),
                            "retries": 0
                        }

                    # Read SSE stream and find our response
                    init_data = None
                    async for event_data in _parse_sse_events(response.aiter_lines()):
                        logger.debug(f"Parsed SSE event: {str(event_data)[:100]}")
                        if event_data.get("id") == 1:
                            init_data = event_data
                            break

                if not init_data:
                    logger.error("❌ No initialize response received from MCP server")
                    return types.ListToolsResult(tools=[]), None

                if "error" in init_data:
                    logger.error(f"❌ MCP initialize error: {init_data['error']}")
                    return types.ListToolsResult(tools=[]), None

                server_info = init_data.get("result", {})
                logger.info(f"✅ MCP Server initialized: {server_info.get('serverInfo', {}).get('name', 'Unknown')}")

                # Step 2: List tools - reuse session ID
                logger.debug(f"Listing MCP tools via POST with SSE (session: {session_id})")

                # Build headers with session ID
                tools_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
                if session_id:
                    tools_headers["Mcp-Session-Id"] = session_id

                async with client.stream(
                    "POST",
                    server_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/list",
                        "params": {},
                        "id": 2
                    },
                    headers=tools_headers
                ) as response:
                    response.raise_for_status()

                    # Read SSE stream and find our response
                    tools_data = None
                    async for event_data in _parse_sse_events(response.aiter_lines()):
                        if event_data.get("id") == 2:
                            tools_data = event_data
                            break

                if not tools_data:
                    logger.error("❌ No tools/list response received from MCP server")
                    return types.ListToolsResult(tools=[]), None

                if "error" in tools_data:
                    logger.error(f"❌ MCP tools/list error: {tools_data['error']}")
                    return types.ListToolsResult(tools=[]), None

                # Parse tools from JSON-RPC response
                tools_list = tools_data.get("result", {}).get("tools", [])
                logger.info(f"✅ Found {len(tools_list)} MCP tools via POST+SSE")

                # Convert to MCP types.Tool objects
                mcp_tools = []
                for tool_dict in tools_list:
                    mcp_tool = types.Tool(
                        name=tool_dict["name"],
                        description=tool_dict.get("description", ""),
                        inputSchema=tool_dict.get("inputSchema", {"type": "object", "properties": {}})
                    )
                    mcp_tools.append(mcp_tool)

                return types.ListToolsResult(tools=mcp_tools), None

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error from MCP server: {e.response.status_code} {e.response.reason_phrase}")
            logger.error(f"   URL: {e.request.url}")
            logger.error(f"   Request headers: {dict(e.request.headers)}")
            logger.error(f"   Response headers: {dict(e.response.headers)}")
            # Don't try to read body on streaming responses
            return types.ListToolsResult(tools=[]), None
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching MCP tools: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"   Traceback: {traceback.format_exc()}")
            return types.ListToolsResult(tools=[]), None

    # 🔧 FIX: Gérer les erreurs de terminaison au niveau de asyncio.run()
    tools_list = None
    resources_list = None

    try:
        logger.info(f"Fetching MCP tools from {server_url}...")
        tools_list, resources_list = asyncio.run(_fetch_tools())
    except BaseExceptionGroup as eg:
        # Vérifier si on a récupéré les outils malgré l'erreur
        logger.error(f"❌ TaskGroup error fetching tools from MCP server: {eg}")
        # L'erreur a déjà été loggée, retourner liste vide
        return []
    except Exception as e:
        logger.error(f"❌ Failed to fetch tools from MCP server: {e}")
        return []

    if tools_list is None:
        logger.error("❌ Failed to fetch tools (returned None)")
        return []

    try:
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
        error_msg = f"{type(first_exc).__name__}: {str(first_exc)}"

        # 🔧 FIX: Diagnostic spécifique selon le type d'erreur
        if "502" in error_msg and "Bad Gateway" in error_msg:
            logger.error(
                f"❌ Serveur MCP down (502 Bad Gateway): {server_url}\n"
                f"   Solutions:\n"
                f"   1. Vérifier logs Railway: railway logs --project travliaq-mcp\n"
                f"   2. Redémarrer: railway restart --service travliaq-mcp-production\n"
                f"   3. Vérifier port binding et configuration\n"
                f"   Le pipeline continuera sans MCP (valeurs par défaut utilisées)"
            )
        elif "ReadTimeout" in error_msg or "timeout" in error_msg.lower():
            logger.error(
                f"❌ Timeout lors de la connexion MCP: {server_url}\n"
                f"   Le serveur MCP prend trop de temps à répondre.\n"
                f"   Le pipeline continuera sans MCP (valeurs par défaut utilisées)"
            )
        else:
            logger.error(f"❌ TaskGroup error fetching tools from MCP server: {error_msg}")

        return []
    except Exception as e:
        error_msg = str(e)
        if "502" in error_msg:
            logger.error(
                f"❌ Serveur MCP down (502): {server_url}\n"
                f"   Vérifiez Railway logs et redémarrez le service MCP"
            )
        else:
            logger.error(f"❌ Failed to fetch tools from MCP server: {error_msg}")
        return []
