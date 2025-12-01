"""Assemblage final du YAML `trip` à partir des artefacts d'agents et de scripts."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_MAIN_IMAGE = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e"


def _safe_get(output_map: Dict[str, Any], key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    value = output_map.get(key)
    return value if isinstance(value, dict) else (default or {})


def _extract_summary_stats(final_choice: Dict[str, Any]) -> List[Dict[str, Any]]:
    stats = final_choice.get("summary_stats")
    if isinstance(stats, list):
        return stats
    return []


def assemble_trip(
    *,
    questionnaire: Dict[str, Any],
    normalized_trip_request: Dict[str, Any],
    agent_outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """Consolide le voyage final en respectant le schéma Trip."""

    destination_choice = _safe_get(agent_outputs, "destination_decision")
    flights = _safe_get(agent_outputs, "flight_pricing")
    lodging = _safe_get(agent_outputs, "lodging_pricing")
    activities = _safe_get(agent_outputs, "activities_geo_design")

    def _build_fallback_image(destination: Optional[str]) -> str:
        if destination:
            slug = str(destination).lower().replace(" ", "-")
            return f"https://source.unsplash.com/featured/?{slug},travel"
        return DEFAULT_MAIN_IMAGE

    trip_core = {
        "code": destination_choice.get("code") or (questionnaire.get("destination") or "DEST2026").upper().replace(" ", ""),
        "destination": destination_choice.get("destination") or questionnaire.get("destination"),
        "destination_en": destination_choice.get("destination_en"),
        "total_days": destination_choice.get("total_days") or normalized_trip_request.get("nuits_exactes") or questionnaire.get("nuits_exactes"),
        "main_image": destination_choice.get("main_image"),
        "flight_from": flights.get("from") or questionnaire.get("lieu_depart"),
        "flight_to": flights.get("to") or questionnaire.get("destination"),
        "flight_duration": flights.get("duration"),
        "flight_type": flights.get("type"),
        "hotel_name": lodging.get("hotel_name"),
        "hotel_rating": lodging.get("hotel_rating"),
        "total_price": destination_choice.get("total_price") or destination_choice.get("total_budget"),
        "total_budget": destination_choice.get("total_budget") or questionnaire.get("budget_par_personne"),
        "average_weather": destination_choice.get("average_weather"),
        "travel_style": destination_choice.get("travel_style"),
        "travel_style_en": destination_choice.get("travel_style_en"),
        "start_date": questionnaire.get("date_depart"),
        "travelers": questionnaire.get("nombre_voyageurs"),
        "price_flights": flights.get("price"),
        "price_hotels": lodging.get("price"),
        "price_transport": destination_choice.get("price_transport"),
        "price_activities": activities.get("price"),
    }

    if not trip_core.get("main_image"):
        trip_core["main_image"] = _build_fallback_image(trip_core.get("destination"))

    # Steps extraction
    steps = []
    if activities.get("steps"):
        if isinstance(activities["steps"], list):
            for step in activities["steps"]:
                if isinstance(step, dict):
                    steps.append(step)
    # Add summary step if not present
    has_summary = any(step.get("is_summary") for step in steps if isinstance(step, dict))
    if not has_summary:
        steps.append(
            {
                "step_number": len(steps) + 1,
                "day_number": normalized_trip_request.get("nuits_exactes") or 1,
                "title": "Résumé du voyage",
                "main_image": destination_choice.get("main_image") or trip_core.get("main_image") or DEFAULT_MAIN_IMAGE,
                "is_summary": True,
                "step_type": "récapitulatif",
                "summary_stats": _extract_summary_stats(destination_choice),
            }
        )

    # 🔧 Images complètes pour chaque step
    for step in steps:
        if not isinstance(step, dict):
            continue

        if not step.get("main_image"):
            step["main_image"] = trip_core.get("main_image") or _build_fallback_image(trip_core.get("destination"))

        images = step.get("images") if isinstance(step.get("images"), list) else []
        if step.get("main_image") and step["main_image"] not in images:
            images.insert(0, step["main_image"])
        step["images"] = images

    trip = {
        "trip": {
            **trip_core,
            "steps": steps,
        }
    }

    return trip
