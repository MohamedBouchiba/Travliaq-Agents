"""Construction déterministe d'un brouillon de System Contract pour la pipeline."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


def _validate_future_date(date_str: str | None) -> str | None:
    """
    Valide qu'une date est dans le futur, sinon la corrige automatiquement.

    Args:
        date_str: Date au format ISO (YYYY-MM-DD) ou None

    Returns:
        - Date corrigée si elle était passée
        - Date originale si elle est future
        - None si invalide ou None
    """
    if not date_str:
        return None

    try:
        date_obj = datetime.fromisoformat(str(date_str)).date()
        today = date.today()

        if date_obj < today:
            # Calculer combien d'années ajouter pour revenir dans le futur
            years_to_add = 1
            while date_obj.replace(year=date_obj.year + years_to_add) < today:
                years_to_add += 1

            corrected_date = date_obj.replace(year=date_obj.year + years_to_add)

            logger.warning(
                f"Date passée corrigée dans System Contract: {date_str} → {corrected_date.isoformat()} "
                f"(+{years_to_add} an(s))"
            )

            return corrected_date.isoformat()

        return date_str

    except (ValueError, AttributeError) as e:
        logger.error(f"Format de date invalide ignoré: {date_str} - {e}")
        return None


def build_system_contract(*, questionnaire: Dict[str, Any], normalized_trip_request: Dict[str, Any], persona_context: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble un contrat système minimal sans halluciner de données."""

    request_meta = {
        "request_id": questionnaire.get("id") or questionnaire.get("questionnaire_id"),
        "user_id": questionnaire.get("user_id"),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source_version": "crew_pipeline_v2",
    }

    user_intelligence = {
        "email": questionnaire.get("email"),
        "narrative_summary": persona_context.get("narrative") or persona_context.get("persona") or "",
        "feasibility_status": "PENDING",
        "feasibility_alerts": [],
    }

    # Validation des dates AVANT insertion dans le contrat
    raw_departure = questionnaire.get("date_depart")
    raw_return = questionnaire.get("date_retour")

    validated_departure = _validate_future_date(raw_departure)
    validated_return = _validate_future_date(raw_return)

    timing = {
        "request_type": questionnaire.get("type_dates") or "flexible",
        "duration_min_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "duration_max_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "departure_dates_whitelist": [validated_departure] if validated_departure else [],
        "return_dates_whitelist": [validated_return] if validated_return else [],
    }

    # Tracer les corrections pour monitoring
    if raw_departure and validated_departure and raw_departure != validated_departure:
        timing["_date_corrections"] = timing.get("_date_corrections", [])
        timing["_date_corrections"].append({
            "field": "departure",
            "original": raw_departure,
            "corrected": validated_departure
        })

    if raw_return and validated_return and raw_return != validated_return:
        timing["_date_corrections"] = timing.get("_date_corrections", [])
        timing["_date_corrections"].append({
            "field": "return",
            "original": raw_return,
            "corrected": validated_return
        })

    geography = {
        "origin_city": questionnaire.get("lieu_depart"),
        "destination_is_defined": questionnaire.get("a_destination") == "yes",
        "destination_city": questionnaire.get("destination"),
        "destination_country": None,
        "discovery_climate_zones": [],
        "discovery_regions": [],
        "excluded_tags": questionnaire.get("contraintes") or [],
    }

    financials = {
        "currency": "EUR",
        "total_hard_cap": None,
        "total_soft_cap": None,
        "budget_range_input": questionnaire.get("budget_par_personne"),
    }

    specifications = {
        "flights": {
            "cabin_class": "ECONOMY",
            "luggage_policy": questionnaire.get("bagages"),
            "stopover_tolerance": "AUTO",
            "preference": questionnaire.get("preference_vol"),
        },
        "accommodation": {
            "types_allowed": questionnaire.get("type_hebergement") or [],
            "min_rating_10": None,
            "required_amenities": questionnaire.get("equipements") or [],
            "location_vibe": questionnaire.get("quartier"),
            "comfort": questionnaire.get("confort"),
        },
        "experience": {
            "pace": questionnaire.get("rythme"),
            "interest_vectors": questionnaire.get("styles") or [],
            "constraints": questionnaire.get("contraintes") or [],
            "safety": questionnaire.get("securite") or [],
        },
    }

    return {
        "meta": request_meta,
        "user_intelligence": user_intelligence,
        "timing": timing,
        "geography": geography,
        "financials": financials,
        "specifications": specifications,
    }
