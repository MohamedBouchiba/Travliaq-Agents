"""Budget Calculator - Deterministic script to replace Agent 7.

This script calculates trip budget from Phase 2 results without using LLM.
"""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def calculate_trip_budget(
    parsed_phase2: Dict[str, Any],
    trip_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calculate trip budget from Phase 2 results.

    Args:
        parsed_phase2: Results from Phase 2 (flights, accommodation, itinerary)
        trip_context: Normalized trip context with budget info

    Returns:
        Dict with budget_summary structure matching Agent 7 output format
    """
    logger.info("💰 Calculating trip budget...")

    # Extract travelers count
    travelers_count = trip_context.get("travelers", {}).get("travelers_count", 1)

    # 1. Extract costs from Phase 2
    flights_data = parsed_phase2.get("flights_research", {}).get("flight_quotes", {})
    accommodation_data = parsed_phase2.get("accommodation_research", {}).get("lodging_quotes", {})
    itinerary_data = parsed_phase2.get("itinerary_design", {}).get("itinerary_plan", {})

    # Flights
    flights_total = 0
    if flights_data and "total" in flights_data:
        flights_total = flights_data["total"].get("total_price", 0) or 0

    # Accommodation
    accommodation_total = 0
    if accommodation_data and "recommended" in accommodation_data:
        accommodation_total = accommodation_data["recommended"].get("total_price", 0) or 0

    # Activities (sum of all step prices except summary)
    activities_total = 0
    activities_details = []
    if itinerary_data and "steps" in itinerary_data:
        for step in itinerary_data["steps"]:
            if not step.get("is_summary", False):
                price = step.get("price", 0) or 0
                if price > 0:
                    activities_total += price
                    activities_details.append(f"{step.get('title', 'Activity')}: {price}€")

    # Transport local: estimate 10-15€/day/person
    total_days = trip_context.get("duration", {}).get("total_days", 7) or 7
    transport_per_day = 12  # Average
    transport_total = transport_per_day * total_days * travelers_count

    # 2. Calculate total
    total = flights_total + accommodation_total + activities_total + transport_total
    per_person = total / travelers_count if travelers_count > 0 else total

    # Round to nearest 10
    total = round(total / 10) * 10
    per_person = round(per_person / 10) * 10

    # 3. Compare with user budget
    user_budget = trip_context.get("budget", {}).get("budget_amount", 0)

    status = "OK"
    delta_percent = 0
    recommendations = []

    if user_budget > 0:
        delta = total - user_budget
        delta_percent = (delta / user_budget) * 100

        if delta_percent <= 5:
            status = "OK"
            recommendations.append("Le budget est respecté")
        elif delta_percent <= 15:
            status = "WARN"
            recommendations.append(f"Léger dépassement de {round(delta_percent, 1)}%")
            recommendations.append("Envisager de réduire les activités payantes")
        else:
            status = "EXCEED"
            recommendations.append(f"Dépassement important de {round(delta_percent, 1)}%")
            recommendations.append("Réduire le confort d'hébergement")
            recommendations.append("Choisir des vols avec escale")
            recommendations.append("Limiter les activités payantes")

    # 4. Build budget_summary structure
    budget_summary = {
        "breakdown": {
            "flights": {
                "total": flights_total,
                "per_person": round(flights_total / travelers_count) if travelers_count > 0 else flights_total,
                "currency": "EUR",
                "source": "flight_quotes"
            },
            "accommodation": {
                "total": accommodation_total,
                "per_person": round(accommodation_total / travelers_count) if travelers_count > 0 else accommodation_total,
                "currency": "EUR",
                "source": "lodging_quotes"
            },
            "activities": {
                "total": round(activities_total),
                "per_person": round(activities_total / travelers_count) if travelers_count > 0 else activities_total,
                "currency": "EUR",
                "source": "itinerary_plan (somme des step.price)",
                "details": activities_details if activities_details else ["Aucune activité payante"]
            },
            "transport_local": {
                "total": transport_total,
                "per_person": round(transport_total / travelers_count) if travelers_count > 0 else transport_total,
                "currency": "EUR",
                "source": f"estimation ({transport_per_day}€/jour/personne)",
                "note": f"Basé sur {total_days} jours et {travelers_count} voyageur(s)"
            }
        },
        "total": {
            "amount": total,
            "per_person": per_person,
            "currency": "EUR"
        },
        "comparison": {
            "user_budget": user_budget,
            "calculated_total": total,
            "delta": total - user_budget if user_budget > 0 else 0,
            "delta_percent": round(delta_percent, 1),
            "status": status
        },
        "recommendations": recommendations
    }

    logger.info(f"✅ Budget calculated: {total}€ total, {per_person}€ per person (status: {status})")

    return {"budget_summary": budget_summary}
