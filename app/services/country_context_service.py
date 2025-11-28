"""Services d'enrichissement contextuel par pays.

Ce module récupère des informations publiques pour enrichir les fiches pays
ou villes, notamment :
- les jours fériés officiels (API Nager.Date)
- les sites du patrimoine mondial de l'UNESCO (catalogue Opendatasoft)

Les fonctions sont synchrones et utilisent httpx avec gestion des erreurs
robuste pour éviter de casser des pipelines en cas d'indisponibilité réseau.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

NAGER_BASE_URL = "https://date.nager.at/api/v3/PublicHolidays"
UNESCO_BASE_URL = "https://data.unesco.org/api/explore/v2.1/catalog/datasets"
UNESCO_WORLD_HERITAGE_DATASET = "whc-sites-2023"
HTTP_TIMEOUT_SECONDS = 10.0


def _get_client(client: Optional[httpx.Client]) -> tuple[httpx.Client, bool]:
    """Retourne un client httpx prêt à l'emploi et indique s'il faut le fermer."""

    if client:
        return client, False

    new_client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    return new_client, True


def fetch_public_holidays(
    country_code: str, year: int = 2026, client: Optional[httpx.Client] = None
) -> List[Dict[str, Any]]:
    """Récupère et normalise les jours fériés pour un pays donné.

    Args:
        country_code: Code ISO alpha-2 (ex: "FR").
        year: Année cible (par défaut 2026).
        client: Client httpx optionnel pour l'injection de transport en tests.

    Returns:
        Liste de dictionnaires normalisés décrivant les jours fériés.
    """

    http_client, should_close = _get_client(client)
    url = f"{NAGER_BASE_URL}/{year}/{country_code.upper()}"

    try:
        response = http_client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - garde-fou réseau
        logger.warning(
            "Échec de récupération des jours fériés",
            extra={"country_code": country_code, "year": year, "error": str(exc)},
        )
        return []
    finally:
        if should_close:
            http_client.close()

    holidays: List[Dict[str, Any]] = []
    for raw in response.json():
        holidays.append(
            {
                "date": raw.get("date"),
                "local_name": raw.get("localName"),
                "name": raw.get("name"),
                "country_code": raw.get("countryCode", country_code.upper()),
                "global": raw.get("global"),
                "counties": raw.get("counties") or [],
            }
        )

    return holidays


def fetch_unesco_world_heritage_sites(
    country_code: str,
    dataset_id: str = UNESCO_WORLD_HERITAGE_DATASET,
    limit: int = 200,
    client: Optional[httpx.Client] = None,
) -> List[Dict[str, Any]]:
    """Récupère les sites UNESCO pour un pays (filtré par code ISO).

    Args:
        country_code: Code ISO alpha-2 du pays (ex: "FR").
        dataset_id: Identifiant du dataset UNESCO (par défaut whc-sites-2023).
        limit: Nombre maximum d'enregistrements à récupérer.
        client: Client httpx optionnel pour tests.

    Returns:
        Liste de sites du patrimoine mondial, normalisés.
    """

    http_client, should_close = _get_client(client)
    url = f"{UNESCO_BASE_URL}/{dataset_id}/records"

    params = {
        "limit": limit,
        # Filtrage par code ISO; la majorité des datasets WHC utilisent iso_code
        "refine": f"iso_code:{country_code.upper()}",
    }

    try:
        response = http_client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - garde-fou réseau
        logger.warning(
            "Échec de récupération des sites UNESCO",
            extra={
                "country_code": country_code,
                "dataset_id": dataset_id,
                "error": str(exc),
            },
        )
        return []
    finally:
        if should_close:
            http_client.close()

    data = response.json() or {}
    results = data.get("results") or data.get("records") or []

    sites: List[Dict[str, Any]] = []
    for raw in results:
        sites.append(
            {
                "name": raw.get("site") or raw.get("name"),
                "country": raw.get("states_name_en") or raw.get("states"),
                "iso_code": raw.get("iso_code", country_code.upper()),
                "region": raw.get("region_en") or raw.get("region"),
                "category": raw.get("category"),
                "latitude": raw.get("latitude"),
                "longitude": raw.get("longitude"),
                "year_inscribed": raw.get("date_inscribed") or raw.get("year"),
                "justification": raw.get("justification"),
            }
        )

    return sites


def build_country_context(
    country_code: str, year: int = 2026, client: Optional[httpx.Client] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Construit un bloc d'informations publiques pour un pays.

    Combinaison simple pour alimenter la clé `travel_info` des documents ville.
    """

    holidays = fetch_public_holidays(country_code, year=year, client=client)
    unesco_sites = fetch_unesco_world_heritage_sites(country_code, client=client)

    return {
        "public_holidays": holidays,
        "unesco_world_heritage_sites": unesco_sites,
    }
