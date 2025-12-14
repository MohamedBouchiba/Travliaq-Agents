"""
Image Generator Service

Centralizes all image generation logic (Hero + Steps) with robust retry mechanisms.
Acts as the single source of truth for image handling, removing this responsibility from agents.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.crew_pipeline.scripts.redis_cache import get_cache

logger = logging.getLogger(__name__)

# Default fallback image if everything else fails
DEFAULT_TRIP_IMAGE = "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=1920&q=80"


class ImageGenerator:
    """
    Service responsable de la génération d'images via MCP (Supabase) avec retries.
    
    Features:
    - 3 tentatives (retries) pour chaque image
    - Validation stricte des URLs retournées
    - Fallback automatique sur image par défaut si échec total
    - Gestion centralisée des prompts
    """

    def __init__(self, mcp_tools: Any):
        """
        Initialize with MCP tools access.

        Args:
            mcp_tools: MCPToolsManager instance or list of tools
        """
        self.mcp_tools = mcp_tools
        self.cache = get_cache(ttl_seconds=604800)  # ⚡ Cache 7 jours pour images

    def generate_hero_image(self, destination: str, trip_code: str) -> str:
        """
        Générer l'image Hero pour le trip.
        
        Args:
            destination: Nom de la destination (ex: "Paris, France")
            trip_code: Code unique du trip pour le dossier stockage
            
        Returns:
            URL de l'image (Supabase ou Fallback)
        """
        prompt = f"hero image for {destination}, spectacular, travel photography, wide angle, 8k"
        logger.info(f"🖼️ Generating HERO image for {destination}...")
        
        url = self._generate_with_retry(
            tool_name="images.hero",
            trip_code=trip_code,
            prompt=prompt
        )
        
        if url:
            return url
            
        logger.warning(f"⚠️ Hero image generation failed after retries. Using default.")
        return DEFAULT_TRIP_IMAGE

    def generate_step_image(
        self, 
        step_number: int,
        title: str, 
        destination: str, 
        trip_code: str,
        activity_type: str = ""
    ) -> str:
        """
        Générer une image pour une étape spécifique.
        
        Args:
            step_number: Numéro de l'étape (pour logs)
            title: Titre de l'étape (utilisé dans le prompt)
            destination: Destination globale
            trip_code: Code unique du trip
            activity_type: Type d'activité (optionnel, pour enrichir prompt)
            
        Returns:
            URL de l'image (Supabase ou Fallback)
        """
        # Construction d'un prompt riche
        prompt_parts = [title]
        if activity_type:
            prompt_parts.append(f"({activity_type})")
        prompt_parts.append(f"in {destination}")
        prompt_parts.append("travel photography, atmospheric, high quality")
        
        prompt = " ".join(prompt_parts)
        logger.info(f"🖼️ Generating STEP {step_number} image: '{title}'...")

        url = self._generate_with_retry(
            tool_name="images.background",
            trip_code=trip_code,
            prompt=prompt
        )
        
        if url:
            return url
            
        logger.warning(f"⚠️ Step {step_number} image generation failed. Using default.")
        return DEFAULT_TRIP_IMAGE

    def generate_image(self, prompt: str, trip_code: str, image_type: str = "background") -> Optional[str]:
        """
        Méthode générique pour générer une image avec un prompt fourni directement.
        
        Args:
            prompt: Le prompt complet
            trip_code: Le code du trip
            image_type: 'background' (défaut) ou 'hero'
            
        Returns:
            URL de l'image ou None si échec (et pas de fallback par défaut ici pour flexibilité, ou DEFAULT?)
            Pour PostProcessingEnricher, on veut probablement le fallback ou None.
            Mais _generate_with_retry retourne None si échec final.
        """
        tool_name = "images.hero" if image_type == "hero" else "images.background"
        
        url = self._generate_with_retry(
            tool_name=tool_name,
            trip_code=trip_code,
            prompt=prompt
        )
        
        return url if url else DEFAULT_TRIP_IMAGE

    def _generate_with_retry(
        self,
        tool_name: str,
        trip_code: str,
        prompt: str,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Logique centrale de génération avec retry ET cache Redis.

        ⚡ OPTIMISATION: Vérifie cache d'abord (7j TTL) pour éviter régénération.
        """
        # ⚡ CACHE: Créer clé unique basée sur prompt + tool_name
        cache_key = f"image:{tool_name}|{prompt[:100]}"  # Limiter longueur prompt pour clé

        # Fonction de génération si cache miss
        def compute_image():
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(f"   🔄 Attempt {attempt}/{max_retries} for {tool_name}...")

                    # Invocation dynamique de l'outil
                    result = self._invoke_mcp_tool(tool_name, trip_code=trip_code, prompt=prompt)

                    # Validation du résultat
                    if self._is_valid_url(result, trip_code):
                        # Validation spécifique : s'assurer que l'URL contient le bon trip_code
                        # (Correction de bug précédent où l'URL pouvait avoir le mauvais folder)
                        final_url = self._fix_url_folder(result, trip_code)
                        logger.info(f"   ✅ Image generated successfully: {final_url[:80]}...")
                        return final_url

                    # Si on arrive ici, le résultat était invalide (None ou erreur)
                    logger.warning(f"   ⚠️ Attempt {attempt} returned invalid result: {str(result)[:100]}")

                except Exception as e:
                    logger.warning(f"   ⚠️ Attempt {attempt} failed with exception: {e}")

                # Attendre un peu avant retry, sauf si c'est la dernière tentative
                if attempt < max_retries:
                    time.sleep(1)

            return None

        # ⚡ Utiliser cache-aside pattern
        return self.cache.get_or_compute(cache_key, compute_image)

    def _invoke_mcp_tool(self, tool_name: str, **kwargs) -> Any:
        """Appel bas niveau à l'outil MCP (supporte manager ou liste)."""
        # Cas 1: mcp_tools est un manager avec call_tool
        if hasattr(self.mcp_tools, 'call_tool'):
            return self.mcp_tools.call_tool(tool_name, **kwargs)
        
        # Cas 2: mcp_tools est une liste d'objets tools (legacy)
        if isinstance(self.mcp_tools, list):
            for tool in self.mcp_tools:
                if hasattr(tool, 'name') and tool.name == tool_name:
                    if hasattr(tool, 'func'):
                        return tool.func(**kwargs)
                    elif hasattr(tool, '_run'):
                        return tool._run(**kwargs)
                    elif callable(tool):
                        return tool(**kwargs)
                        
        logger.error(f"❌ Tool '{tool_name}' not found in mcp_tools configuration")
        return None

    def _is_valid_url(self, result: Any, trip_code: str) -> bool:
        """Vérifie si le résultat ressemble à une URL Supabase valide."""
        if not result:
            return False
            
        if isinstance(result, dict):
            # Certains tools retournent dict {'url': ..., 'success': ...}
            if result.get('success') is False:
                return False
            url = result.get('url')
            # 🔧 FIX: Nettoyer les guillemets doubles potentiels (double encoding MCP)
            if isinstance(url, str):
                url = self._clean_url_string(url)
            # 🔧 FIX: Vérifier que l'URL commence bien par http (pas un JSON string)
            return bool(url and isinstance(url, str) and url.startswith("http") and "supabase.co" in url)
            
        if isinstance(result, str):
            # Vérifier si c'est une URL et pas un message d'erreur
            cleaned = self._clean_url_string(result)
            if "supabase.co" in cleaned and cleaned.startswith("http"):
                return True
            if "error" in result.lower() or "failed" in result.lower():
                return False
                
        return False

    def _clean_url_string(self, url: str) -> str:
        """
        🔧 FIX: Nettoie une URL potentiellement double-encodée.
        
        Gère les cas:
        - '"https://..."' (guillemets JSON autour de l'URL)
        - '{"url": "https://..."}' (JSON string au lieu de dict)
        """
        if not isinstance(url, str):
            return ""
        
        url = url.strip()
        
        # Cas 1: Guillemets JSON autour de l'URL entière
        if url.startswith('"') and url.endswith('"'):
            url = url[1:-1]
        
        # Cas 2: JSON string contenant {"url": "..."}
        if url.startswith('{') and 'url' in url:
            try:
                import json
                parsed = json.loads(url)
                if isinstance(parsed, dict) and 'url' in parsed:
                    url = parsed['url']
                    # Récursion pour nettoyer les guillemets additionnels
                    return self._clean_url_string(url)
            except (json.JSONDecodeError, ValueError):
                pass
        
        return url


    def _fix_url_folder(self, url: str, expected_trip_code: str) -> str:
        """
        Extrait l'URL d'un dict si nécessaire et corrige le folder si incohérent.
        """
        # Extraire string si dict
        if isinstance(url, dict):
            url = url.get('url', '')
            
        if not isinstance(url, str):
            return ""
        
        # 🔧 FIX: Nettoyer les guillemets doubles potentiels (double encoding)
        url = self._clean_url_string(url)

        # Logique de correction de folder (copié de StepTemplateGenerator)
        if "/TRIPS/" not in url:
            return url

        parts = url.split("/TRIPS/")
        if len(parts) != 2:
            return url

        base_url = parts[0] + "/TRIPS/"
        remainder = parts[1]
        path_parts = remainder.split("/", 1)
        
        if len(path_parts) != 2:
            return url

        current_folder = path_parts[0]
        filename = path_parts[1]

        if current_folder != expected_trip_code:
            logger.debug(f"   🔧 Fixing URL folder: '{current_folder}' -> '{expected_trip_code}'")
            return f"{base_url}{expected_trip_code}/{filename}"

        return url
