"""Services utilitaires pour enrichir le contexte pays.

Les tests unitaires valident uniquement une normalisation simple des données
provenant d'API publiques. Les fonctions sont volontairement tolérantes aux
erreurs réseau : en cas d'échec, elles renvoient une liste vide plutôt que de
lever une exception bloquante.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional

import httpx


def _build_client(client: Optional[httpx.Client]) -> httpx.Client:
    """Retourne un client httpx utilisable (externe ou contextuel)."""

    return client or httpx.Client()


def fetch_public_holidays(
    country_code: str, year: int = 2026, *, client: Optional[httpx.Client] = None
) -> List[Dict[str, Any]]:
    """Récupère les jours fériés publics pour un pays donné.

    Les valeurs sont normalisées afin que les tests puissent comparer des clés
    cohérentes quel que soit le fournisseur.
    """

    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country_code.upper()}"
    http_client = _build_client(client)

    try:
        response = http_client.get(url)
        response.raise_for_status()
        raw_items = response.json()
    except Exception:
        return []

    normalized: List[Dict[str, Any]] = []
    for item in raw_items:
        normalized.append(
            {
                "date": item.get("date"),
                "local_name": item.get("localName"),
                "name": item.get("name"),
                "country_code": item.get("countryCode"),
                "global": item.get("global", False),
                "counties": item.get("counties") or [],
            }
        )

    return normalized


def fetch_unesco_world_heritage_sites(
    country_code: str, *, client: Optional[httpx.Client] = None
) -> List[Dict[str, Any]]:
    """Récupère les sites UNESCO d'un pays et les normalise."""

    # API publique Opendatasoft (suffisante pour les tests)
    base_url = "https://public.opendatasoft.com/api/records/1.0/search/"
    params = {
        "dataset": "unesco-world-heritage-list",
        "q": "",
        "rows": 200,
        "refine": f"iso_code:{country_code.upper()}",
    }

    http_client = _build_client(client)

    try:
        response = http_client.get(base_url, params=params)
        response.raise_for_status()
        payload = response.json() or {}
    except Exception:
        return []

    normalized: List[Dict[str, Any]] = []
    for item in payload.get("results", []):
        normalized.append(
            {
                "name": item.get("site"),
                "country": item.get("states_name_en"),
                "iso_code": item.get("iso_code"),
                "region": item.get("region_en"),
                "category": item.get("category"),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "year_inscribed": item.get("date_inscribed"),
                "justification": item.get("justification"),
            }
        )

    return normalized


def build_country_context(country_code: str, year: int = 2026) -> Dict[str, Any]:
    """Construit un bloc de contexte agrégé pour un pays donné."""

    return {
        "public_holidays": fetch_public_holidays(country_code, year),
        "unesco_world_heritage_sites": fetch_unesco_world_heritage_sites(country_code),
    }

