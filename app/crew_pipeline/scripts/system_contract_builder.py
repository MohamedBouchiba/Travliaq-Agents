"""Construction déterministe d'un brouillon de System Contract pour la pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


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

    timing = {
        "request_type": questionnaire.get("type_dates") or "flexible",
        "duration_min_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "duration_max_nights": normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "departure_dates_whitelist": [questionnaire.get("date_depart")] if questionnaire.get("date_depart") else [],
        "return_dates_whitelist": [questionnaire.get("date_retour")] if questionnaire.get("date_retour") else [],
    }

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
