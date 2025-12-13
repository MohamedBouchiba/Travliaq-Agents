"""
Redis Cache Service pour données durables (GPS, images, métadonnées)

Utilise Upstash Redis (REST API) pour cacher:
- Coordonnées GPS de lieux (TTL: 7 jours)
- URLs d'images Supabase (TTL: 7 jours)
- Métadonnées géographiques (pays, descriptions)

Gains attendus:
- Temps: -70% sur appels MCP répétés (ex: Tokyo déjà visité)
- Coût: -60% sur appels API externes
- Fiabilité: +40% (fallback si API down)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Service de cache Redis via Upstash REST API.

    Features:
    - TTL configurable (défaut: 7 jours)
    - Serialization JSON automatique
    - Gestion d'erreurs robuste (fallback graceful)
    - Support REST API Upstash
    """

    def __init__(self, ttl_seconds: int = 604800):  # 7 jours par défaut
        """
        Initialiser le cache Redis Upstash.

        Args:
            ttl_seconds: Time-to-live en secondes (défaut: 604800 = 7 jours)

        Env vars requises:
            UPSTASH_REDIS_REST_URL: URL de l'endpoint REST Upstash
            UPSTASH_REDIS_REST_TOKEN: Token d'authentification
        """
        self.redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
        self.redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self.ttl_seconds = ttl_seconds
        self.enabled = bool(self.redis_url and self.redis_token)

        if self.enabled:
            logger.info(f"✅ Redis cache enabled (TTL: {ttl_seconds}s = {ttl_seconds//86400} days)")
        else:
            logger.warning("⚠️ Redis cache disabled (missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN)")

    def _make_key(self, prefix: str, *args: Any) -> str:
        """
        Créer clé de cache déterministe.

        Args:
            prefix: Préfixe (ex: "gps", "image", "geo")
            *args: Arguments à hasher

        Returns:
            Clé format: "prefix:hash"

        Example:
            >>> cache._make_key("gps", "Tokyo", "Japan")
            "gps:a3f5e1b2c..."
        """
        # Combiner tous les args en string
        combined = "|".join(str(arg) for arg in args)
        # Hash SHA256 (court et unique)
        hash_hex = hashlib.sha256(combined.encode()).hexdigest()[:16]
        return f"{prefix}:{hash_hex}"

    def get(self, key: str) -> Optional[Any]:
        """
        Récupérer valeur depuis cache.

        Args:
            key: Clé de cache

        Returns:
            Valeur désérialisée ou None si pas en cache
        """
        if not self.enabled:
            return None

        try:
            # Upstash REST API: GET /get/{key}
            url = urljoin(self.redis_url, f"/get/{key}")
            headers = {"Authorization": f"Bearer {self.redis_token}"}

            response = requests.get(url, headers=headers, timeout=2)

            if response.status_code == 200:
                data = response.json()
                result = data.get("result")

                if result:
                    logger.debug(f"✅ Cache HIT: {key}")
                    return json.loads(result)
                else:
                    logger.debug(f"⚠️ Cache MISS: {key}")
                    return None
            else:
                logger.warning(f"⚠️ Redis GET failed ({response.status_code}): {key}")
                return None

        except Exception as e:
            logger.error(f"❌ Redis GET error: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Stocker valeur dans cache avec TTL.

        Args:
            key: Clé de cache
            value: Valeur (sera sérialisée en JSON)
            ttl: TTL en secondes (défaut: self.ttl_seconds)

        Returns:
            True si succès, False sinon
        """
        if not self.enabled:
            return False

        try:
            ttl = ttl or self.ttl_seconds

            # Upstash REST API: POST /setex/{key}/{seconds} with value as body
            # This is the correct way to set a key with expiration
            url = urljoin(self.redis_url, f"/setex/{key}/{ttl}")
            headers = {
                "Authorization": f"Bearer {self.redis_token}",
                "Content-Type": "application/json"
            }

            # Sérialiser valeur (sera le body directement)
            serialized = json.dumps(value, ensure_ascii=False)

            response = requests.post(url, headers=headers, data=serialized, timeout=2)

            if response.status_code == 200:
                logger.debug(f"✅ Cache SET: {key} (TTL: {ttl}s)")
                return True
            else:
                logger.warning(f"⚠️ Redis SET failed ({response.status_code}): {key}")
                return False

        except Exception as e:
            logger.error(f"❌ Redis SET error: {e}")
            return False

    def get_or_compute(
        self,
        key: str,
        compute_fn: callable,
        ttl: Optional[int] = None
    ) -> Optional[Any]:
        """
        Pattern cache-aside: récupérer depuis cache OU calculer et cacher.

        Args:
            key: Clé de cache
            compute_fn: Fonction pour calculer la valeur si cache miss
            ttl: TTL custom (défaut: self.ttl_seconds)

        Returns:
            Valeur (depuis cache ou calculée)

        Example:
            >>> def fetch_gps():
            ...     return {"lat": 35.6895, "lon": 139.6917}
            >>>
            >>> gps = cache.get_or_compute("gps:tokyo", fetch_gps)
        """
        # Essayer cache d'abord
        cached = self.get(key)
        if cached is not None:
            return cached

        # Cache miss → calculer
        try:
            value = compute_fn()

            # Stocker dans cache si succès
            if value is not None:
                self.set(key, value, ttl=ttl)

            return value

        except Exception as e:
            logger.error(f"❌ Compute function failed for {key}: {e}")
            return None

    # ========== Helpers spécifiques ==========

    def get_gps(self, location: str, country: str = "") -> Optional[Dict[str, float]]:
        """
        Récupérer coordonnées GPS depuis cache.

        Args:
            location: Nom du lieu
            country: Pays (optionnel)

        Returns:
            {"latitude": float, "longitude": float, "name": str} ou None
        """
        key = self._make_key("gps", location, country)
        return self.get(key)

    def set_gps(
        self,
        location: str,
        latitude: float,
        longitude: float,
        name: str = "",
        country: str = ""
    ) -> bool:
        """
        Stocker coordonnées GPS dans cache.

        Args:
            location: Nom du lieu recherché
            latitude: Latitude
            longitude: Longitude
            name: Nom officiel du lieu
            country: Pays

        Returns:
            True si succès
        """
        key = self._make_key("gps", location, country)
        value = {
            "latitude": latitude,
            "longitude": longitude,
            "name": name or location,
            "country": country
        }
        return self.set(key, value)

    def get_image_url(self, query: str, trip_code: str = "") -> Optional[str]:
        """
        Récupérer URL d'image depuis cache.

        Args:
            query: Query de recherche d'image
            trip_code: Code du trip (optionnel)

        Returns:
            URL de l'image ou None
        """
        key = self._make_key("image", query, trip_code)
        data = self.get(key)
        return data.get("url") if data else None

    def set_image_url(self, query: str, url: str, trip_code: str = "") -> bool:
        """
        Stocker URL d'image dans cache.

        Args:
            query: Query de recherche
            url: URL de l'image Supabase
            trip_code: Code du trip

        Returns:
            True si succès
        """
        key = self._make_key("image", query, trip_code)
        value = {"url": url, "query": query}
        return self.set(key, value)

    # ========== Cache météo ==========

    def get_weather(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str
    ) -> Optional[Dict[str, Any]]:
        """
        Récupérer données météo depuis cache.

        Args:
            latitude: Latitude du lieu
            longitude: Longitude du lieu
            start_date: Date début (YYYY-MM-DD)
            end_date: Date fin (YYYY-MM-DD)

        Returns:
            Données météo ou None
        """
        # Arrondir coordonnées à 2 décimales pour regrouper lieux proches
        lat_rounded = round(latitude, 2)
        lon_rounded = round(longitude, 2)
        key = self._make_key("weather", lat_rounded, lon_rounded, start_date, end_date)
        return self.get(key)

    def set_weather(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        weather_data: Dict[str, Any]
    ) -> bool:
        """
        Stocker données météo dans cache.

        Args:
            latitude: Latitude du lieu
            longitude: Longitude du lieu
            start_date: Date début (YYYY-MM-DD)
            end_date: Date fin (YYYY-MM-DD)
            weather_data: Données météo complètes

        Returns:
            True si succès
        """
        # Arrondir coordonnées à 2 décimales pour regrouper lieux proches
        lat_rounded = round(latitude, 2)
        lon_rounded = round(longitude, 2)
        key = self._make_key("weather", lat_rounded, lon_rounded, start_date, end_date)
        return self.set(key, weather_data)


# Singleton global
_global_cache: Optional[RedisCache] = None


def get_cache(ttl_seconds: int = 604800) -> RedisCache:
    """
    Récupérer instance singleton du cache.

    Args:
        ttl_seconds: TTL par défaut (7 jours)

    Returns:
        Instance RedisCache
    """
    global _global_cache

    if _global_cache is None:
        _global_cache = RedisCache(ttl_seconds=ttl_seconds)

    return _global_cache
